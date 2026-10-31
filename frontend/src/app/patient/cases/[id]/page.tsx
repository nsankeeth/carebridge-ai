"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, HelpCircle, Info, Loader2, MessageSquareText, RefreshCw, Send, ShieldCheck, ShieldOff } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { AiProvenance, FindingsTable, StatusBadge, WorkflowTracker } from "@/components/case-ui";
import { ExecutionTrace } from "@/components/execution-trace";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { formatDate, NEXT_STEP_LABEL } from "@/lib/format";
import type { PatientCase } from "@/lib/types";

const SHAREABLE = ["SUMMARY_READY", "CONSENT_WITHDRAWN", "HANDOFF_CANCELLED"];
const SHARED = ["HANDOFF_SENT", "ACKNOWLEDGED", "UNDER_REVIEW"];

export default function PatientCasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") ?? "explanation");
  const q = useQuery({
    queryKey: ["patient-case", id],
    queryFn: () => api.get<PatientCase>(`/patient/cases/${id}`),
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!d) return false;
      return d.status === "PROCESSING" || d.executions.some((e) => e.status === "RUNNING") ? 1500 : 10000;
    },
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["patient-case", id] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

  const requestShare = useMutation({
    mutationFn: () => api.post(`/patient/cases/${id}/consent/request`),
    onSuccess: () => router.push(`/patient/cases/${id}/share`),
    onError,
  });
  const handoff = useMutation({ mutationFn: () => api.post(`/patient/cases/${id}/handoff`), onSuccess: refresh, onError });
  const withdraw = useMutation({
    mutationFn: () => api.post(`/patient/cases/${id}/consent/withdraw`),
    onSuccess: () => {
      toast.success("Consent withdrawn. Your clinician can no longer open this case.");
      refresh();
    },
    onError,
  });
  const retry = useMutation({ mutationFn: () => api.post(`/agent/cases/${id}/process`), onSuccess: refresh, onError });
  const close = useMutation({ mutationFn: () => api.post(`/patient/cases/${id}/close`), onSuccess: refresh, onError });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.isError || !q.data) return <Alert variant="destructive"><AlertDescription>Case not found.</AlertDescription></Alert>;
  const c = q.data;
  const explanation = c.summary?.status !== "FAILED_VALIDATION" ? c.summary?.patient_explanation : undefined;
  const byId = Object.fromEntries(c.findings.map((f) => [f.id, f]));
  const consent = c.consents.findLast((x) => x.status === "GRANTED");
  const processing = c.executions.find((e) => e.kind === "PROCESSING");
  const handoffRun = c.executions.find((e) => e.kind === "HANDOFF");

  return (
    <div className="space-y-6">
      <Link href="/patient" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> My cases
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{c.title}</h1>
          <p className="text-sm text-muted-foreground">
            {c.document?.filename} · uploaded {formatDate(c.document?.uploaded_at, true)}
          </p>
        </div>
        <StatusBadge status={c.status} />
      </div>
      <Card>
        <CardContent className="pt-6">
          <WorkflowTracker status={c.status} />
        </CardContent>
      </Card>

      {c.status === "PROCESSING" && processing && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="border-primary/40">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Loader2 className="size-5 animate-spin text-primary" /> Analyzing your report
              </CardTitle>
              <CardDescription>
                The AI agent is reading your report, extracting each result exactly as printed, and checking its work against the
                original before writing an explanation. This usually takes under a minute.
              </CardDescription>
            </CardHeader>
          </Card>
          <ExecutionTrace execution={processing} />
        </div>
      )}

      {(c.status === "PROCESSING_FAILED" || c.status === "NEEDS_CORRECTION") && (
        <Alert variant="destructive">
          <AlertTitle>{c.status === "NEEDS_CORRECTION" ? "The AI output did not pass our safety checks" : "We couldn't process this report"}</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>
              {c.status === "NEEDS_CORRECTION"
                ? "To protect you, a summary that fails validation is never shown or shared. You can run the analysis again."
                : (processing?.error ?? "Processing failed.")}
            </p>
            <Button size="sm" variant="outline" onClick={() => retry.mutate()} disabled={retry.isPending}>
              <RefreshCw className="size-4" /> Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {c.review?.completed_at && (
        <Card className="border-emerald-300 bg-emerald-50/50 dark:bg-emerald-950/20" data-testid="review-result">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MessageSquareText className="size-5 text-emerald-700" /> Your clinician reviewed this report
            </CardTitle>
            <CardDescription>{formatDate(c.review.completed_at, true)}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <p>
              <span className="font-medium">Next step: </span>
              {NEXT_STEP_LABEL[c.review.next_step ?? ""] ?? c.review.next_step}
            </p>
            {c.review.patient_message && <p className="rounded-md bg-card p-3 text-sm">“{c.review.patient_message}”</p>}
            {c.status === "REVIEW_COMPLETED" && (
              <Button size="sm" variant="outline" onClick={() => close.mutate()} disabled={close.isPending}>
                Mark this case as closed
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {c.summary && c.status !== "PROCESSING" && (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="explanation">Explanation</TabsTrigger>
            <TabsTrigger value="results">Results ({c.findings.length})</TabsTrigger>
            <TabsTrigger value="sharing">Sharing & status</TabsTrigger>
            <TabsTrigger value="agent">AI activity</TabsTrigger>
          </TabsList>

          <TabsContent value="explanation" className="space-y-4">
            {explanation ? (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>What your report says</CardTitle>
                    <AiProvenance summary={c.summary} />
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <p className="text-base leading-relaxed" data-testid="explanation-overview">{explanation.overview}</p>
                    {explanation.items_for_clinician_review.length > 0 && (
                      <Alert className="border-amber-300 bg-amber-50/70 dark:bg-amber-950/20">
                        <Info className="size-4" />
                        <AlertTitle>Worth discussing with a clinician</AlertTitle>
                        <AlertDescription>
                          <ul className="mt-1 list-disc space-y-1 pl-5">
                            {explanation.items_for_clinician_review.map((r) => (
                              <li key={r.finding_id}>
                                <span className="font-medium">{byId[r.finding_id]?.test_name}</span>: {r.reason}
                              </li>
                            ))}
                          </ul>
                        </AlertDescription>
                      </Alert>
                    )}
                  </CardContent>
                </Card>
                <div className="grid gap-3 md:grid-cols-2">
                  {explanation.findings.map((e) => {
                    const f = byId[e.finding_id];
                    if (!f) return null;
                    return (
                      <Card key={e.finding_id}>
                        <CardHeader className="pb-2">
                          <CardTitle className="flex items-baseline justify-between text-base">
                            {f.test_name}
                            <span className="font-mono text-sm font-normal">
                              {f.value} {f.unit}
                            </span>
                          </CardTitle>
                          <CardDescription>Lab reference range: {f.reference_range ?? "not printed"}</CardDescription>
                        </CardHeader>
                        <CardContent className="text-sm leading-relaxed">{e.plain_language}</CardContent>
                      </Card>
                    );
                  })}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-base">
                        <HelpCircle className="size-4" /> Questions you could ask
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="list-disc space-y-1 pl-5 text-sm">
                        {explanation.questions_to_ask.map((x) => <li key={x}>{x}</li>)}
                      </ul>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Limitations</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                        {explanation.limitations.map((x) => <li key={x}>{x}</li>)}
                      </ul>
                    </CardContent>
                  </Card>
                </div>
              </>
            ) : (
              <p className="text-muted-foreground">No validated explanation is available.</p>
            )}
          </TabsContent>

          <TabsContent value="results" className="space-y-3">
            <FindingsTable findings={c.findings} />
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/patient/cases/${id}/document`} target="_blank" rel="noreferrer">
                <ExternalLink className="size-4" /> View original report
              </a>
            </Button>
          </TabsContent>

          <TabsContent value="sharing" className="space-y-4">
            <SharingPanel
              c={c}
              consentName={consent?.clinician_name}
              onRequest={() => requestShare.mutate()}
              requesting={requestShare.isPending}
              onHandoff={() => handoff.mutate()}
              handingOff={handoff.isPending || handoffRun?.status === "RUNNING"}
              onWithdraw={() => withdraw.mutate()}
            />
            {handoffRun && <ExecutionTrace execution={handoffRun} />}
          </TabsContent>

          <TabsContent value="agent" className="grid gap-4 md:grid-cols-2">
            {c.executions.map((e) => <ExecutionTrace key={e.id} execution={e} />)}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function SharingPanel(props: {
  c: PatientCase;
  consentName?: string;
  onRequest: () => void;
  requesting: boolean;
  onHandoff: () => void;
  handingOff: boolean;
  onWithdraw: () => void;
}) {
  const { c } = props;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Clinician handoff</CardTitle>
        <CardDescription>Your report is only shared with a clinician you choose, after you give explicit consent.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {SHAREABLE.includes(c.status) && (
          <Button onClick={props.onRequest} disabled={props.requesting} data-testid="share-with-clinician">
            <ShieldCheck className="size-4" /> Share with a clinician
          </Button>
        )}
        {c.status === "AWAITING_CONSENT" && (
          <Button asChild data-testid="review-consent">
            <Link href={`/patient/cases/${c.id}/share`}>
              <ShieldCheck className="size-4" /> Review and give consent
            </Link>
          </Button>
        )}
        {c.status === "CONSENT_GRANTED" && (
          <div className="space-y-3">
            <p className="text-sm">
              You gave consent to share with <span className="font-medium">{props.consentName}</span>. Send it now and our care-coordination
              agent will deliver the handoff and keep you updated.
            </p>
            <Button onClick={props.onHandoff} disabled={props.handingOff} data-testid="send-handoff">
              {props.handingOff ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Send to {props.consentName}
            </Button>
          </div>
        )}
        {c.handoff && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4" data-testid="handoff-status">
            <div>
              <dt className="text-muted-foreground">Clinician</dt>
              <dd className="font-medium">{c.handoff.clinician_name}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Handoff</dt>
              <dd className="font-medium capitalize">{c.handoff.status.toLowerCase()}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Sent</dt>
              <dd>{formatDate(c.handoff.sent_at, true)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Acknowledged</dt>
              <dd>{c.handoff.acknowledged_at ? formatDate(c.handoff.acknowledged_at, true) : "Waiting"}</dd>
            </div>
          </dl>
        )}
        {(c.status === "CONSENT_GRANTED" || SHARED.includes(c.status)) && (
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="sm" className="text-destructive">
                <ShieldOff className="size-4" /> Withdraw consent
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Withdraw consent?</DialogTitle>
                <DialogDescription>
                  {props.consentName} will no longer be able to open this case. Withdrawing stops future access only; it can&apos;t undo
                  access that has already happened.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="destructive" onClick={props.onWithdraw}>
                  Withdraw consent
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
        <div className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
          <p className="font-medium">Consent history</p>
          {c.consents.length === 0 && <p>No consent given yet.</p>}
          {c.consents.map((x) => (
            <p key={x.id}>
              {x.status === "GRANTED" ? "Granted" : "Withdrawn"} for {x.clinician_name} on {formatDate(x.granted_at, true)}
              {x.withdrawn_at && ` · withdrawn ${formatDate(x.withdrawn_at, true)}`}
            </p>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
