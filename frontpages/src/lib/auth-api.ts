export async function accountApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...options, headers: { "Content-Type": "application/json", ...options.headers },
    cache: "no-store", signal: options.signal ?? AbortSignal.timeout(20_000),
  });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((item: {msg?: string}) => item.msg).join("；");
    } catch { /* 非 JSON 响应保留状态说明。 */ }
    if (response.status === 401 && path !== "auth/login" && !path.includes("password")) window.location.replace("/login");
    throw new Error(detail);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
