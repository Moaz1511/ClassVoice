import Link from "next/link";
import { EmptyState } from "../../../components/ui/PageState";

export const metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow">Workspace overview</p><h1>Good morning, Moaz</h1><p>Build clear, consented academic audio for your learners.</p></div>
        <Link className="button button-primary" href="/studio">Generate audio <span aria-hidden="true">→</span></Link>
      </div>
      <section className="dashboard-grid" aria-label="Workspace summary">
        <article className="card dashboard-welcome" aria-labelledby="getting-started-heading">
          <div className="card-kicker">Getting started</div>
          <h2 id="getting-started-heading">Your studio is ready</h2>
          <p className="muted">Create a voice profile with consent, then use Studio to prepare your first lesson.</p>
          <div className="action-row">
            <Link className="button button-secondary" href="/voices/new">Create a voice profile</Link>
            <Link className="button button-secondary" href="/generations">View generations</Link>
          </div>
        </article>
        <article className="card dashboard-safety" aria-labelledby="safety-heading">
          <div className="card-kicker">Safety gate</div>
          <h2 id="safety-heading">Consent-first generation</h2>
          <p className="muted">Only approved voices with active consent can be submitted to the generation queue.</p>
          <span className="status-badge status-badge-success"><span className="status-dot" />Policy checks enabled</span>
        </article>
      </section>
      <section className="card dashboard-list-card" aria-labelledby="recent-heading">
        <div className="section-heading"><div><div className="card-kicker">Activity</div><h2 id="recent-heading">Recent generations</h2></div><Link className="text-link" href="/generations">View all</Link></div>
        <EmptyState title="No generations yet" description="Your completed lesson audio and safe retry controls will appear here." action={{ href: "/studio", label: "Open studio" }} />
      </section>
      <section className="dashboard-footer-note" aria-label="Data loading note">
        <span className="status-dot" aria-hidden="true" />
        <span>Workspace data will load from the authenticated API client in the next integration slice.</span>
      </section>
    </>
  );
}
