import { requireUser } from "@/lib/auth-server";
import { AuthProvider } from "@/components/auth/auth-provider";
import { UserManagement } from "@/components/admin/user-management";

export default async function UserManagementPage() {
  const user = await requireUser(true);
  return <AuthProvider user={user}><UserManagement /></AuthProvider>;
}
