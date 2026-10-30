"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="grid min-h-dvh place-items-center bg-background p-6"><div className="max-w-sm text-center"><h1 className="text-xl font-semibold">工作台暂时遇到问题</h1><p className="my-4 text-sm leading-7 text-muted-foreground">可以尝试重新载入。服务器上已经提交的任务不会因为页面错误而停止。</p><Button onClick={reset}>重新载入</Button></div></main>;
}
