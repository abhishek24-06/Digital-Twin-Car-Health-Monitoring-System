import type { Metadata } from "next";
import { ProfileView } from "@/components/profile/profile-view";

export const metadata: Metadata = {
  title: "Profile",
  description: "Manage your account details and role information.",
};

export default function ProfilePage() {
  return <ProfileView />;
}
