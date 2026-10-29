"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { verifyEmail } from "../../../lib/auth";

type VerifyState = "pending" | "success" | "error";

export default function VerifyEmailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams.get("email") ?? "your email address";
  const [state, setState] = useState<VerifyState>("pending");
  const [error, setError] = useState<string | null>(null);

  async function handleVerify() {
    setError(null);
    try {
      await verifyEmail(email);
      setState("success");
    } catch (cause) {
      setState("error");
      setError(cause instanceof Error ? cause.message : "Verification failed.");
    }
  }

  return (
    <main className="auth-layout">
      <section className="card auth-card" aria-labelledby="verify-heading">
        <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">CV</span><span>ClassVoice</span></Link>
        {state === "success" ? <><h1 id="verify-heading">Email verified</h1><p>Your account is ready. Sign in to create your workspace.</p><Link className="button button-primary button-block" href="/auth/sign-in">Continue to sign in</Link></> : <><h1 id="verify-heading">Check your email</h1><p>We sent a verification link to <strong>{email}</strong>. Verify it before signing in.</p>{state === "error" && <div className="form-error" role="alert">{error}</div>}<button className="button button-primary button-block" type="button" onClick={handleVerify}>I verified my email</button><button className="button button-secondary button-block" type="button" onClick={() => router.refresh()}>Check again</button><div className="notice">The local development provider uses this button to model the verification transition. Production uses the allowlisted Supabase callback.</div></>}
        <div className="auth-links"><Link className="text-link" href="/auth/sign-in">Back to sign in</Link></div>
      </section>
    </main>
  );
}
