"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Cpu, HeartPulse, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAiStatus, useMe } from "@/hooks/use-me";
import { api } from "@/lib/api";
import { relative } from "@/lib/format";
import type { Notification, Role } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV: Record<Role, { href: string; label: string }[]> = {
  PATIENT: [{ href: "/patient", label: "My cases" }, { href: "/patient/upload", label: "Upload report" }],
  CLINICIAN: [{ href: "/clinician", label: "Assigned cases" }, { href: "/clinician/tasks", label: "Follow-ups" }],
  ADMIN: [
    { href: "/admin", label: "Overview" },
    { href: "/admin/agent", label: "Agent & Meta AI" },
    { href: "/admin/users", label: "Demo accounts" },
    { href: "/admin/audit", label: "Audit log" },
  ],
};

export function AppShell({ role, children }: { role: Role; children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const me = useMe();
  const ai = useAiStatus();
  const notifications = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<Notification[]>("/notifications"),
    refetchInterval: 10_000,
    enabled: !!me.data,
  });
  const readAll = useMutation({
    mutationFn: () => api.post("/notifications/read-all"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const logout = useMutation({
    mutationFn: () => api.post("/auth/logout"),
    onSettled: () => {
      qc.clear();
      router.replace("/login");
    },
  });

  useEffect(() => {
    if (me.data && me.data.role !== role) router.replace("/");
    if (me.isError) router.replace("/login");
  }, [me.data, me.isError, role, router]);

  if (!me.data || me.data.role !== role) return null;
  const unread = notifications.data?.filter((n) => !n.read).length ?? 0;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b bg-card/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <HeartPulse className="size-5 text-primary" /> CareBridge
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {NAV[role].map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground",
                  pathname === n.href && "bg-muted text-foreground font-medium",
                )}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {ai.data && (
              <Badge
                variant="outline"
                className="hidden sm:inline-flex gap-1 border-primary/40 text-primary"
                title={`Meta Model API · ${ai.data.base_url}`}
              >
                <Cpu className="size-3" /> Meta · {ai.data.model}
              </Badge>
            )}
            <DropdownMenu onOpenChange={(open) => !open && unread > 0 && readAll.mutate()}>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="relative" aria-label="Notifications">
                  <Bell className="size-5" />
                  {unread > 0 && (
                    <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-destructive text-[10px] text-white">
                      {unread}
                    </span>
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-80">
                <DropdownMenuLabel>Notifications</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <div className="max-h-96 overflow-y-auto">
                  {notifications.data?.length ? (
                    notifications.data.map((n) => (
                      <div key={n.id} className={cn("px-3 py-2 text-sm", !n.read && "bg-accent/50")}>
                        <p className="font-medium">{n.title}</p>
                        <p className="text-muted-foreground">{n.body}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {relative(n.created_at)}
                          {n.source === "agent" && " · sent by care-coordination agent"}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="px-3 py-6 text-center text-sm text-muted-foreground">No notifications yet</p>
                  )}
                </div>
              </DropdownMenuContent>
            </DropdownMenu>
            <div className="hidden sm:block text-right leading-tight">
              <p className="text-sm font-medium">{me.data.full_name}</p>
              <p className="text-xs text-muted-foreground capitalize">{role.toLowerCase()}</p>
            </div>
            <Button variant="ghost" size="icon" onClick={() => logout.mutate()} aria-label="Sign out">
              <LogOut className="size-4" />
            </Button>
          </div>
        </div>
        <nav className="flex md:hidden gap-1 overflow-x-auto px-4 pb-2">
          {NAV[role].map((n) => (
            <Link key={n.href} href={n.href} className="whitespace-nowrap rounded-md px-3 py-1 text-sm text-muted-foreground hover:bg-muted">
              {n.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
    </div>
  );
}
