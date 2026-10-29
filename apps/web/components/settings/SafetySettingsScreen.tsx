"use client";

import Link from "next/link";
import { useState } from "react";

export function SafetySettingsScreen() {
  const [moderationEmail, setModerationEmail] = useState("");
  const [requireConsent, setRequireConsent] = useState(true);
  const [message, setMessage] = useState("");

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Safety and consent</p><h1>Safety settings</h1><p>Review generation gates, moderation contacts, and consent-first defaults.</p></div></div>
      {message ? <div className="notice" role="status">{message}</div> : null}
      <div className="settings-grid"><section className="card" aria-labelledby="safety-heading"><div className="card-kicker">Generation policy</div><h2 id="safety-heading">Consent gates</h2><label className="checkbox-field safety-toggle"><input type="checkbox" checked={requireConsent} onChange={(event) => setRequireConsent(event.target.checked)} /><span><strong>Require active consent for every generation</strong><small>Recommended. Revoked voices are blocked immediately by the API and database invariants.</small></span></label><div className="notice">Model license, voice readiness, sample quality, and moderation checks remain server-side enforcement points.</div><div className="field safety-contact"><label htmlFor="moderation-email">Moderation contact email</label><input id="moderation-email" type="email" value={moderationEmail} placeholder="safety@example.edu" onChange={(event) => setModerationEmail(event.target.value)} /><span className="field-hint">Used for workspace safety notifications; never sent to generated content recipients.</span></div><button className="button button-primary" type="button" onClick={() => setMessage("Safety settings save handoff is ready; no mutation was sent from this placeholder screen.")}>Save safety settings</button></section><section className="card" aria-labelledby="policy-heading"><div className="card-kicker">Policy and reporting</div><h2 id="policy-heading">Need help?</h2><p className="muted">Report suspected misuse or review moderator guidance without exposing source audio or private storage URLs.</p><div className="action-column"><Link className="button button-secondary" href="/admin/reports">Open safety reports</Link><Link className="button button-secondary" href="/docs/api">Read API safety guidance</Link></div></section></div>
    </>
  );
}
