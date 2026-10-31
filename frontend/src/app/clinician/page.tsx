"use client";

import { useQuery } from "@tanstack/react-query";
import { AlarmClock, ChevronRight, Inbox } from "lucide-react";
import Link from "next/link";
import { StatusBadge } from "@/components/case-ui";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { relative } from "@/lib/format";
import { api } from "@/lib/api";
import type { CaseListItem, Task } from "@/lib/types";

export default function ClinicianDashboard() {
  const cases = useQuery({ queryKey: ["clinician-cases"], queryFn: () => api.get<CaseListItem[]>("/clinician/cases"), refetchInterval: 10_000 });
  const tasks = useQuery({ queryKey: ["clinician-tasks"], queryFn: () => api.get<Task[]>("/clinician/tasks"), refetchInterval: 15_000 });
  const openTasks = tasks.data?.filter((t) => t.status === "OPEN") ?? [];
  const waiting = cases.data?.filter((c) => c.status === "HANDOFF_SENT").length ?? 0;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Assigned cases</h1>
        <p className="text-muted-foreground">Cases patients have explicitly consented to share with you.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Awaiting acknowledgment" value={waiting} />
        <Stat label="Active cases" value={cases.data?.filter((c) => ["ACKNOWLEDGED", "UNDER_REVIEW"].includes(c.status)).length ?? 0} />
        <Stat label="Open follow-ups" value={openTasks.length} />
      </div>

      {openTasks.length > 0 && (
        <Card className="border-amber-300">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <AlarmClock className="size-4 text-amber-600" /> Follow-ups from the care-coordination agent
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {openTasks.map((t) => (
                <li key={t.id}>
                  <Link className="hover:underline" href={`/clinician/cases/${t.case_id}`}>
                    {t.description}
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Inbox</CardTitle>
          <CardDescription>AI summaries are drafts for your review. You remain responsible for all clinical decisions.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {cases.isLoading ? (
            <Skeleton className="m-6 h-20" />
          ) : cases.data?.length ? (
            <ul className="divide-y" data-testid="clinician-case-list">
              {cases.data.map((c) => (
                <li key={c.id}>
                  <Link href={`/clinician/cases/${c.id}`} className="flex items-center gap-4 px-6 py-4 transition hover:bg-muted/50">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">
                        {c.patient_name} <span className="font-normal text-muted-foreground">· {c.title}</span>
                      </p>
                      <p className="text-sm text-muted-foreground">Received {relative(c.handoff?.sent_at)}</p>
                    </div>
                    {c.status === "HANDOFF_SENT" && <Badge variant="destructive">New</Badge>}
                    <StatusBadge status={c.status} />
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex flex-col items-center gap-2 p-10 text-muted-foreground">
              <Inbox className="size-8" /> No cases have been shared with you.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-3xl font-semibold">{value}</p>
        <p className="text-sm text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  );
}
