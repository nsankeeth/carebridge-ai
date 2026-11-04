"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Lock, Paperclip, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { VoiceButton } from "@/components/thread/voice-button";
import { ageLabel } from "@/lib/format";
import type { Dependent, PatientThread } from "@/lib/types";

export const CONSENT_LINE =
  "CareBridge will share this conversation and anything you attach with your care team (your family doctor and on-call clinicians).";

async function uploadPdf(threadId: string, file: File) {
  const fd = new FormData();
  fd.append("file", file);
  await api.post(`/patient/threads/${threadId}/attachments`, fd);
}

export function NewThreadComposer() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [subject, setSubject] = useState<string>("me");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const deps = useQuery({ queryKey: ["dependents"], queryFn: () => api.get<Dependent[]>("/patient/dependents") });
  const create = useMutation({
    mutationFn: async () => {
      const { thread } = await api.post<{ thread: PatientThread }>("/patient/threads", {
        subject_dependent_id: subject === "me" ? null : subject,
        body: text.trim(),
        consent_confirmed: true,
      });
      if (file) await uploadPdf(thread.id, file).catch(() => toast.error("Your message was sent, but the report couldn't be attached."));
      return thread;
    },
    onSuccess: (thread) => router.push(`/patient/threads/${thread.id}${thread.emergency ? "?emergency=1" : ""}`),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <form
      className="space-y-3 rounded-2xl border bg-card p-4 shadow-sm sm:p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) create.mutate();
      }}
    >
      <div className="space-y-1.5">
        <Label>Who is this for?</Label>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Who is this for?">
          {[{ id: "me", label: "Me" }, ...(deps.data ?? []).map((d) => ({ id: d.id, label: `${d.name} (${ageLabel(d.age_years)})` }))].map((o) => (
            <Button
              key={o.id}
              type="button"
              role="radio"
              aria-checked={subject === o.id}
              data-testid={`subject-${o.id === "me" ? "me" : o.label.split(" ")[0].toLowerCase()}`}
              variant={subject === o.id ? "default" : "outline"}
              size="sm"
              onClick={() => setSubject(o.id)}
            >
              {o.label}
            </Button>
          ))}
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="composer">What’s going on today?</Label>
        <Textarea
          id="composer"
          data-testid="composer-input"
          rows={4}
          maxLength={4000}
          placeholder="Describe what's happening, when it started, and anything you've noticed."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <input ref={fileInput} type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <Button type="button" variant="ghost" size="sm" onClick={() => fileInput.current?.click()}>
            <Paperclip className="size-4" /> {file ? file.name : "Attach a lab report (PDF)"}
          </Button>
          <VoiceButton onTranscript={(said) => setText((t) => (t.trim() ? `${t.trim()} ${said}` : said))} disabled={create.isPending} />
        </div>
        <Button type="submit" data-testid="composer-send" disabled={!text.trim() || create.isPending}>
          {create.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Send
        </Button>
      </div>
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="consent-line">
        <Lock className="mt-0.5 size-3.5 shrink-0" /> {CONSENT_LINE} If this is an emergency, call 911.
      </p>
    </form>
  );
}

export function ReplyComposer({ threadId, disabled }: { threadId: string; disabled?: boolean }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const send = useMutation({
    mutationFn: () => api.post<PatientThread>(`/patient/threads/${threadId}/messages`, { body: text.trim() }),
    onSuccess: (data) => {
      setText("");
      qc.setQueryData(["thread", threadId], data);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const attach = useMutation({
    mutationFn: (f: File) => uploadPdf(threadId, f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["thread", threadId] }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <form
      className="flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) send.mutate();
      }}
    >
      <input
        ref={fileInput}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) attach.mutate(f);
          e.target.value = "";
        }}
      />
      <Button type="button" variant="ghost" size="icon" aria-label="Attach a lab report" disabled={disabled || attach.isPending} onClick={() => fileInput.current?.click()}>
        {attach.isPending ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}
      </Button>
      <Textarea
        data-testid="reply-input"
        rows={1}
        maxLength={4000}
        disabled={disabled}
        className="min-h-10 flex-1 resize-none border-0 shadow-none focus-visible:ring-0"
        placeholder={disabled ? "This conversation is closed" : "Add an update…"}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <VoiceButton size="icon" onTranscript={(said) => setText((t) => (t.trim() ? `${t.trim()} ${said}` : said))} disabled={disabled || send.isPending} />
      <Button type="submit" size="icon" aria-label="Send" data-testid="reply-send" disabled={disabled || !text.trim() || send.isPending}>
        {send.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
      </Button>
    </form>
  );
}
