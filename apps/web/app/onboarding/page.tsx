"use client";

import Link from "next/link";
import { ProtectedRoute } from "../../components/auth/ProtectedRoute";

export default function OnboardingPage() {
  return <ProtectedRoute><main className="auth-layout"><section className="card onboarding-card" aria-labelledby="onboarding-heading"><span className="eyebrow">First-time setup</span><h1 id="onboarding-heading">Set up your learning workspace</h1><p className="muted">ClassVoice keeps workspace ownership, consent, and generated-audio provenance visible from the start.</p><ul className="safety-list"><li>Create a workspace for your class or teaching project.</li><li>Use only voice samples you own or have permission to use.</li><li>Every generated output is labeled as AI-generated and remains private by default.</li></ul><Link className="button button-primary button-block" href="/dashboard">Create workspace and continue</Link><p className="field-hint" style={{ marginTop: "16px" }}>Workspace invitations and role selection will be connected to the API onboarding transaction in the next integration step.</p></section></main></ProtectedRoute>;
}
