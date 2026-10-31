import { AppShell } from "@/components/app-shell";

export default function ClinicianLayout({ children }: { children: React.ReactNode }) {
  return <AppShell role="CLINICIAN">{children}</AppShell>;
}
