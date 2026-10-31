"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, FileText, Upload } from "lucide-react";
import Link from "next/link";
import { StatusBadge } from "@/components/case-ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/hooks/use-me";
import { api } from "@/lib/api";
import { relative } from "@/lib/format";
import type { CaseListItem } from "@/lib/types";

export default function PatientDashboard() {
  const me = useMe();
  const cases = useQuery({
    queryKey: ["patient-cases"],
    queryFn: () => api.get<CaseListItem[]>("/patient/cases"),
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === "PROCESSING") ? 2000 : 15000),
  });

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Welcome back, {me.data?.full_name.split(" ")[0]}</h1>
          <p className="text-muted-foreground">Your lab reports, explanations, and where each one is in your care.</p>
        </div>
        <Button asChild>
          <Link href="/patient/upload">
            <Upload className="size-4" /> Upload a report
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>My cases</CardTitle>
          <CardDescription>Each uploaded report becomes a case you can track from explanation to clinician review.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {cases.isLoading ? (
            <div className="space-y-2 p-6">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : cases.data?.length ? (
            <ul className="divide-y" data-testid="case-list">
              {cases.data.map((c) => (
                <li key={c.id}>
                  <Link href={`/patient/cases/${c.id}`} className="flex items-center gap-4 px-6 py-4 transition hover:bg-muted/50">
                    <FileText className="size-5 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{c.title}</p>
                      <p className="truncate text-sm text-muted-foreground">
                        {c.handoff ? `Shared with ${c.handoff.clinician_name}` : (c.document_name ?? "No report")} · updated {relative(c.updated_at)}
                      </p>
                    </div>
                    <StatusBadge status={c.status} />
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-10 text-center text-muted-foreground">
              No cases yet. <Link className="text-primary underline" href="/patient/upload">Upload your first report</Link>.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
