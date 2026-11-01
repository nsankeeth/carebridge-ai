"use client";

import { AlertTriangle, CheckCircle2, Clock, Phone, Siren, Stethoscope } from "lucide-react";
import { TONE_CLASS } from "@/components/case-ui";
import { Badge } from "@/components/ui/badge";
import { URGENCY_LABEL, URGENCY_TONE, relative } from "@/lib/format";
import type { PatientThread, Urgency } from "@/lib/types";
import { cn } from "@/lib/utils";

export function UrgencyBadge({ level }: { level: Urgency | null }) {
  if (!level) return <Badge className={cn("font-medium", TONE_CLASS.neutral)}>Checking…</Badge>;
  return (
    <Badge data-testid="urgency-badge" data-level={level} className={cn("font-semibold", TONE_CLASS[URGENCY_TONE[level]])}>
      {level === "EMERGENCY" && <Siren className="size-3" />}
      {URGENCY_LABEL[level]}
    </Badge>
  );
}

const CARD_TONE: Record<Urgency, string> = {
  EMERGENCY: "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40",
  URGENT: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30",
  SOON: "border-sky-200 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/30",
  ROUTINE: "border-border bg-card",
};

export function UrgencyCard({ thread }: { thread: PatientThread }) {
  const level = thread.urgency;
  return (
    <section
      data-testid="urgency-card"
      data-level={level ?? "PENDING"}
      className={cn("space-y-3 rounded-xl border p-4 shadow-sm", level ? CARD_TONE[level] : "bg-card")}
    >
      <div className="flex flex-wrap items-center gap-2">
        {level === "EMERGENCY" ? <Siren className="size-5 text-red-600" /> : <AlertTriangle className="size-5 text-amber-600" />}
        <h2 className="font-semibold">How urgent this is</h2>
        <UrgencyBadge level={level} />
      </div>
      {thread.guidance ? (
        <p className="text-sm leading-relaxed">{thread.guidance}</p>
      ) : (
        <p className="text-sm text-muted-foreground">We’re checking your message now. This takes a few seconds.</p>
      )}
      {thread.emergency && (
        <a
          href="tel:911"
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-3 text-base font-semibold text-white hover:bg-red-700"
        >
          <Phone className="size-5" /> Call 911
        </a>
      )}
      {thread.fallback_advised && (
        <p className="rounded-md bg-red-100 p-2 text-sm font-medium text-red-900 dark:bg-red-950 dark:text-red-100">
          We haven’t reached a clinician yet. Go to urgent care or an emergency department now.
        </p>
      )}
      {thread.worsening_signs.length > 0 && !thread.emergency && (
        <div className="text-sm">
          <p className="font-medium">Watch for</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
            {thread.worsening_signs.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="space-y-1 border-t pt-3 text-sm" data-testid="care-team">
        <p className="flex items-center gap-1.5 font-medium">
          <Stethoscope className="size-4" /> Your care team
        </p>
        {!thread.consent_active ? (
          <p className="text-muted-foreground">Your care team no longer has access to this conversation.</p>
        ) : thread.care_team.length ? (
          thread.care_team.map((m) => (
            <p key={m.name} className="flex items-center gap-1.5 text-muted-foreground">
              {m.acknowledged_at ? <CheckCircle2 className="size-3.5 text-emerald-600" /> : <Clock className="size-3.5" />}
              <span className="text-foreground">{m.name}</span>
              {m.acknowledged_at ? `· seen ${relative(m.acknowledged_at)}` : `· notified ${relative(m.notified_at)}, not yet seen`}
            </p>
          ))
        ) : (
          <p className="text-muted-foreground">Contacting your care team…</p>
        )}
      </div>
    </section>
  );
}
