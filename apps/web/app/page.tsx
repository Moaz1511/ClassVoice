import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="auth-layout">
      <section className="auth-card" aria-labelledby="landing-heading">
        <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">CV</span><span>ClassVoice</span></Link>
        <h1 id="landing-heading">Academic voice generation with consent built in.</h1>
        <p>Create teacher-led lessons and agent-ready audio while keeping ownership, provenance, and safety visible.</p>
        <Link className="button button-primary button-block" href="/auth/sign-in">Open ClassVoice</Link>
        <div className="notice">ClassVoice uses “voice profile” and “voice sample” language. A sample can only be used after the required consent is recorded.</div>
      </section>
    </main>
  );
}
