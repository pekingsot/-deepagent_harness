import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Workspace · 智能任务工作台",
  description: "规划复杂任务，协作执行，掌握每一步进展。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
