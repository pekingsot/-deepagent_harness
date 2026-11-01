import { Workspace } from "@/components/workspace/workspace";
import { requireUser } from "@/lib/auth-server";
import { AuthProvider } from "@/components/auth/auth-provider";

export default async function Home() {
  const user = await requireUser();
  return <AuthProvider user={user}><Workspace /></AuthProvider>;
}
