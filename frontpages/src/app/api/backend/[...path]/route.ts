import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const cookieName = "harness_session";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = path.join("/");
  const method = request.method;
  const health = method === "GET" && target === "health";
  const login = method === "POST" && target === "auth/login";
  const taskItem = /^tasks\/[0-9a-f-]{36}(?:\/(events|execution|executions|resume|cancel|messages))?$/.test(target);
  const userItem = /^users\/[1-9]\d*$/.test(target);
  const memoryItem = /^user-memories\/[1-9]\d*$/.test(target);
  const allowed = health || login || (
    method === "GET" && (target === "auth/me" || target === "users" || target === "user-memories" || target === "tasks" || (taskItem && !/\/(resume|cancel)$/.test(target)))
  ) || (method === "POST" && (target === "auth/logout" || target === "users" || /^users\/[1-9]\d*\/reset-password$/.test(target) || target === "tasks" || (taskItem && /\/(resume|cancel|messages)$/.test(target))))
    || (method === "PATCH" && (userItem || memoryItem || /^tasks\/[0-9a-f-]{36}$/.test(target)))
    || (method === "DELETE" && (memoryItem || /^tasks\/[0-9a-f-]{36}$/.test(target)))
    || (method === "PUT" && target === "auth/password");
  if (!allowed) return NextResponse.json({ detail: "接口不存在" }, { status: 404 });
  const writing = ["POST", "PATCH", "PUT", "DELETE"].includes(method);
  const hasBody = ["POST", "PATCH", "PUT"].includes(method);
  if (writing) {
    // Cookie 写请求必须来自受信任的前端站点，包括登录和退出。
    const origin = process.env.FRONTEND_ORIGIN ?? request.nextUrl.origin;
    if (request.headers.get("origin") !== origin) return NextResponse.json({ detail: "请求来源不被允许" }, { status: 403 });
  }
  const token = request.cookies.get(cookieName)?.value;
  if (!health && !login && !token) return NextResponse.json({ detail: "请先登录" }, { status: 401 });
  const url = new URL(health ? "/health" : `/api/v1/${target}`, process.env.HARNESS_API_URL ?? "http://127.0.0.1:8000");
  url.search = request.nextUrl.search;
  const headers = new Headers({ accept: request.headers.get("accept") ?? "application/json" });
  // 忽略浏览器的 Authorization，令牌只从 HttpOnly Cookie 获取。
  if (token && !login) headers.set("authorization", `Bearer ${token}`);
  const cursor = request.headers.get("last-event-id");
  if (cursor) headers.set("last-event-id", cursor);
  if (hasBody) headers.set("content-type", "application/json");
  const cookieOptions = { httpOnly: true, sameSite: "lax" as const, secure: process.env.NODE_ENV === "production", path: "/" };
  try {
    const streaming = target.endsWith("/events");
    const upstream = await fetch(url, {
      method, headers, body: hasBody ? await request.text() : undefined, cache: "no-store", redirect: "error",
      signal: streaming ? request.signal : AbortSignal.any([request.signal, AbortSignal.timeout(15_000)]),
    });
    if (login && upstream.ok) {
      const result = await upstream.json();
      if (typeof result.access_token !== "string" || !Number.isInteger(result.expires_in)) throw new Error("登录响应不合法");
      // 令牌只写入 Cookie，绝不放入浏览器可读取的 JSON。
      const response = NextResponse.json({ user: result.user }, { headers: { "Cache-Control": "no-store" } });
      response.cookies.set(cookieName, result.access_token, { ...cookieOptions, maxAge: result.expires_in });
      return response;
    }
    const response = new NextResponse(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no" },
    });
    // 把后端轮次追踪编号透传到浏览器，方便定位 API 与 Worker。
    const traceId = upstream.headers.get("x-trace-id");
    if (traceId) response.headers.set("X-Trace-ID", traceId);
    if ((upstream.status === 401 && target !== "auth/password") || (target === "auth/logout" && upstream.ok) || (target === "auth/password" && upstream.ok)) {
      response.cookies.set(cookieName, "", { ...cookieOptions, maxAge: 0 });
    }
    return response;
  } catch {
    return NextResponse.json({ detail: "暂时无法连接后端，请确认 FastAPI 已启动" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE };
