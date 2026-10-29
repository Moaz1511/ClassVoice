"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { signInWithDemo } from "../../../lib/auth";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (searchParams.get("error")) {
      setError("The sign-in provider could not complete this request.");
      return;
    }
    void signInWithDemo().then(() => router.replace("/onboarding"));
  }, [router, searchParams]);

  if (error) return <main className="error-state"><h1>Sign-in could not be completed.</h1><p>{error}</p><Link className="button button-primary" href="/auth/sign-in">Return to sign in</Link></main>;
  return <main className="centered-state" aria-live="polite"><div className="spinner" aria-hidden="true" /><p>Completing secure sign-in…</p></main>;
}
