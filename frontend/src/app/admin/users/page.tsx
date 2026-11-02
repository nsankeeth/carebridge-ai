"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useMe } from "@/hooks/use-me";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

const schema = z.object({
  full_name: z.string().trim().min(1, "Required"),
  email: z.string().email(),
  role: z.enum(["PATIENT", "CLINICIAN", "ADMIN"]),
  password: z.string().min(8, "At least 8 characters"),
});
type Form = z.infer<typeof schema>;

export default function UsersPage() {
  const qc = useQueryClient();
  const me = useMe();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get<User[]>("/admin/users") });
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { full_name: "", email: "", role: "PATIENT", password: "" } });
  const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Failed");
  const create = useMutation({
    mutationFn: (v: Form) => api.post("/admin/users", v),
    onSuccess: () => {
      toast.success("Demo account created");
      form.reset();
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError,
  });
  const onCall = useMutation({
    mutationFn: (u: User) => api.patch(`/admin/users/${u.id}`, { on_call: !u.clinician?.on_call }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
    onError,
  });
  const toggle = useMutation({
    mutationFn: (u: User) => api.patch(`/admin/users/${u.id}`, { is_active: !u.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
    onError,
  });

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Accounts</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data?.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    {u.full_name}
                    {u.clinician && (
                      <span className="block text-xs text-muted-foreground">
                        {u.clinician.specialty}
                        {u.clinician.on_call && <Badge className="ml-1 h-4 text-[10px]">on call · #{u.clinician.on_call_priority}</Badge>}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">{u.email}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{u.role.toLowerCase()}</Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {u.clinician && (
                      <Button size="sm" variant="ghost" data-testid={`on-call-${u.email}`} onClick={() => onCall.mutate(u)}>
                        {u.clinician.on_call ? "Take off call" : "Put on call"}
                      </Button>
                    )}
                    {u.id !== me.data?.id && (
                      <Button size="sm" variant="ghost" onClick={() => toggle.mutate(u)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Add account</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            {(["full_name", "email", "password"] as const).map((k) => (
              <div key={k} className="space-y-1">
                <Label htmlFor={k} className="capitalize">{k.replace("_", " ")}</Label>
                <Input id={k} type={k === "password" ? "password" : "text"} {...form.register(k)} />
                {form.formState.errors[k] && <p className="text-xs text-destructive">{form.formState.errors[k]?.message}</p>}
              </div>
            ))}
            <div className="space-y-1">
              <Label>Role</Label>
              <Controller
                control={form.control}
                name="role"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="PATIENT">Patient</SelectItem>
                      <SelectItem value="CLINICIAN">Clinician</SelectItem>
                      <SelectItem value="ADMIN">Administrator</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
            <Button type="submit" className="w-full" disabled={create.isPending}>
              Create account
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
