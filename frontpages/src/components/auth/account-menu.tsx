"use client";
import Link from "next/link";
import { LogOut, Settings2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { accountApi } from "@/lib/auth-api";
import { leaveWorkspace, useAuthUser } from "@/components/auth/auth-provider";
import { useState } from "react";

export function AccountMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const user = useAuthUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function logout() {
    setBusy(true); setError("");
    try { await accountApi("auth/logout", { method: "POST" }); leaveWorkspace(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "退出失败"); setBusy(false); }
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent>
    <DialogTitle className="text-lg font-semibold">{user.display_name}</DialogTitle>
    <DialogDescription className="mt-2 text-sm text-muted-foreground">{user.tenant_name} · {user.role === "admin" ? "管理员" : "成员"} · @{user.username}</DialogDescription>
    <div className="mt-6 grid gap-3">
      {user.role === "admin" && <Button asChild variant="outline"><Link href="/admin/users"><Users />用户管理</Link></Button>}
      <Button asChild variant="outline"><Link href="/account"><Settings2 />个人中心</Link></Button>
      <Button variant="ghost" disabled={busy} onClick={() => void logout()}><LogOut />{busy ? "正在退出…" : "退出登录"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </DialogContent></Dialog>;
}
