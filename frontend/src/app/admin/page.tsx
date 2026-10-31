"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { StatusBadge } from "@/components/case-ui";
import { TaskList } from "@/components/task-list";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { HAPPY_PATH, relative, STATUS_LABEL } from "@/lib/format";
import type { CaseStatus } from "@/lib/types";

interface Overview {
  cases_by_status: Partial<Record<CaseStatus, number>>;
  cases: { id: string; status: CaseStatus; patient_name: string; created_at: string; updated_at: string; open_tasks: number }[];
  model_usage: { provider: string; model_id: string; status: string; calls: number; avg_latency_ms: number; total_tokens: number }[];
}

export default function AdminOverview() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin-overview"], queryFn: () => api.get<Overview>("/admin/overview"), refetchInterval: 10_000 });
  const run = useMutation({
    mutationFn: () => api.post<{ started: unknown[] }>("/admin/follow-up/run"),
    onSuccess: (r) => {
      toast.success(`Follow-up agent checked ${r.started.length} case(s)`);
      qc.invalidateQueries();
    },
  });
  const d = q.data;
  const statuses = [...HAPPY_PATH, "PROCESSING_FAILED", "NEEDS_CORRECTION", "CONSENT_WITHDRAWN", "HANDOFF_CANCELLED"] as CaseStatus[];

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Workflow overview</h1>
          <p className="text-muted-foreground">Operational view only. Administrators can&apos;t see report contents or AI summaries.</p>
        </div>
        <Button onClick={() => run.mutate()} disabled={run.isPending} data-testid="run-follow-up">
          {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <Bot className="size-4" />} Run follow-up agent
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {statuses
          .filter((s) => d?.cases_by_status[s])
          .map((s) => (
            <Card key={s}>
              <CardContent className="pt-5">
                <p className="text-2xl font-semibold">{d?.cases_by_status[s]}</p>
                <p className="text-xs text-muted-foreground">{STATUS_LABEL[s]}</p>
              </CardContent>
            </Card>
          ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Cases</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Patient</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead>Open tasks</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d?.cases.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{c.patient_name}</TableCell>
                    <TableCell>
                      <StatusBadge status={c.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">{relative(c.updated_at)}</TableCell>
                    <TableCell>{c.open_tasks}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Meta model usage</CardTitle>
              <CardDescription>
                Every inference is logged with model, latency and tokens. <Link href="/admin/agent" className="underline">Details</Link>
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Calls</TableHead>
                    <TableHead>Avg latency</TableHead>
                    <TableHead>Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d?.model_usage.map((m) => (
                    <TableRow key={`${m.model_id}-${m.status}`}>
                      <TableCell className="font-mono text-xs">
                        {m.provider}/{m.model_id}
                      </TableCell>
                      <TableCell>{m.status}</TableCell>
                      <TableCell>{m.calls}</TableCell>
                      <TableCell>{(m.avg_latency_ms / 1000).toFixed(1)}s</TableCell>
                      <TableCell>{m.total_tokens.toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Administrative follow-ups</CardTitle>
              <CardDescription>Tasks created from clinician decisions and by the follow-up agent.</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <TaskList endpoint="/admin/tasks" queryKey="admin-tasks" />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
