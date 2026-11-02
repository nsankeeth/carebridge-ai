"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Siren } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FindingsTable, StatusBadge } from "@/components/case-ui";
import { ClinicianActions, ClinicianReply } from "@/components/thread/clinician-actions";
import { ClinicianBriefPanel } from "@/components/thread/clinician-brief";
import { MessageList } from "@/components/thread/message-list";
import { UrgencyBadge } from "@/components/thread/urgency-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api";
import { ageLabel, URGENCY_LABEL } from "@/lib/format";
import type { ClinicianThread } from "@/lib/types";

export default function ClinicianThreadPage() {
  const { id } = useParams<{ id: string }>();
  const thread = useQuery({
    queryKey: ["clinician-thread", id],
    queryFn: () => api.get<ClinicianThread>(`/clinician/threads/${id}`),
    refetchInterval: 10_000,
    retry: (n, e) => !(e instanceof ApiError && [403, 404].includes(e.status)) && n < 2,
  });

  if (thread.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{thread.error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!thread.data) return <Skeleton className="h-64" />;
  const t = thread.data;
  const latest = t.assessments[t.assessments.length - 1];

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <Link href="/clinician" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Queue
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">
            {t.subject.name}
            {t.subject.age_years != null && <span className="font-normal text-muted-foreground"> ({ageLabel(t.subject.age_years)})</span>}
          </h1>
          <UrgencyBadge level={t.urgency} />
          <StatusBadge status={t.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {t.subject.relation !== "self" ? `Parent: ${t.patient_name} · ` : ""}urgency set by {t.urgency_set_by ?? "—"}
        </p>
      </div>

      {t.emergency && (
        <Alert className="border-red-300 bg-red-50 dark:bg-red-950/40">
          <Siren className="size-4 text-red-600" />
          <AlertDescription>The patient was told to call 911. Consider calling them now.</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <MessageList messages={t.messages} attachments={t.attachments} viewer="CLINICIAN" />
          <ClinicianReply thread={t} />
          {t.findings.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Attached report</CardTitle>
              </CardHeader>
              <CardContent>
                <FindingsTable findings={t.findings} showSource />
              </CardContent>
            </Card>
          )}
        </div>
        <div className="space-y-4 lg:col-span-2">
          {latest && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Why it’s {t.urgency ? URGENCY_LABEL[t.urgency].toLowerCase() : "pending"}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  <span className="text-muted-foreground">Rules:</span> {latest.rule_level ?? "no red flag"}
                  {latest.rule_flags.length > 0 && ` (${latest.rule_flags.join(", ").replaceAll("_", " ")})`}
                </p>
                <p>
                  <span className="text-muted-foreground">Meta:</span> {latest.model_level ?? (latest.status === "model_failed" ? "unavailable" : "pending")}
                </p>
                {latest.reasons.length > 0 && (
                  <ul className="list-disc pl-5 text-muted-foreground">{latest.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                )}
              </CardContent>
            </Card>
          )}
          <ClinicianActions thread={t} />
          <ClinicianBriefPanel thread={t} />
        </div>
      </div>
    </div>
  );
}
