"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { HeartPulse, Loader2, ShieldCheck, Stethoscope, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

const schema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });
type Form = z.infer<typeof schema>;

// Synthetic demo accounts created by `python -m app.seed` (see backend/app/seed.py).
const DEMO_PASSWORD = process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "CareBridge-Demo-2026";
const DEMO_ACCOUNTS = [
  { label: "Maya Thompson", sub: "Patient", email: "maya.thompson@patient.demo", icon: UserRound },
  { label: "Dr. Priya Raman", sub: "Clinician", email: "dr.raman@clinic.demo", icon: Stethoscope },
  { label: "Jordan Lee", sub: "Administrator", email: "admin@carebridge.demo", icon: ShieldCheck },
];
const HOME = { PATIENT: "/patient", CLINICIAN: "/clinician", ADMIN: "/admin" } as const;

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });

  async function onSubmit(values: Form) {
    setError(null);
    try {
      const { user } = await api.post<{ user: User }>("/auth/login", values);
      qc.clear();
      qc.setQueryData(["me"], user);
      router.replace(HOME[user.role]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to sign in");
    }
  }

  return (
    <main className="min-h-screen grid lg:grid-cols-2">
      <section className="hidden lg:flex flex-col justify-between bg-gradient-to-br from-cyan-900 via-teal-800 to-slate-900 p-12 text-white">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <HeartPulse className="size-6" /> CareBridge
        </div>
        <div className="space-y-6 max-w-md">
          <h1 className="text-4xl font-semibold leading-tight">From lab report to clinician review, without the gaps.</h1>
          <p className="text-cyan-100/90">
            CareBridge explains your results in plain language, then, with your consent, hands them to your clinician and keeps
            everyone updated until the loop is closed.
          </p>
          <ul className="space-y-2 text-sm text-cyan-100/80">
            <li>• Report understanding and summaries powered by Meta AI</li>
            <li>• Consent enforced before anything is shared</li>
            <li>• Every action recorded in an audit trail</li>
          </ul>
        </div>
      </section>

      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-md space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-2xl">Sign in</CardTitle>
              <CardDescription>Use your CareBridge account.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)} noValidate>
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input id="email" type="email" autoComplete="username" {...form.register("email")} />
                  {form.formState.errors.email && <p className="text-sm text-destructive">{form.formState.errors.email.message}</p>}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
                  {form.formState.errors.password && <p className="text-sm text-destructive">{form.formState.errors.password.message}</p>}
                </div>
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
                  {form.formState.isSubmitting && <Loader2 className="size-4 animate-spin" />} Sign in
                </Button>
              </form>
            </CardContent>
          </Card>

          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Demo accounts</p>
            <div className="grid gap-2">
              {DEMO_ACCOUNTS.map((a) => (
                <button
                  key={a.email}
                  type="button"
                  data-testid={`demo-${a.sub.toLowerCase()}`}
                  onClick={() => {
                    form.setValue("email", a.email);
                    form.setValue("password", DEMO_PASSWORD);
                    void form.handleSubmit(onSubmit)();
                  }}
                  className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3 text-left transition hover:border-primary/50 hover:bg-accent"
                >
                  <a.icon className="size-5 text-primary" />
                  <span className="flex-1">
                    <span className="block text-sm font-medium">{a.label}</span>
                    <span className="block text-xs text-muted-foreground">{a.sub}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
