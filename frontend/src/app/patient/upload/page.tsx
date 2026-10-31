"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2, Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import type { CaseListItem } from "@/lib/types";

const MAX = 10 * 1024 * 1024;
const schema = z.object({
  title: z.string().trim().min(1, "Give this report a name").max(200),
  file: z
    .custom<FileList>()
    .refine((f) => f?.length === 1, "Choose a PDF report")
    .refine((f) => !f?.[0] || f[0].type === "application/pdf" || f[0].name.toLowerCase().endsWith(".pdf"), "Only PDF files are supported")
    .refine((f) => !f?.[0] || f[0].size <= MAX, "Reports must be 10 MB or smaller"),
});
type Form = z.infer<typeof schema>;

export default function UploadPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { title: "" } });
  const upload = useMutation({
    mutationFn: (v: Form) => {
      const fd = new FormData();
      fd.set("title", v.title);
      fd.set("file", v.file[0]);
      return api.post<{ case: CaseListItem }>("/patient/cases/upload", fd);
    },
    onSuccess: ({ case: c }) => {
      qc.invalidateQueries({ queryKey: ["patient-cases"] });
      router.push(`/patient/cases/${c.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Upload failed"),
  });

  return (
    <div className="mx-auto max-w-xl">
      <Card>
        <CardHeader>
          <CardTitle>Upload a lab report</CardTitle>
          <CardDescription>
            We read the PDF, pull out each result exactly as printed, and explain it in plain language. Nothing is shared with
            anyone until you give consent.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={form.handleSubmit((v) => upload.mutate(v))} noValidate>
            <div className="space-y-2">
              <Label htmlFor="title">Report name</Label>
              <Input id="title" placeholder="e.g. October blood work" {...form.register("title")} />
              {form.formState.errors.title && <p className="text-sm text-destructive">{form.formState.errors.title.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="file">PDF report</Label>
              <label
                htmlFor="file"
                className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition hover:border-primary/60 hover:bg-accent/40"
              >
                <FileUp className="size-8 text-primary" />
                <span className="text-sm font-medium">{form.watch("file")?.[0]?.name ?? "Choose a PDF (up to 10 MB)"}</span>
                <span className="text-xs text-muted-foreground">Machine-readable PDFs from your lab work best</span>
              </label>
              <input id="file" type="file" accept="application/pdf,.pdf" className="sr-only" {...form.register("file")} />
              {form.formState.errors.file && <p className="text-sm text-destructive">{String(form.formState.errors.file.message)}</p>}
            </div>
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Lock className="size-3.5" /> Your report stays private until you choose to share it.
            </p>
            <Button type="submit" className="w-full" disabled={upload.isPending}>
              {upload.isPending && <Loader2 className="size-4 animate-spin" />} Upload and analyze
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
