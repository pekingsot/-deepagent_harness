// 使用 Node 自带测试器；上游 fetch 完全替代，不发送外部请求。
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const ts = require("typescript");
const { NextRequest } = require("next/server");
const route = path.join(__dirname, "../src/app/api/backend/[...path]/route.ts");
const compiled = ts.transpileModule(fs.readFileSync(route, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const loaded = { exports: {} };
new Function("require", "module", "exports", compiled)(createRequire(route), loaded, loaded.exports);
const handlers = loaded.exports;
const origin = "http://localhost:3000";

function request(target, method = "GET", options = {}) {
  return new NextRequest(`${origin}/api/backend/${target}`, { method, ...options });
}
function context(target) { return { params: Promise.resolve({ path: target.split("/") }) }; }

test("认证代理的 Cookie、安全边界和 SSE 转发", async (t) => {
  const original = global.fetch;
  await t.test("执行轮次历史可读取，拒绝向历史接口写入", async () => {
    const target = "tasks/11111111-1111-4111-8111-111111111111/executions";
    global.fetch = async () => Response.json([]);
    try {
      const response = await handlers.GET(request(target, "GET", { headers: { Cookie: "harness_session=trusted-session" } }), context(target));
      assert.equal(response.status, 200);
      const rejected = await handlers.POST(request(target, "POST", { headers: { Origin: origin, Cookie: "harness_session=trusted-session" }, body: "{}" }), context(target));
      assert.equal(rejected.status, 404);
    } finally { global.fetch = original; }
  });
  await t.test("透传后端追踪编号，不接收浏览器伪造的追踪上下文", async () => {
    const traceId = "1234567890abcdef1234567890abcdef";
    global.fetch = async (_url, options) => {
      assert.equal(options.headers.get("traceparent"), null);
      return Response.json({}, { headers: { "X-Trace-ID": traceId } });
    };
    try {
      const response = await handlers.POST(request("tasks", "POST", {
        headers: { Origin: origin, Cookie: "harness_session=trusted-session", traceparent: "forged" },
        body: "{}",
      }), context("tasks"));
      assert.equal(response.headers.get("x-trace-id"), traceId);
    } finally {
      global.fetch = original;
    }
  });
  const originalOrigin = process.env.FRONTEND_ORIGIN;
  process.env.FRONTEND_ORIGIN = origin;
  t.after(() => { global.fetch = original; if (originalOrigin === undefined) delete process.env.FRONTEND_ORIGIN; else process.env.FRONTEND_ORIGIN = originalOrigin; });
  let calls = [];
  global.fetch = async (...args) => { calls.push(args); throw new Error("不应该请求上游"); };
  await t.test("没有 Cookie 时拒绝聊天请求", async () => {
    const response = await handlers.GET(request("tasks"), context("tasks"));
    assert.equal(response.status, 401); assert.equal(calls.length, 0);
  });
  await t.test("拒绝跨站写入和伪造 Authorization", async () => {
    const response = await handlers.POST(request("auth/login", "POST", { headers: { Origin: "https://foreign.example" }, body: "{}" }), context("auth/login"));
    assert.equal(response.status, 403); assert.equal(calls.length, 0);
    const forged = await handlers.GET(request("tasks", "GET", { headers: { Authorization: "Bearer forged" } }), context("tasks"));
    assert.equal(forged.status, 401);
  });
  await t.test("登录只返回用户，令牌进入 HttpOnly Cookie", async () => {
    global.fetch = async () => Response.json({ access_token: "server-secret-token", expires_in: 3600, user: { id: 42 } });
    const response = await handlers.POST(request("auth/login", "POST", { headers: { Origin: origin }, body: "{}" }), context("auth/login"));
    assert.deepEqual(await response.json(), { user: { id: 42 } });
    const cookie = response.headers.get("set-cookie");
    assert.match(cookie, /HttpOnly/i); assert.match(cookie, /SameSite=lax/i); assert.match(cookie, /Max-Age=3600/i);
  });
  await t.test("业务身份使用 Cookie，忽略浏览器提交的令牌", async () => {
    global.fetch = async (_url, options) => {
      assert.equal(options.headers.get("authorization"), "Bearer trusted-session");
      return Response.json([]);
    };
    const response = await handlers.GET(request("tasks", "GET", { headers: { Cookie: "harness_session=trusted-session", Authorization: "Bearer forged" } }), context("tasks"));
    assert.equal(response.status, 200);
  });
  await t.test("SSE 保留事件流和断点游标", async () => {
    const target = "tasks/00000000-0000-0000-0000-000000000001/events";
    global.fetch = async (_url, options) => {
      assert.equal(options.headers.get("last-event-id"), "123-4");
      return new Response("id: 124-0\nevent: completed\ndata: {}\n\n", { headers: { "Content-Type": "text/event-stream" } });
    };
    const response = await handlers.GET(request(target, "GET", { headers: { Cookie: "harness_session=trusted-session", "Last-Event-ID": "123-4" } }), context(target));
    assert.match(response.headers.get("content-type"), /text\/event-stream/);
    assert.match(await response.text(), /event: completed/);
  });
  await t.test("退出与密码修改成功清除 Cookie，旧密码填错不清除", async () => {
    for (const target of ["auth/logout", "auth/password"]) {
      const method = target.endsWith("password") ? "PUT" : "POST";
      global.fetch = async () => new Response(null, { status: 204 });
      const response = await handlers[method](request(target, method, { headers: { Origin: origin, Cookie: "harness_session=trusted-session" }, body: "{}" }), context(target));
      assert.match(response.headers.get("set-cookie"), /Max-Age=0/i);
    }
    global.fetch = async () => Response.json({ detail: "当前密码错误" }, { status: 401 });
    const response = await handlers.PUT(request("auth/password", "PUT", { headers: { Origin: origin, Cookie: "harness_session=trusted-session" }, body: "{}" }), context("auth/password"));
    assert.equal(response.headers.get("set-cookie"), null);
  });
  await t.test("不允许代理任意后端路径", async () => {
    const response = await handlers.GET(request("internal/secrets", "GET", { headers: { Cookie: "harness_session=trusted-session" } }), context("internal/secrets"));
    assert.equal(response.status, 404);
  });
  await t.test("个人记忆查询保留分页，修改和删除使用登录 Cookie", async () => {
    const cookie = { Cookie: "harness_session=trusted-session" };
    global.fetch = async (url, options) => {
      assert.equal(url.pathname, "/api/v1/user-memories");
      assert.equal(url.searchParams.get("cursor"), "30");
      assert.equal(options.headers.get("authorization"), "Bearer trusted-session");
      return Response.json({ items: [], next_cursor: null });
    };
    const listed = await handlers.GET(request("user-memories?cursor=30&limit=20", "GET", { headers: cookie }), context("user-memories"));
    assert.equal(listed.status, 200);
    const target = "user-memories/12";
    global.fetch = async (url, options) => {
      assert.equal(url.pathname, "/api/v1/user-memories/12");
      assert.equal(options.method, "PATCH");
      assert.deepEqual(JSON.parse(options.body), { content: "我喜欢中文注释" });
      return new Response(null, { status: 204 });
    };
    const updated = await handlers.PATCH(request(target, "PATCH", { headers: { ...cookie, Origin: origin }, body: JSON.stringify({ content: "我喜欢中文注释" }) }), context(target));
    assert.equal(updated.status, 204);
    global.fetch = async (_url, options) => {
      assert.equal(options.method, "DELETE");
      assert.equal(options.body, undefined);
      assert.equal(options.headers.get("authorization"), "Bearer trusted-session");
      return new Response(null, { status: 204 });
    };
    const deleted = await handlers.DELETE(request(target, "DELETE", { headers: { ...cookie, Origin: origin } }), context(target));
    assert.equal(deleted.status, 204);
    assert.equal(await deleted.text(), "");
  });
  await t.test("记忆删除拒绝跨站与未登录请求，并禁止其他资源的 DELETE", async () => {
    global.fetch = async () => { throw new Error("不得发送到上游"); };
    const target = "user-memories/12";
    const crossSite = await handlers.DELETE(request(target, "DELETE", { headers: { Origin: "https://foreign.example", Cookie: "harness_session=trusted-session" } }), context(target));
    assert.equal(crossSite.status, 403);
    const anonymous = await handlers.DELETE(request(target, "DELETE", { headers: { Origin: origin } }), context(target));
    assert.equal(anonymous.status, 401);
    const otherResource = await handlers.DELETE(request("users/12", "DELETE", { headers: { Origin: origin, Cookie: "harness_session=trusted-session" } }), context("users/12"));
    assert.equal(otherResource.status, 404);
  });
});
