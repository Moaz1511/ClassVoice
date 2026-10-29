"use client";

import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useState } from "react";
import { passwordSchema, requestPasswordReset, resetPassword } from "../../../lib/auth";

export default function ResetPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState(searchParams.get("mode") === "reset" ? "reset" : "request");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    setSubmitting(true);
    await requestPasswordReset(email);
    setMessage("If an account exists for that email, reset instructions are ready.");
    setSubmitting(false);
  }

  async function handleReset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const parsed = passwordSchema.safeParse({ password, confirmPassword });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Check your new password.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(parsed.data.password);
      setMessage("Password updated. You can sign in with your new password.");
      setMode("request");
      setPassword("");
      setConfirmPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Password reset failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="card auth-card" aria-labelledby="reset-heading">
        <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">CV</span><span>ClassVoice</span></Link>
        <h1 id="reset-heading">{mode === "reset" ? "Choose a new password" : "Reset your password"}</h1>
        <p>{mode === "reset" ? "Use a strong password you have not used elsewhere." : "We will send a reset link without revealing whether an account exists."}</p>
        {error && <div className="form-error" role="alert">{error}</div>}
        {message && <div className="form-success" role="status">{message}</div>}
        {mode === "reset" ? <form className="auth-form" onSubmit={handleReset} noValidate><div className="field"><label htmlFor="password">New password</label><input id="password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></div><div className="field"><label htmlFor="confirm-password">Confirm new password</label><input id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></div><button className="button button-primary button-block" type="submit" disabled={submitting}>{submitting ? "Updating…" : "Update password"}</button></form> : <form className="auth-form" onSubmit={handleRequest} noValidate><div className="field"><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></div><button className="button button-primary button-block" type="submit" disabled={submitting}>{submitting ? "Sending…" : "Send reset link"}</button></form>}
        {mode === "request" && message && <button className="button button-secondary button-block" type="button" onClick={() => { setMode("reset"); router.replace("/auth/reset-password?mode=reset"); }}>Continue to local reset</button>}
        <div className="auth-links"><Link className="text-link" href="/auth/sign-in">Back to sign in</Link></div>
      </section>
    </main>
  );
}
