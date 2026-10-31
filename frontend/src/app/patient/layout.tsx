import { AppShell } from "@/components/app-shell";

export default function PatientLayout({ children }: { children: React.ReactNode }) {
  return <AppShell role="PATIENT">{children}</AppShell>;
}
