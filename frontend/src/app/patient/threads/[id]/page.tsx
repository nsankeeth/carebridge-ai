"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/case-ui";
import { ReplyComposer } from "@/components/thread/composer";
import { EmergencyScreen } from "@/components/thread/emergency-screen";
import { MessageList } from "@/components/thread/message-list";
import { QuestionChips } from "@/components/thread/question-chips";
import { UrgencyCard } from "@/components/thread/urgency-card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { ageLabel } from "@/lib/format";
import type { PatientThread } from "@/lib/types";

export default function PatientThreadPage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const thread = useQuery({
    queryKey: ["thread", id],
    queryFn: () => api.get<PatientThread>(`/patient/threads/${id}`),
    refetchInterval: 5000,
  });
  const [dismissed, setDismissed] = useState(false);
  const emergency = thread.data?.emergency ?? search.get("emergency") === "1";

  // A thread that becomes an emergency later (e.g. after an answer) shows the screen again.
  useEffect(() => {
    if (!emergency) setDismissed(false);
  }, [emergency]);

  if (thread.isLoading || !thread.data) {
    return emergency ? (
      <EmergencyScreen steps={[]} onDismiss={() => setDismissed(true)} />
    ) : (
      <div className="mx-auto max-w-3xl space-y-4">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  const t = thread.data;
  const closed = t.status === "CLOSED";

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {emergency && !dismissed && <EmergencyScreen steps={t.emergency_steps} onDismiss={() => setDismissed(true)} />}
      <div className="space-y-1">
        <Link href="/patient" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> All conversations
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="min-w-0 flex-1 truncate text-xl font-semibold">{t.title}</h1>
          <StatusBadge status={t.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          For {t.subject.relation === "self" ? "you" : `${t.subject.name} (${ageLabel(t.subject.age_years)})`}
        </p>
      </div>

      <UrgencyCard thread={t} />
      <MessageList messages={t.messages} attachments={t.attachments} viewer="PATIENT" />
      <QuestionChips threadId={t.id} questions={t.pending_questions} />
      <div className="sticky bottom-3">
        <ReplyComposer threadId={t.id} disabled={closed} />
      </div>
    </div>
  );
}
