"use client";

import { Loader2, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

// Muse Voice Transcribe accepts WAV only: mono, 16-bit PCM at 16 or 24 kHz.
const SAMPLE_RATE = 16000;
const MAX_SECONDS = 120;

function encodeWav(samples: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const text = (at: number, s: string) => [...s].forEach((c, i) => v.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  text(36, "data");
  v.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([buf], { type: "audio/wav" });
}

async function toWav(recording: Blob): Promise<Blob> {
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(await recording.arrayBuffer());
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * SAMPLE_RATE), SAMPLE_RATE);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), SAMPLE_RATE);
  } finally {
    void ctx.close();
  }
}

/** Tap to speak, tap again to stop. The transcript is handed back for the patient to check before sending. */
export function VoiceButton({ onTranscript, disabled, size = "sm" }: { onTranscript: (text: string) => void; disabled?: boolean; size?: "sm" | "icon" }) {
  const [state, setState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current);
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  async function start() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      toast.error("Microphone access is needed to speak your message. You can type it instead.");
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      if (timer.current) clearInterval(timer.current);
      setState("transcribing");
      try {
        const fd = new FormData();
        fd.append("audio", await toWav(new Blob(chunks, { type: rec.mimeType })), "voice.wav");
        const { transcript } = await api.post<{ transcript: string }>("/patient/transcribe", fd);
        onTranscript(transcript);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "We couldn't transcribe that recording.");
      } finally {
        setState("idle");
      }
    };
    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    timer.current = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS && rec.state === "recording") rec.stop();
        return s + 1;
      });
    }, 1000);
  }

  const label = state === "recording" ? `Stop recording (${seconds}s)` : state === "transcribing" ? "Transcribing…" : "Speak your message";
  return (
    <Button
      type="button"
      variant={state === "recording" ? "destructive" : "ghost"}
      size={size}
      aria-label={label}
      title={label}
      data-testid="voice-button"
      disabled={disabled || state === "transcribing"}
      onClick={() => (state === "recording" ? recorder.current?.stop() : start())}
    >
      {state === "transcribing" ? <Loader2 className="size-4 animate-spin" /> : state === "recording" ? <Square className="size-4" /> : <Mic className="size-4" />}
      {size === "sm" && (state === "recording" ? ` Stop (${seconds}s)` : state === "transcribing" ? " Transcribing…" : " Speak")}
    </Button>
  );
}
