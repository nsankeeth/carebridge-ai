"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Task } from "@/lib/types";

export function TaskList({ endpoint, queryKey }: { endpoint: string; queryKey: string }) {
  const qc = useQueryClient();
  const tasks = useQuery({ queryKey: [queryKey], queryFn: () => api.get<Task[]>(endpoint), refetchInterval: 10_000 });
  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: Task["status"] }) => api.patch(`${endpoint}/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [queryKey] }),
  });
  if (!tasks.data?.length) return <p className="p-6 text-center text-muted-foreground">No follow-up tasks.</p>;
  return (
    <ul className="divide-y" data-testid="task-list">
      {tasks.data.map((t) => (
        <li key={t.id} className="flex flex-wrap items-center gap-3 px-6 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm">{t.description}</p>
            <p className="text-xs text-muted-foreground">
              {t.kind} · {t.created_by === "agent" ? "created by care-coordination agent" : "created by clinician"} · due {formatDate(t.due_at, true)}
              {queryKey === "clinician-tasks" && (
                <>
                  {" "}·{" "}
                  <Link className="underline" href={`/clinician/cases/${t.case_id}`}>
                    open case
                  </Link>
                </>
              )}
            </p>
          </div>
          <Badge variant={t.status === "OPEN" ? "default" : "secondary"}>{t.status.toLowerCase()}</Badge>
          {t.status === "OPEN" && (
            <Button size="sm" variant="outline" onClick={() => update.mutate({ id: t.id, status: "DONE" })}>
              Mark done
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
