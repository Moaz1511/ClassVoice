"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { signUp, signUpSchema } from "../../../lib/auth";

export default function SignUpPage() {
  const router = useRouter();
  const [values, setValues] = useState({ email: "", displayName: "", password: "", confirmPassword: "", termsAccepted: false });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function update(name: keyof typeof values, value: string | boolean) {
    setValues((current) => ({ ...current, [name]: value }));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const parsed = signUpSchema.safeParse(values);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Check the highlighted fields.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await signUp(parsed.data);
      router.push(`/auth/verify-email?email=${encodeURIComponent(result.email)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Account creation failed. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="card auth-card" aria-labelledby="sign-up-heading">
        <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">CV</span><span>ClassVoice</span></Link>
        <h1 id="sign-up-heading">Create your account</h1>
        <p>Start with a workspace for consented academic voice generation.</p>
        <form className="auth-form" onSubmit={handleSubmit} noValidate>
          {error && <div className="form-error" role="alert">{error}</div>}
          <div className="field"><label htmlFor="display-name">Display name</label><input id="display-name" type="text" autoComplete="name" value={values.displayName} onChange={(event) => update("displayName", event.target.value)} /></div>
          <div className="field"><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" value={values.email} onChange={(event) => update("email", event.target.value)} /></div>
          <div className="field"><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="new-password" value={values.password} onChange={(event) => update("password", event.target.value)} /><span className="field-hint">At least 12 characters, without spaces.</span></div>
          <div className="field"><label htmlFor="confirm-password">Confirm password</label><input id="confirm-password" type="password" autoComplete="new-password" value={values.confirmPassword} onChange={(event) => update("confirmPassword", event.target.value)} /></div>
          <div className="checkbox-field"><input id="terms" type="checkbox" checked={values.termsAccepted} onChange={(event) => update("termsAccepted", event.target.checked)} /><label htmlFor="terms">I accept the ClassVoice terms and understand that voice samples require documented consent.</label></div>
          <button className="button button-primary button-block" type="submit" disabled={submitting}>{submitting ? "Creating account…" : "Create account"}</button>
        </form>
        <div className="auth-links"><span>Already have an account?</span><Link className="text-link" href="/auth/sign-in">Sign in</Link></div>
      </section>
    </main>
  );
}
