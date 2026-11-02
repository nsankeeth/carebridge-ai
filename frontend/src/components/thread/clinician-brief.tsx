"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Quote } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { ClinicianThread } from "@/lib/types";

function Quotes({ items, tone }: { items: string[]; tone: "for" | "against" }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-0.5">
      {items.map((q) => (
        <li key={q} className={tone === "for" ? "text-emerald-800 dark:text-emerald-300" : "text-red-800 dark:text-red-300"}>
          {tone === "for" ? "+" : "−"} “{q}”
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      {children}
    </div>
  );
}

export function ClinicianBriefPanel({ thread }: { thread: ClinicianThread }) {
  const qc = useQueryClient();
  const b = thread.brief;
  const [correction, setCorrection] = useState("");
  const grade = useMutation({
    mutationFn: (assessment: "ACCURATE" | "CORRECTED" | "REJECTED") =>
      api.post(`/clinician/threads/${thread.id}/brief-assessment`, { assessment, correction: correction || null }),
    onSuccess: () => {
      toast.success("Thanks, your assessment was recorded");
      qc.invalidateQueries({ queryKey: ["clinician-thread", thread.id] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!b) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Meta is drafting the triage brief…
        </CardContent>
      </Card>
    );
  }
  const c = b.content;
  return (
    <Card data-testid="brief">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="size-4 text-primary" /> AI draft for clinician review
        </CardTitle>
        <CardDescription>
          Meta <span className="font-mono">{b.model_id}</span> · v{b.version} · {formatDate(b.created_at, true)} · quotes checked against the patient’s own words
          {b.validation_issues.length > 0 && ` · ${b.validation_issues.length} ungrounded item(s) removed`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="font-medium">{c.headline}</p>
        {c.red_flags.length > 0 && (
          <Section title="Red flags">
            <ul className="space-y-1">
              {c.red_flags.map((f) => (
                <li key={f.flag + f.patient_quote} className="flex items-start gap-1.5">
                  <Quote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <span>
                    <span className="font-medium">{f.flag.replaceAll("_", " ")}</span> — “{f.patient_quote}”
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}
        <Section title="Possible causes to consider">
          <ul className="space-y-2">
            {c.possible_causes.map((p) => (
              <li key={p.cause} className="rounded-md border p-2">
                <p className="flex items-center gap-2 font-medium">
                  {p.cause}
                  <Badge variant="outline" className="text-xs">{p.likelihood === "higher" ? "more likely" : "less likely"}</Badge>
                </p>
                <div className="mt-1 text-xs">
                  <Quotes items={p.supporting_quotes} tone="for" />
                  <Quotes items={p.against_quotes} tone="against" />
                </div>
              </li>
            ))}
          </ul>
        </Section>
        {c.timeline.length > 0 && (
          <Section title="Timeline">
            <ol className="list-decimal space-y-0.5 pl-5">{c.timeline.map((t) => <li key={t}>{t}</li>)}</ol>
          </Section>
        )}
        <Section title="Suggested questions">
          <ul className="list-disc space-y-0.5 pl-5">{c.suggested_questions.map((q) => <li key={q}>{q}</li>)}</ul>
        </Section>
        <Section title="Suggested next steps">
          <ul className="list-disc space-y-0.5 pl-5">{c.suggested_next_steps.map((q) => <li key={q}>{q}</li>)}</ul>
        </Section>
        <Section title="Draft treatment idea (clinician only, never shown to the patient)">
          <p className="rounded-md bg-muted p-2">{c.draft_treatment_idea}</p>
        </Section>
        <Section title="What CareBridge told the patient">
          <details className="rounded-md border p-2">
            <summary className="cursor-pointer text-muted-foreground">{c.what_ai_told_patient.length} message(s)</summary>
            <ul className="mt-2 space-y-2">
              {c.what_ai_told_patient.map((m, i) => (
                <li key={i} className="whitespace-pre-line border-l-2 pl-2 text-muted-foreground">{m}</li>
              ))}
            </ul>
          </details>
        </Section>
        <div className="space-y-2 border-t pt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Grade this draft {b.assessment && <Badge className="ml-1">{b.assessment.toLowerCase()}</Badge>}
          </p>
          <Textarea rows={2} placeholder="What’s inaccurate? (required to correct or reject)" value={correction} onChange={(e) => setCorrection(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            {(["ACCURATE", "CORRECTED", "REJECTED"] as const).map((a) => (
              <Button key={a} size="sm" variant={a === "ACCURATE" ? "default" : "outline"} disabled={grade.isPending} onClick={() => grade.mutate(a)}>
                {a === "ACCURATE" ? "Accurate" : a === "CORRECTED" ? "Needs correction" : "Reject"}
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
