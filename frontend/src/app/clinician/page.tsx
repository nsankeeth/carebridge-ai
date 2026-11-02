"use client";

import { useQuery } from "@tanstack/react-query";
import { AlarmClock, ChevronRight, FileText, Inbox, MessageCircleHeart, Timer } from "lucide-react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { StatusBadge } from "@/components/case-ui";
import { UrgencyBadge } from "@/components/thread/urgency-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ageLabel, relative } from "@/lib/format";
import { api } from "@/lib/api";
import type { QueueRow, Task } from "@/lib/types";
import { cn } from "@/lib/utils";

function Countdown({ due }: { due: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!due) return null;
  const ms = new Date(due).getTime() - now;
  const mins = Math.floor(Math.abs(ms) / 60000);
  const secs = Math.floor((Math.abs(ms) % 60000) / 1000);
  const text = mins >= 120 ? `${Math.round(mins / 60)} h` : `${mins}:${String(secs).padStart(2, "0")}`;
  return (
    <span data-testid="ack-countdown" className={cn("flex items-center gap-1 font-mono text-xs", ms < 0 ? "text-red-600" : ms < 5 * 60000 ? "text-amber-700" : "text-muted-foreground")}>
      <Timer className="size-3.5" /> {ms < 0 ? `overdue ${text}` : `respond in ${text}`}
    </span>
  );
}

export default function ClinicianQueue() {
  const queue = useQuery({ queryKey: ["clinician-queue"], queryFn: () => api.get<QueueRow[]>("/clinician/queue"), refetchInterval: 5000 });
  const tasks = useQuery({ queryKey: ["clinician-tasks"], queryFn: () => api.get<Task[]>("/clinician/tasks"), refetchInterval: 15_000 });
  const openTasks = tasks.data?.filter((t) => t.status === "OPEN") ?? [];
  const rows = queue.data ?? [];
  const waiting = rows.filter((r) => r.ack_due_at).length;
  const urgent = rows.filter((r) => r.urgency === "URGENT" || r.urgency === "EMERGENCY").length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Queue</h1>
        <p className="text-muted-foreground">Patients who need you, most urgent first.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Urgent or emergency" value={urgent} />
        <Stat label="Waiting for you to acknowledge" value={waiting} />
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
          <CardTitle>Patients</CardTitle>
          <CardDescription>AI briefs and summaries are drafts for your review. You remain responsible for all clinical decisions.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {queue.isLoading ? (
            <Skeleton className="m-6 h-20" />
          ) : rows.length ? (
            <ul className="divide-y" data-testid="clinician-case-list">
              {rows.map((r) => (
                <li key={r.id} data-testid="queue-row" data-urgency={r.urgency ?? ""}>
                  <Link
                    href={r.kind === "SYMPTOM" ? `/clinician/threads/${r.id}` : `/clinician/cases/${r.id}`}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-4 transition hover:bg-muted/50 sm:px-6"
                  >
                    {r.kind === "SYMPTOM" ? <MessageCircleHeart className="size-5 shrink-0 text-primary" /> : <FileText className="size-5 shrink-0 text-primary" />}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">
                        {r.subject_name}
                        {r.subject_age_years != null && <span className="font-normal text-muted-foreground"> ({ageLabel(r.subject_age_years)})</span>}
                        <span className="font-normal text-muted-foreground"> · {r.title}</span>
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {r.subject_name !== r.patient_name && `Parent: ${r.patient_name} · `}first message {relative(r.first_message_at)}
                      </p>
                    </div>
                    <Countdown due={r.ack_due_at} />
                    {r.kind === "SYMPTOM" ? <UrgencyBadge level={r.urgency} /> : <StatusBadge status={r.status} />}
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex flex-col items-center gap-2 p-10 text-muted-foreground">
              <Inbox className="size-8" /> Nothing waiting for you.
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
