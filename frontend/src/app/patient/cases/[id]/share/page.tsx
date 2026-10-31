"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import type { SharingPreview } from "@/lib/types";

const schema = z.object({
  clinician_id: z.string().uuid("Choose who to share with"),
  confirmed: z.literal(true, { errorMap: () => ({ message: "Please confirm to give consent" }) }),
});
type Form = z.infer<typeof schema>;

export default function SharePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const preview = useQuery({ queryKey: ["sharing", id], queryFn: () => api.get<SharingPreview>(`/patient/cases/${id}/sharing`) });
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { clinician_id: "", confirmed: undefined } });
  const grant = useMutation({
    mutationFn: (v: Form) => api.post(`/patient/cases/${id}/consent`, v),
    onSuccess: () => {
      toast.success("Consent recorded");
      qc.invalidateQueries({ queryKey: ["patient-case", id] });
      router.push(`/patient/cases/${id}?tab=sharing`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not record consent"),
  });

  if (!preview.data) return <Skeleton className="h-96" />;
  const p = preview.data;
  const chosen = p.clinicians.find((c) => c.id === form.watch("clinician_id"));

  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-primary" /> Consent to share with a clinician
          </CardTitle>
          <CardDescription>Review exactly what will be shared, with whom, and why.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={form.handleSubmit((v) => grant.mutate(v))} noValidate>
            <section className="space-y-3">
              <h2 className="font-medium">1. Who will receive it</h2>
              <Controller
                control={form.control}
                name="clinician_id"
                render={({ field }) => (
                  <RadioGroup value={field.value} onValueChange={field.onChange} className="gap-2">
                    {p.clinicians.map((c) => (
                      <Label
                        key={c.id}
                        htmlFor={c.id}
                        className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent/50"
                      >
                        <RadioGroupItem value={c.id} id={c.id} data-testid={`clinician-${c.name}`} />
                        <span>
                          <span className="block font-medium">{c.name}</span>
                          <span className="block text-xs text-muted-foreground">
                            {c.specialty} · {c.clinic_name}
                          </span>
                        </span>
                      </Label>
                    ))}
                  </RadioGroup>
                )}
              />
              {form.formState.errors.clinician_id && <p className="text-sm text-destructive">{form.formState.errors.clinician_id.message}</p>}
            </section>

            <section className="space-y-2">
              <h2 className="font-medium">2. What will be shared</h2>
              <ul className="space-y-1.5 text-sm">
                {p.scope.map((s) => (
                  <li key={s.key} className="flex items-center gap-2">
                    <CheckCircle2 className="size-4 text-primary" /> {s.label}
                  </li>
                ))}
              </ul>
            </section>

            <section className="space-y-2">
              <h2 className="font-medium">3. Why</h2>
              <p className="text-sm text-muted-foreground">{p.purpose}</p>
            </section>

            <ul className="space-y-1 rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground">
              {p.notes.map((n) => <li key={n}>• {n}</li>)}
            </ul>

            <Controller
              control={form.control}
              name="confirmed"
              render={({ field }) => (
                <Label className="flex items-start gap-3 font-normal leading-snug">
                  <Checkbox checked={field.value === true} onCheckedChange={(v) => field.onChange(v === true ? true : undefined)} data-testid="consent-confirm" />
                  <span>
                    I consent to share the items above with {chosen?.name ?? "the selected clinician"} for the purpose described. I understand I
                    can withdraw this consent for future access at any time.
                  </span>
                </Label>
              )}
            />
            {form.formState.errors.confirmed && <p className="text-sm text-destructive">{form.formState.errors.confirmed.message}</p>}

            <div className="flex gap-3">
              <Button type="submit" disabled={grant.isPending} data-testid="grant-consent">
                {grant.isPending && <Loader2 className="size-4 animate-spin" />} Give consent
              </Button>
              <Button type="button" variant="ghost" onClick={() => router.push(`/patient/cases/${id}`)}>
                Not now
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
