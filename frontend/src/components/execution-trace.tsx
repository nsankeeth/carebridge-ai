"use client";

import { useQuery } from "@tanstack/react-query";
import { AgentTrace } from "@/components/case-ui";
import { api } from "@/lib/api";
import type { Execution } from "@/lib/types";

/** Fetches a run with its model-call log and polls while it is still running. */
export function ExecutionTrace({ execution }: { execution: Execution }) {
  const q = useQuery({
    queryKey: ["execution", execution.id],
    queryFn: () => api.get<Execution>(`/agent/executions/${execution.id}`),
    initialData: execution,
    refetchInterval: (query) => (query.state.data?.status === "RUNNING" ? 1500 : false),
  });
  return <AgentTrace execution={q.data ?? execution} />;
}
