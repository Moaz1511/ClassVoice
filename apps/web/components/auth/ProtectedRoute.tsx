"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getSessionStatus, subscribeAuth, type SessionState } from "../../lib/auth";

export function ProtectedRoute({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<SessionState>("checking");

  useEffect(() => {
    const check = () => {
      const sessionStatus = getSessionStatus();
      if (sessionStatus === "active") {
        setState("signed-in");
        return;
      }
      setState("signed-out");
      const reason = sessionStatus === "expired" ? "&reason=expired" : "";
      router.replace(`/auth/sign-in?returnTo=${encodeURIComponent(pathname)}${reason}`);
    };
    check();
    return subscribeAuth(check);
  }, [pathname, router]);

  if (state !== "signed-in") {
    return (
      <main className="centered-state" aria-live="polite">
        <div className="spinner" aria-hidden="true" />
        <p>Checking your ClassVoice session…</p>
      </main>
    );
  }

  return children;
}
