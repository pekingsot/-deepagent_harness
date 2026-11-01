import { requireUser } from "@/lib/auth-server";
import { AuthProvider } from "@/components/auth/auth-provider";
import { AccountSettings } from "@/components/auth/account-settings";

export const metadata = { title: "个人中心 | Agent Workspace" };

export default async function AccountPage() {
  const user = await requireUser();
  return <AuthProvider user={user}><AccountSettings /></AuthProvider>;
}
