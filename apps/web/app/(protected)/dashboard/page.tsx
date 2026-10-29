export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <>
      <div className="page-heading">
        <div><h1>Good morning, Moaz</h1><p>Build clear, consented academic audio for your learners.</p></div>
        <a className="button button-primary" href="/studio">Generate audio <span aria-hidden="true">→</span></a>
      </div>
      <section className="card" aria-labelledby="getting-started-heading">
        <h2 id="getting-started-heading">Your studio is ready</h2>
        <p className="muted">Create a voice profile with consent, then use Studio to prepare your first lesson.</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", marginTop: "20px" }}>
          <a className="button button-secondary" href="/voices/new">Create a voice profile</a>
          <a className="button button-secondary" href="/generations">View generations</a>
        </div>
      </section>
    </>
  );
}
