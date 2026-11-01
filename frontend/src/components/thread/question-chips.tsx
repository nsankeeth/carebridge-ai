"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { PatientThread, ThreadQuestion } from "@/lib/types";

export function QuestionChips({ threadId, questions }: { threadId: string; questions: ThreadQuestion[] }) {
  const qc = useQueryClient();
  const answer = useMutation({
    mutationFn: (v: { question_id: string; option: string }) => api.post<PatientThread>(`/patient/threads/${threadId}/answers`, v),
    onSuccess: (data) => qc.setQueryData(["thread", threadId], data),
    onError: (e: Error) => toast.error(e.message),
  });
  if (!questions.length) return null;
  return (
    <div className="space-y-3 rounded-xl border bg-card p-4" data-testid="question-chips">
      {questions.map((q) => (
        <div key={q.id} className="space-y-2">
          <p className="text-sm font-medium">{q.question}</p>
          <div className="flex flex-wrap gap-2">
            {q.options.map((o) => (
              <Button
                key={o}
                size="sm"
                variant="outline"
                disabled={answer.isPending}
                data-testid={`question-${q.id}-${o.toLowerCase().replace(/\s+/g, "-")}`}
                onClick={() => answer.mutate({ question_id: q.id, option: o })}
              >
                {o}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
