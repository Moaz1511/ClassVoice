"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { hasStoredSession, type SessionState } from "../../lib/auth";

export function ProtectedRoute({ children }: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<SessionState>("checking");

  useEffect(() => {
    if (hasStoredSession()) {
      setState("signed-in");
      return;
    }
    setState("signed-out");
    router.replace(`/auth/sign-in?returnTo=${encodeURIComponent(pathname)}`);
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
