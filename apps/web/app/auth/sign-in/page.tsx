"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { beginLocalSession } from "../../../lib/auth";

export default function SignInPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("returnTo") || "/dashboard";

  function handleLocalSignIn() {
    beginLocalSession();
    router.replace(returnTo.startsWith("/") ? returnTo : "/dashboard");
  }

  return (
    <main className="auth-layout">
      <section className="card auth-card" aria-labelledby="sign-in-heading">
        <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">CV</span><span>ClassVoice</span></Link>
        <h1 id="sign-in-heading">Welcome back</h1>
        <p>Sign in to manage your consented voice profiles and academic generations.</p>
        <button className="button button-primary button-block" type="button" onClick={handleLocalSignIn}>Continue to local workspace</button>
        <div className="notice">The Supabase email/OAuth form is connected in the next auth screen step. This local action only creates a development session marker.</div>
      </section>
    </main>
  );
}
