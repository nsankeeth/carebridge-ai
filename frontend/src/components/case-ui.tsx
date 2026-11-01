"use client";

import { AlertTriangle, Bot, Check, CheckCircle2, Circle, Cpu, Loader2, Wrench, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate, HAPPY_PATH, STATUS_LABEL, STATUS_TONE, STEP_LABEL, type Tone } from "@/lib/format";
import type { CaseStatus, Execution, Finding, Summary } from "@/lib/types";
import { cn } from "@/lib/utils";

export const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground border-transparent",
  info: "bg-sky-100 text-sky-800 border-transparent dark:bg-sky-900/40 dark:text-sky-200",
  progress: "bg-cyan-100 text-cyan-900 border-transparent dark:bg-cyan-900/40 dark:text-cyan-200",
  success: "bg-emerald-100 text-emerald-800 border-transparent dark:bg-emerald-900/40 dark:text-emerald-200",
  warning: "bg-amber-100 text-amber-900 border-transparent dark:bg-amber-900/40 dark:text-amber-200",
  danger: "bg-red-100 text-red-800 border-transparent dark:bg-red-900/40 dark:text-red-200",
};

export function StatusBadge({ status }: { status: CaseStatus }) {
  return (
    <Badge data-testid="case-status" data-status={status} className={cn("font-medium", TONE_CLASS[STATUS_TONE[status]])}>
      {status === "PROCESSING" && <Loader2 className="size-3 animate-spin" />}
      {STATUS_LABEL[status]}
    </Badge>
  );
}

const TRACKER_STEPS: { label: string; reached: CaseStatus[] }[] = [
  { label: "Uploaded", reached: HAPPY_PATH.slice(0) },
  { label: "AI summary", reached: HAPPY_PATH.slice(2) },
  { label: "Consent", reached: HAPPY_PATH.slice(4) },
  { label: "Sent", reached: HAPPY_PATH.slice(5) },
  { label: "Acknowledged", reached: HAPPY_PATH.slice(6) },
  { label: "Reviewed", reached: HAPPY_PATH.slice(8) },
  { label: "Closed", reached: HAPPY_PATH.slice(9) },
];

export function WorkflowTracker({ status }: { status: CaseStatus }) {
  const offPath = !HAPPY_PATH.includes(status);
  const current = TRACKER_STEPS.findLastIndex((s) => s.reached.includes(status));
  return (
    <div className="space-y-3">
      <ol className="flex items-center gap-1 overflow-x-auto pb-1">
        {TRACKER_STEPS.map((s, i) => {
          const done = i <= current;
          return (
            <li key={s.label} className="flex min-w-fit items-center gap-1">
              <span
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                  done ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                  i === current && !offPath && "ring-2 ring-primary/30",
                )}
              >
                {done ? <Check className="size-3" /> : <Circle className="size-3" />} {s.label}
              </span>
              {i < TRACKER_STEPS.length - 1 && <span className={cn("h-px w-4", done ? "bg-primary" : "bg-border")} />}
            </li>
          );
        })}
      </ol>
      {offPath && (
        <p className="flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
          <AlertTriangle className="size-4" /> {STATUS_LABEL[status]}
        </p>
      )}
    </div>
  );
}

export function FlagCell({ f }: { f: Finding }) {
  const out = f.flag || f.outside_reference_range;
  if (!out) return <span className="text-muted-foreground">Within range</span>;
  return (
    <span className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-300">
      <AlertTriangle className="size-3.5" />
      {f.flag ? `Lab flag: ${f.flag}` : "Outside range"}
    </span>
  );
}

