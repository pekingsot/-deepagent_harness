import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = path.join("/");
  const health = request.method === "GET" && target === "health";
  // 只代理现有任务接口，禁止客户端指定上游地址。
  const collection = target === "tasks";
  const item = /^tasks\/[0-9a-f-]{36}(?:\/(events|execution|resume|cancel|messages))?$/.test(target);
  const validGet = collection || (item && !/\/(resume|cancel)$/.test(target));
  const validPost = collection || (item && /\/(resume|cancel|messages)$/.test(target));
  const validPatch = /^tasks\/[0-9a-f-]{36}$/.test(target);
  const permitted = request.method === "GET" ? validGet : request.method === "POST" ? validPost : request.method === "PATCH" && validPatch;
  if (!health && !permitted) {
    return Response.json({ detail: "不支持的任务接口" }, { status: 404 });
  }
  const authorization = request.headers.get("authorization");
  if (!health && !authorization?.startsWith("Bearer ")) {
    return Response.json({ detail: "请先配置访问令牌" }, { status: 401 });
  }
  const base = process.env.HARNESS_API_URL ?? "http://127.0.0.1:8000";
  const url = new URL(health ? "/health" : `/api/v1/${target}`, base);
  url.search = request.nextUrl.search;
  const headers = new Headers({ accept: request.headers.get("accept") ?? "application/json" });
  if (authorization) headers.set("authorization", authorization);
  const cursor = request.headers.get("last-event-id");
  if (cursor) headers.set("last-event-id", cursor);
  if (["POST", "PATCH"].includes(request.method)) headers.set("content-type", "application/json");

  try {
    const streaming = target.endsWith("/events");
    const signal = streaming ? request.signal : AbortSignal.any([request.signal, AbortSignal.timeout(15_000)]);
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body: ["POST", "PATCH"].includes(request.method) ? await request.text() : undefined,
      cache: "no-store",
      redirect: "error",
      signal,
    });
    const responseHeaders = new Headers({
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    });
    // 直接转发 ReadableStream，不等待 SSE 完成，也不缓存完整响应。
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: "无法连接任务服务，请检查 FastAPI 是否启动及 HARNESS_API_URL 配置" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH };
