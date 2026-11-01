"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, FileText, MessageCircleHeart } from "lucide-react";
import Link from "next/link";
import { StatusBadge } from "@/components/case-ui";
import { NewThreadComposer } from "@/components/thread/composer";
import { UrgencyBadge } from "@/components/thread/urgency-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/hooks/use-me";
import { api } from "@/lib/api";
import { relative } from "@/lib/format";
import type { ThreadListItem } from "@/lib/types";

export default function PatientHome() {
  const me = useMe();
  const threads = useQuery({
    queryKey: ["patient-threads"],
    queryFn: () => api.get<ThreadListItem[]>("/patient/threads"),
    refetchInterval: 15_000,
  });

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Hi {me.data?.full_name.split(" ")[0]}, what’s going on today?</h1>
        <p className="text-muted-foreground">Tell us what’s happening. We’ll work out how urgent it is and get the right clinician on it.</p>
      </div>

      <NewThreadComposer />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your conversations</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {threads.isLoading ? (
            <div className="space-y-2 p-6">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : threads.data?.length ? (
            <ul className="divide-y" data-testid="thread-list">
              {threads.data.map((t) => (
                <li key={t.id}>
                  <Link
                    href={t.kind === "SYMPTOM" ? `/patient/threads/${t.id}` : `/patient/cases/${t.id}`}
                    className="flex items-center gap-3 px-4 py-3 transition hover:bg-muted/50 sm:px-6"
                  >
                    {t.kind === "SYMPTOM" ? <MessageCircleHeart className="size-5 shrink-0 text-primary" /> : <FileText className="size-5 shrink-0 text-primary" />}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{t.title}</p>
                      <p className="truncate text-sm text-muted-foreground">
                        {t.subject_name} · {relative(t.last_message_at)}
                      </p>
                    </div>
                    {t.kind === "SYMPTOM" ? <UrgencyBadge level={t.urgency} /> : <StatusBadge status={t.status} />}
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="p-8 text-center text-muted-foreground">No conversations yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
