"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AiStatus, User } from "@/lib/types";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me"), staleTime: 60_000 });
}

export function useAiStatus() {
  return useQuery({ queryKey: ["ai-status"], queryFn: () => api.get<AiStatus>("/agent/status"), staleTime: 30_000 });
}
