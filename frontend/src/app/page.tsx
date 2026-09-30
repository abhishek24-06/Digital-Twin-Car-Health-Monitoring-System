import { redirect } from "next/navigation";

/** The product root is the dashboard; unauthenticated users are bounced to login. */
export default function RootPage() {
  redirect("/dashboard");
}