export function FindingsTable({ findings, showSource = false }: { findings: Finding[]; showSource?: boolean }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table data-testid="findings-table">
        <TableHeader>
          <TableRow>
            <TableHead>Test</TableHead>
            <TableHead>Result</TableHead>
            <TableHead>Reference range</TableHead>
            <TableHead>Status</TableHead>
            {showSource && <TableHead>Source</TableHead>}
            <TableHead>Check</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {findings.map((f) => (
            <TableRow key={f.id} className={cn((f.flag || f.outside_reference_range) && "bg-amber-50/60 dark:bg-amber-950/20")}>
              <TableCell className="font-medium">{f.test_name}</TableCell>
              <TableCell className="font-mono">
                {f.value} <span className="text-muted-foreground">{f.unit}</span>
              </TableCell>
              <TableCell className="font-mono text-muted-foreground">{f.reference_range ?? "—"}</TableCell>
              <TableCell>
                <FlagCell f={f} />
              </TableCell>
              {showSource && (
                <TableCell className="max-w-64 truncate font-mono text-xs text-muted-foreground" title={f.source_text ?? ""}>
                  p.{f.source_page} · {f.source_text}
                </TableCell>
              )}
              <TableCell>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      {f.status === "VERIFIED" ? (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-300">
                          <CheckCircle2 className="size-3.5" /> Matches report
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-red-700 dark:text-red-300">
                          <AlertTriangle className="size-3.5" /> Needs review
                        </span>
                      )}
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">
                      {f.status === "VERIFIED"
                        ? `Value, unit and range were found verbatim on page ${f.source_page} (${f.extraction_method}).`
                        : f.validation_notes.join(" ")}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function AiProvenance({ summary }: { summary: Summary }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" data-testid="ai-provenance">
      <Cpu className="size-3.5" />
      <span>
        Generated by Meta <span className="font-mono">{summary.model_id}</span>
      </span>
      <span>· {formatDate(summary.created_at, true)}</span>
      <span>· validated against the source report</span>
    </div>
  );
}

function stepIcon(ok: boolean | undefined, running: boolean) {
  if (running) return <Loader2 className="size-4 animate-spin text-primary" />;
  return ok ? <CheckCircle2 className="size-4 text-emerald-600" /> : <XCircle className="size-4 text-destructive" />;
}

/** Shows what the agent actually did: pipeline steps, Meta model calls, and tool invocations. */
export function AgentTrace({ execution, title }: { execution: Execution; title?: string }) {
  const running = execution.status === "RUNNING";
  const label = title ?? { PROCESSING: "Report processing agent", HANDOFF: "Handoff coordinator agent", FOLLOW_UP: "Follow-up coordinator agent" }[execution.kind];
  return (
    <Card data-testid={`agent-trace-${execution.kind.toLowerCase()}`}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="size-4 text-primary" /> {label}
          <Badge variant="outline" className="ml-auto">
            {running ? "Running" : execution.status === "SUCCEEDED" ? "Completed" : "Failed"}
          </Badge>
        </CardTitle>
        <CardDescription>{formatDate(execution.started_at, true)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <ol className="space-y-2">
          {execution.steps.map((s, i) => {
            if (s.type === "tool_call") {
              return (
                <li key={i} className="flex items-start gap-2 text-sm">
                  {stepIcon(s.ok, false)}
                  <div className="min-w-0">
                    <p>
                      <Wrench className="mr-1 inline size-3.5 text-muted-foreground" />
                      Model chose tool <code className="rounded bg-muted px-1 font-mono text-xs">{s.tool}</code>
                      {s.model && <span className="text-xs text-muted-foreground"> · {s.model}</span>}
                    </p>
                    {!s.ok && s.result && <p className="text-xs text-destructive">Blocked by backend: {String(s.result.error)}</p>}
                  </div>
                </li>
              );
            }
            if (s.type === "final" || s.type === "limit") {
              return (
                <li key={i} className="rounded-md bg-muted/60 p-2 text-sm">
                  <span className="font-medium">Agent summary: </span>
                  {s.message}
                </li>
              );
            }
            const isMeta = s.name?.startsWith("meta_");
            return (
              <li key={i} className="flex items-center gap-2 text-sm">
                {stepIcon(s.status === "succeeded", false)}
                <span>{STEP_LABEL[s.name ?? ""] ?? s.name}</span>
                {isMeta && (
                  <Badge variant="secondary" className="gap-1 text-[10px]">
                    <Cpu className="size-3" /> Meta model
                  </Badge>
                )}
                <span className="ml-auto text-xs text-muted-foreground">{s.duration_ms != null ? `${(s.duration_ms / 1000).toFixed(1)}s` : ""}</span>
              </li>
            );
          })}
          {running && (
            <li className="flex items-center gap-2 text-sm text-primary">
              {stepIcon(undefined, true)} {STEP_LABEL[execution.current_step ?? ""] ?? execution.current_step ?? "Starting"}…
            </li>
          )}
        </ol>
        {execution.error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">{execution.error}</p>}
        {execution.model_calls && execution.model_calls.length > 0 && (
          <div className="mt-3 border-t pt-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Model inference log</p>
            <div className="space-y-1 font-mono text-xs">
              {execution.model_calls.map((m) => (
                <div key={m.id} className="flex flex-wrap gap-x-3 text-muted-foreground" data-testid="model-call">
                  <span className={cn(m.status === "ok" ? "text-emerald-700 dark:text-emerald-300" : "text-destructive")}>{m.status}</span>
                  <span className="text-foreground">{m.task}</span>
                  <span>{`${m.provider}/${m.model_id}`}</span>
                  <span>{(m.latency_ms / 1000).toFixed(1)}s</span>
                  {m.total_tokens != null && <span>{m.total_tokens.toLocaleString()} tok</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
