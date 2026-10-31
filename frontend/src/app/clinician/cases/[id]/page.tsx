"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCheck, ClipboardCheck, Cpu, FileText, Loader2, Stethoscope } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { AiProvenance, FindingsTable, StatusBadge, WorkflowTracker } from "@/components/case-ui";
import { ExecutionTrace } from "@/components/execution-trace";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { formatDate, NEXT_STEP_LABEL } from "@/lib/format";
import type { ClinicianCase } from "@/lib/types";

export default function ClinicianCasePage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["clinician-case", id], queryFn: () => api.get<ClinicianCase>(`/clinician/cases/${id}`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["clinician-case", id] });
    qc.invalidateQueries({ queryKey: ["clinician-cases"] });
    qc.invalidateQueries({ queryKey: ["clinician-tasks"] });
  };
  const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");
  const ack = useMutation({ mutationFn: () => api.post(`/clinician/cases/${id}/acknowledge`), onSuccess: refresh, onError });
  const start = useMutation({ mutationFn: () => api.post(`/clinician/cases/${id}/review/start`), onSuccess: refresh, onError });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError || !q.data)
    return (
      <Alert variant="destructive">
        <AlertDescription>{q.error instanceof ApiError ? q.error.message : "Case not available."}</AlertDescription>
      </Alert>
    );
  const c = q.data;
  const s = c.summary?.clinician_summary;
  const byId = Object.fromEntries(c.findings.map((f) => [f.id, f]));

  return (
    <div className="space-y-6">
      <Link href="/clinician" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Assigned cases
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{c.patient.name}</h1>
          <p className="text-sm text-muted-foreground">
            {c.title} · DOB {formatDate(c.patient.date_of_birth)} · {c.patient.synthetic_health_ref} · shared {formatDate(c.handoff?.sent_at, true)}
          </p>
        </div>
        <StatusBadge status={c.status} />
      </div>
      <Card>
        <CardContent className="pt-6">
          <WorkflowTracker status={c.status} />
        </CardContent>
      </Card>

      {c.status === "HANDOFF_SENT" && (
        <Card className="border-primary/50 bg-accent/30">
          <CardContent className="flex flex-wrap items-center gap-4 pt-6">
            <p className="flex-1 text-sm">
              {c.patient.name} shared this report with you on {formatDate(c.handoff?.sent_at, true)}. Acknowledge receipt so the patient knows it
              reached you.
            </p>
            <Button onClick={() => ack.mutate()} disabled={ack.isPending} data-testid="acknowledge">
              <CheckCheck className="size-4" /> Acknowledge receipt
            </Button>
          </CardContent>
        </Card>
      )}
      {c.status === "ACKNOWLEDGED" && (
        <Card className="border-primary/50 bg-accent/30">
          <CardContent className="flex flex-wrap items-center gap-4 pt-6">
            <p className="flex-1 text-sm">You acknowledged this case. Start your review when ready.</p>
            <Button onClick={() => start.mutate()} disabled={start.isPending} data-testid="start-review">
              <Stethoscope className="size-4" /> Start review
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-2 overflow-hidden">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="size-4" /> Original report
            </CardTitle>
            <CardDescription>{c.document?.filename}</CardDescription>
          </CardHeader>
          <iframe title="Original report" src={`/api/clinician/cases/${id}/document`} className="h-[640px] w-full border-t bg-muted" />
        </Card>

        <div className="space-y-4 lg:col-span-3">
          <Tabs defaultValue="summary">
            <TabsList>
              <TabsTrigger value="summary">AI handoff summary</TabsTrigger>
              <TabsTrigger value="findings">Findings ({c.findings.length})</TabsTrigger>
              <TabsTrigger value="patient">Patient view</TabsTrigger>
              <TabsTrigger value="agent">Agent activity</TabsTrigger>
            </TabsList>
            <TabsContent value="summary">
              {c.summary && s ? (
                <Card data-testid="clinician-summary">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <Cpu className="size-4 text-primary" /> {s.headline}
                    </CardTitle>
                    <AiProvenance summary={c.summary} />
                    {c.summary.status !== "ACTIVE" && (
                      <Badge variant="outline" className="w-fit">
                        Marked {c.summary.status.toLowerCase()} by clinician
                      </Badge>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-4 text-sm">
                    <div>
                      <p className="mb-2 font-medium">Flagged or outside the reported interval</p>
                      <ul className="space-y-2">
                        {s.key_findings.map((k) => (
                          <li key={k.finding_id} className="rounded-md border p-2">
                            <span className="font-medium">{k.test_name}</span>{" "}
                            <span className="font-mono">
                              {k.value} {k.unit}
                            </span>{" "}
                            <span className="text-muted-foreground">(ref {k.reference_range ?? "—"}{k.reported_flag ? `, flag ${k.reported_flag}` : ""})</span>
                            <p className="text-muted-foreground">{k.note}</p>
                          </li>
                        ))}
                        {s.key_findings.length === 0 && <li className="text-muted-foreground">None.</li>}
                      </ul>
                      <p className="mt-2 text-muted-foreground">{s.other_findings_count} other result(s) within the reported range.</p>
                    </div>
                    {[["Items requiring review", s.items_requiring_review], ["Data quality", s.data_quality], ["Limitations", s.limitations]].map(
                      ([label, items]) =>
                        (items as string[]).length > 0 && (
                          <div key={label as string}>
                            <p className="font-medium">{label as string}</p>
                            <ul className="list-disc pl-5 text-muted-foreground">
                              {(items as string[]).map((x) => <li key={x}>{x}</li>)}
                            </ul>
                          </div>
                        ),
                    )}
                    {c.findings.some((f) => f.status === "NEEDS_REVIEW") && (
                      <p className="flex items-center gap-2 text-amber-700">
                        <AlertTriangle className="size-4" /> Some extracted values could not be verified against the source. Check the original.
                      </p>
                    )}
                    <p className="border-t pt-3 text-xs text-muted-foreground">
                      Draft generated by an AI model for clinician review. It is not a clinical assessment and may be incomplete.
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <p className="text-muted-foreground">No summary available.</p>
              )}
            </TabsContent>
            <TabsContent value="findings">
              <FindingsTable findings={c.findings} showSource />
            </TabsContent>
            <TabsContent value="patient">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">What the patient was shown</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <p>{c.summary?.patient_explanation.overview}</p>
                  <ul className="list-disc pl-5 text-muted-foreground">
                    {c.summary?.patient_explanation.findings.map((e) => (
                      <li key={e.finding_id}>
                        <span className="text-foreground">{byId[e.finding_id]?.test_name}:</span> {e.plain_language}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="agent" className="space-y-4">
              {c.executions.map((e) => <ExecutionTrace key={e.id} execution={e} />)}
            </TabsContent>
          </Tabs>

          {(c.status === "UNDER_REVIEW" || c.review?.completed_at) && <ReviewPanel c={c} onDone={refresh} onError={onError} />}
        </div>
      </div>
    </div>
  );
}

function ReviewPanel({ c, onDone, onError }: { c: ClinicianCase; onDone: () => void; onError: (e: unknown) => void }) {
  const r = c.review;
  const [assessment, setAssessment] = useState<string>(r?.summary_assessment ?? "");
  const [correction, setCorrection] = useState(r?.summary_correction ?? "");
  const [nextStep, setNextStep] = useState<string>(r?.next_step ?? "");
  const [notes, setNotes] = useState(r?.clinical_notes ?? "");
  const [message, setMessage] = useState(r?.patient_message ?? "");
  const assess = useMutation({
    mutationFn: () => api.post(`/clinician/cases/${c.id}/summary-assessment`, { assessment, correction: correction || null }),
    onSuccess: () => {
      toast.success("Summary assessment saved");
      onDone();
    },
    onError,
  });
  const complete = useMutation({
    mutationFn: () =>
      api.post(`/clinician/cases/${c.id}/review/complete`, { next_step: nextStep, clinical_notes: notes || null, patient_message: message || null }),
    onSuccess: () => {
      toast.success("Review completed. The patient has been notified.");
      onDone();
    },
    onError,
  });
  const done = !!r?.completed_at;

  return (
    <Card data-testid="review-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardCheck className="size-5 text-primary" /> Clinical review
        </CardTitle>
        <CardDescription>
          {done ? `Completed ${formatDate(r?.completed_at, true)}` : "Assess the AI draft, record your decision, and choose an administrative next step."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <Label>1. Is the AI summary accurate?</Label>
          <div className="flex flex-wrap gap-2">
            {(["ACCURATE", "CORRECTED", "REJECTED"] as const).map((a) => (
              <Button
                key={a}
                type="button"
                size="sm"
                disabled={done}
                variant={assessment === a ? "default" : "outline"}
                onClick={() => setAssessment(a)}
                data-testid={`assess-${a.toLowerCase()}`}
              >
                {{ ACCURATE: "Accurate", CORRECTED: "Needs correction", REJECTED: "Reject" }[a]}
              </Button>
            ))}
          </div>
          {assessment && assessment !== "ACCURATE" && (
            <Textarea placeholder="What is inaccurate?" value={correction} onChange={(e) => setCorrection(e.target.value)} disabled={done} />
          )}
          {!done && (
            <Button size="sm" variant="secondary" disabled={!assessment || assess.isPending} onClick={() => assess.mutate()} data-testid="save-assessment">
              {assess.isPending && <Loader2 className="size-4 animate-spin" />} Save assessment
            </Button>
          )}
          {r?.summary_assessment && <p className="text-xs text-muted-foreground">Saved: {r.summary_assessment.toLowerCase()}</p>}
        </div>

        <div className="space-y-2">
          <Label htmlFor="notes">2. Clinical notes (not shown to the patient)</Label>
          <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} disabled={done} data-testid="clinical-notes" />
        </div>
        <div className="space-y-2">
          <Label>3. Next step</Label>
          <Select value={nextStep} onValueChange={setNextStep} disabled={done}>
            <SelectTrigger data-testid="next-step" className="w-full">
              <SelectValue placeholder="Choose an administrative next step" />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(NEXT_STEP_LABEL).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="message">4. Message to the patient</Label>
          <Textarea id="message" value={message} onChange={(e) => setMessage(e.target.value)} disabled={done} data-testid="patient-message" />
        </div>
        {!done && (
          <Button disabled={!nextStep || !r?.summary_assessment || complete.isPending} onClick={() => complete.mutate()} data-testid="complete-review">
            {complete.isPending && <Loader2 className="size-4 animate-spin" />} Complete review
          </Button>
        )}
        {!r?.summary_assessment && !done && <p className="text-xs text-muted-foreground">Save your assessment of the AI summary first.</p>}
      </CardContent>
    </Card>
  );
}
