import { redirect } from "next/navigation";
import { currentUser } from "@/lib/auth-server";
import { LoginForm } from "@/components/auth/login-form";

export default async function LoginPage() {
  if (await currentUser()) redirect("/");
  return <LoginForm />;
}
