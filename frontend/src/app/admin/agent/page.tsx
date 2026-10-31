"use client";

import { useQuery } from "@tanstack/react-query";
import { Cpu } from "lucide-react";
import { AgentTrace } from "@/components/case-ui";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAiStatus } from "@/hooks/use-me";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Execution, ModelCall } from "@/lib/types";

export default function AgentPage() {
  const ai = useAiStatus();
  const execs = useQuery({ queryKey: ["admin-executions"], queryFn: () => api.get<Execution[]>("/admin/executions?limit=20"), refetchInterval: 5000 });
  const calls = useQuery({ queryKey: ["admin-model-calls"], queryFn: () => api.get<ModelCall[]>("/admin/model-calls?limit=50"), refetchInterval: 5000 });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Agent & Meta AI</h1>
        <p className="text-muted-foreground">What the agents did and every model inference behind it.</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="size-5 text-primary" /> Model provider
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 text-sm sm:grid-cols-4" data-testid="ai-status">
          <div>
            <p className="text-muted-foreground">Provider</p>
            <p className="font-medium">Meta Model API</p>
          </div>
          <div>
            <p className="text-muted-foreground">Model</p>
            <p className="font-mono">{ai.data?.model}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Endpoint</p>
            <p className="font-mono">{ai.data?.base_url}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Last successful Meta inference</p>
            <p>
              {ai.data?.last_successful_meta_call
                ? `${formatDate(ai.data.last_successful_meta_call.created_at, true)} (${ai.data.last_successful_meta_call.model_id})`
                : "None yet"}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Inference log</CardTitle>
          <CardDescription>Model identifier, status, latency and token usage as reported by the API.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table data-testid="model-call-table">
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Task</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Tokens (in / out)</TableHead>
                <TableHead>Response id</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {calls.data?.map((m) => (
                <TableRow key={m.id}>
                  <TableCell className="text-xs text-muted-foreground">{formatDate(m.created_at, true)}</TableCell>
                  <TableCell>{m.task}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {m.provider}/{m.model_id}
                  </TableCell>
                  <TableCell className={m.status === "ok" ? "text-emerald-700" : "text-destructive"} title={m.error ?? ""}>
                    {m.status}
                  </TableCell>
                  <TableCell>{(m.latency_ms / 1000).toFixed(2)}s</TableCell>
                  <TableCell className="font-mono text-xs">
                    {m.input_tokens ?? "—"} / {m.output_tokens ?? "—"}
                  </TableCell>
                  <TableCell className="max-w-40 truncate font-mono text-xs text-muted-foreground">{m.response_id ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {execs.data?.map((e) => <AgentTrace key={e.id} execution={e} />)}
      </div>
    </div>
  );
}
