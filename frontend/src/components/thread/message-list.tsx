"use client";

import { Bot, FileText, Info, Stethoscope } from "lucide-react";
import { FindingsTable } from "@/components/case-ui";
import { formatDate } from "@/lib/format";
import type { ThreadAttachment, ThreadMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

function questionText(messages: ThreadMessage[], id: string | undefined): string | undefined {
  for (const m of messages) for (const q of m.payload?.questions ?? []) if (q.id === id) return q.question;
}

export function MessageList({
  messages,
  attachments,
  viewer,
}: {
  messages: ThreadMessage[];
  attachments: ThreadAttachment[];
  viewer: "PATIENT" | "CLINICIAN";
}) {
  return (
    <ol className="space-y-3" aria-label="Conversation">
      {messages.map((m) => {
        const kind = m.payload?.kind;
        if (m.author_type === "SYSTEM") {
          return (
            <li key={m.id} data-testid="message" data-author="SYSTEM" className="flex justify-center">
              <p className="flex max-w-[90%] items-start gap-1.5 whitespace-pre-line rounded-full bg-muted px-3 py-1 text-center text-xs text-muted-foreground">
                <Info className="mt-0.5 size-3 shrink-0" /> {m.body}
              </p>
            </li>
          );
        }
        const mine = m.author_type === viewer || (viewer === "CLINICIAN" && m.author_type === "CLINICIAN");
        const isPatient = m.author_type === "PATIENT";
        const attachment = kind === "report_ready" ? attachments.find((a) => a.id === m.payload?.document_id) : undefined;
        return (
          <li key={m.id} data-testid="message" data-author={m.author_type} className={cn("flex", mine ? "justify-end" : "justify-start")}>
            <div
              className={cn(
                "max-w-[85%] space-y-1 rounded-2xl px-4 py-2.5 text-sm shadow-sm",
                isPatient && viewer === "PATIENT" ? "bg-primary text-primary-foreground" : "border bg-card",
                m.author_type === "CLINICIAN" && "border-emerald-300 dark:border-emerald-800",
              )}
            >
              <p className={cn("flex items-center gap-1 text-xs font-medium", isPatient && viewer === "PATIENT" ? "text-primary-foreground/80" : "text-muted-foreground")}>
                {m.author_type === "AI" && <Bot className="size-3.5" />}
                {m.author_type === "CLINICIAN" && <Stethoscope className="size-3.5" />}
                {kind === "report" && <FileText className="size-3.5" />}
                {m.author_type === "AI" ? "CareBridge" : m.author_type === "CLINICIAN" ? (m.author_name ?? "Clinician") : isPatient && viewer === "CLINICIAN" ? "Patient" : "You"}
                <span className="font-normal">· {formatDate(m.created_at, true)}</span>
              </p>
              {kind === "answer" ? (
                <p>
                  <span className="opacity-80">{questionText(messages, m.payload?.question_id)}</span> <strong>{m.body}</strong>
                </p>
              ) : kind === "questions" && viewer === "CLINICIAN" ? (
                <div>
                  <p>{m.body}</p>
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    {(m.payload?.questions ?? []).map((q) => (
                      <li key={q.id}>{q.question}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="whitespace-pre-line leading-relaxed">{m.body}</p>
              )}
              {attachment?.findings && (
                <div className="space-y-2 pt-2">
                  {attachment.explanation && <p className="text-muted-foreground">{attachment.explanation.overview}</p>}
                  <FindingsTable findings={attachment.findings} />
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
