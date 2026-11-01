"use client";

import { Phone, Siren, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export function EmergencyScreen({ steps, onDismiss }: { steps: string[]; onDismiss: () => void }) {
  return (
    <div
      role="alertdialog"
      aria-labelledby="emergency-title"
      data-testid="emergency-screen"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-6 overflow-y-auto bg-red-700 p-6 text-white"
    >
      <Siren className="size-14" />
      <div className="max-w-md space-y-2 text-center">
        <h1 id="emergency-title" className="text-3xl font-bold">
          Call 911 now
        </h1>
        <p className="text-lg text-red-50">This may be an emergency. Don’t wait for a message back.</p>
      </div>
      <a
        href="tel:911"
        data-testid="call-911"
        className="flex w-full max-w-md items-center justify-center gap-3 rounded-2xl bg-white px-6 py-5 text-2xl font-bold text-red-700 shadow-lg hover:bg-red-50"
      >
        <Phone className="size-7" /> Call 911
      </a>
      <ol className="w-full max-w-md list-decimal space-y-1 pl-6 text-red-50">
        {steps.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
      <p className="max-w-md text-center text-sm text-red-100">We are also letting your care team know.</p>
      <Button variant="ghost" className="text-white hover:bg-red-600 hover:text-white" onClick={onDismiss} data-testid="emergency-dismiss">
        <X className="size-4" /> Back to the conversation
      </Button>
    </div>
  );
}
