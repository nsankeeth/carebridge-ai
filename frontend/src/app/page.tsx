"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useMe } from "@/hooks/use-me";

const HOME = { PATIENT: "/patient", CLINICIAN: "/clinician", ADMIN: "/admin" } as const;

export default function Index() {
  const router = useRouter();
  const { data, isError } = useMe();
  useEffect(() => {
    if (data) router.replace(HOME[data.role]);
    if (isError) router.replace("/login");
  }, [data, isError, router]);
  return null;
}
