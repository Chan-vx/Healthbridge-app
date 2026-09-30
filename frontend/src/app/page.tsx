"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getSession, HOME } from "@/lib/api";

export default function Index() {
  const router = useRouter();
  useEffect(() => {
    const session = getSession();
    router.replace(session ? HOME[session.user.role] : "/login");
  }, [router]);
  return null;
}
