"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Loader2, Phone, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { URGENCY_LABEL } from "@/lib/format";
import type { ClinicianThread, Urgency } from "@/lib/types";

const OUTCOMES: Record<string, string> = {
  ADVICE_GIVEN: "Advice given",
  SEEN_IN_PERSON: "Seen in person",
  SENT_TO_EMERGENCY: "Sent to emergency",
  SCHEDULE_APPOINTMENT: "Appointment scheduled",
  REFER_TO_SPECIALIST: "Referred to specialist",
  NO_FURTHER_ACTION: "No further action",
};

function useThreadAction<T>(threadId: string, path: string, success?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: T) => api.post(`/clinician/threads/${threadId}/${path}`, body),
    onSuccess: () => {
      if (success) toast.success(success);
      qc.invalidateQueries({ queryKey: ["clinician-thread", threadId] });
      qc.invalidateQueries({ queryKey: ["clinician-queue"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

export function ClinicianReply({ thread }: { thread: ClinicianThread }) {
  const [text, setText] = useState("");
  const send = useThreadAction<{ body: string }>(thread.id, "messages");
  const closed = thread.status === "CLOSED";
  return (
    <form
      className="flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) send.mutate({ body: text.trim() }, { onSuccess: () => setText("") });
      }}
    >
      <Textarea
        data-testid="reply-input"
        rows={2}
        disabled={closed || !thread.consent_active}
        className="flex-1 resize-none border-0 shadow-none focus-visible:ring-0"
        placeholder="Reply to the patient…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <Button type="submit" data-testid="reply-send" disabled={!text.trim() || send.isPending}>
        {send.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Send
      </Button>
    </form>
  );
}

export function ClinicianActions({ thread }: { thread: ClinicianThread }) {
  const ack = useThreadAction<undefined>(thread.id, "acknowledge", "Acknowledged. The patient can see you’ve seen it.");
  const urgency = useThreadAction<{ level: Urgency; reason: string }>(thread.id, "urgency", "Urgency updated");
  const outcome = useThreadAction<{ outcome: string; note: string | null }>(thread.id, "outcome", "Outcome recorded");
  const close = useThreadAction<undefined>(thread.id, "close", "Conversation closed");
  const [level, setLevel] = useState<Urgency>(thread.urgency ?? "SOON");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState("ADVICE_GIVEN");
  const [note, setNote] = useState("");
  const pending = thread.my_handoff.status === "SENT";
  const closed = thread.status === "CLOSED";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="flex flex-wrap gap-2">
          {pending && (
            <Button data-testid="ack-button" onClick={() => ack.mutate(undefined)} disabled={ack.isPending}>
              <CheckCheck className="size-4" /> Acknowledge
            </Button>
          )}
          {thread.patient_phone ? (
            <Button asChild variant="outline" data-testid="call-patient">
              <a href={`tel:${thread.patient_phone}`}>
                <Phone className="size-4" /> Call {thread.patient_phone}
              </a>
            </Button>
          ) : (
            <Button variant="outline" disabled>
              <Phone className="size-4" /> No phone on file
            </Button>
          )}
        </div>

        <div className="space-y-2 border-t pt-3">
          <p className="font-medium">Change urgency</p>
          <div className="flex flex-wrap gap-2">
            <Select value={level} onValueChange={(v) => setLevel(v as Urgency)}>
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["EMERGENCY", "URGENT", "SOON", "ROUTINE"] as const).map((l) => (
                  <SelectItem key={l} value={l}>{URGENCY_LABEL[l]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input className="min-w-40 flex-1" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
            <Button variant="outline" disabled={!reason.trim() || closed || urgency.isPending} onClick={() => urgency.mutate({ level, reason: reason.trim() }, { onSuccess: () => setReason("") })}>
              Update
            </Button>
          </div>
        </div>

        <div className="space-y-2 border-t pt-3">
          <p className="font-medium">Outcome {thread.outcome && <span className="font-normal text-muted-foreground">· recorded: {OUTCOMES[thread.outcome] ?? thread.outcome}</span>}</p>
          <Select value={result} onValueChange={setResult}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(OUTCOMES).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Textarea rows={2} placeholder="Note (optional, clinician only)" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={outcome.isPending} onClick={() => outcome.mutate({ outcome: result, note: note || null })}>
              Record outcome
            </Button>
            <Button variant="ghost" disabled={closed || pending || close.isPending} onClick={() => close.mutate(undefined)}>
              Close conversation
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
