"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { signIn, signInSchema, signInWithDemo } from "../../../lib/auth";

function safeReturnTo(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

export default function SignInPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("returnTo"));
  const expired = searchParams.get("reason") === "expired";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const parsed = signInSchema.safeParse({ email, password });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Check your sign-in details.");
      return;
    }
    setSubmitting(true);
    try {
      await signIn(parsed.data);
      router.replace(returnTo);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in failed. Try again.");
      setSubmitting(false);
    }
  }

  async function handleDemoSignIn() {
    setError(null);
    setSubmitting(true);
    await signInWithDemo();
    router.replace(returnTo);
  }

  return (
    <main className="auth-layout">
      <section className="card auth-card" aria-labelledby="sign-in-heading">
        <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">CV</span><span>ClassVoice</span></Link>
        <h1 id="sign-in-heading">Welcome back</h1>
        <p>Sign in to manage your consented voice profiles and academic generations.</p>
        <form className="auth-form" onSubmit={handleSubmit} noValidate>
          {expired && <div className="form-error" role="status">Your session expired. Sign in again to continue.</div>}
          {error && <div className="form-error" role="alert">{error}</div>}
          <div className="field"><label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} aria-invalid={Boolean(error)} /></div>
          <div className="field"><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} aria-invalid={Boolean(error)} /></div>
          <button className="button button-primary button-block" type="submit" disabled={submitting}>{submitting ? "Signing in…" : "Sign in"}</button>
        </form>
        <div className="divider">or</div>
        <button className="button button-secondary button-block" type="button" onClick={handleDemoSignIn} disabled={submitting}>Continue with local demo</button>
        <div className="auth-links"><Link className="text-link" href="/auth/reset-password">Forgot password?</Link><span aria-hidden="true">·</span><Link className="text-link" href="/auth/sign-up">Create account</Link></div>
        <div className="notice">Production sessions use the configured Supabase provider. The local demo keeps only a non-credential expiry marker in session storage; access tokens stay in memory.</div>
      </section>
    </main>
  );
}
