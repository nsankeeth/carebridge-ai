"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";

interface AuditRow {
  id: string;
  action: string;
  actor_type: string;
  actor_name: string | null;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export default function AuditPage() {
  const [filter, setFilter] = useState("");
  const q = useQuery({
    queryKey: ["audit", filter],
    queryFn: () => api.get<AuditRow[]>(`/admin/audit?limit=200${filter ? `&action=${encodeURIComponent(filter)}` : ""}`),
    refetchInterval: 10_000,
  });
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-end justify-between gap-4">
        <div>
          <CardTitle>Audit log</CardTitle>
          <CardDescription>Uploads, AI processing, consent, sharing, clinician access, reviews and follow-ups. No medical content is logged.</CardDescription>
        </div>
        <Input className="max-w-xs" placeholder="Filter by action prefix, e.g. consent" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </CardHeader>
      <CardContent className="p-0">
        <Table data-testid="audit-table">
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead>Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.data?.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDate(e.created_at, true)}</TableCell>
                <TableCell className="font-mono text-xs">{e.action}</TableCell>
                <TableCell className="text-sm">
                  {e.actor_type === "USER" ? e.actor_name : <Badge variant="secondary">{e.actor_type.toLowerCase()}</Badge>}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {e.resource_type} {e.resource_id?.slice(0, 8)}
                </TableCell>
                <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground" title={JSON.stringify(e.details)}>
                  {Object.entries(e.details)
                    .map(([k, v]) => `${k}=${typeof v === "string" ? v.slice(0, 40) : JSON.stringify(v)}`)
                    .join(" ")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
