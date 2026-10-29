"use client";

import { useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../ui/PageState";

type LoadState = "loading" | "ready" | "error";
const auditRows: never[] = [];

export function AuditScreen() {
  const [loadState, setLoadState] = useState<LoadState>("ready");
  const [action, setAction] = useState("all");
  const [actor, setActor] = useState("all");
  const [search, setSearch] = useState("");

  function refresh() {
    setLoadState("loading");
    window.setTimeout(() => setLoadState("ready"), 250);
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Moderator and admin view</p><h1>Audit log</h1><p>Inspect append-only activity with request correlation and redacted metadata.</p></div><button className="button button-secondary" type="button" onClick={refresh}>{loadState === "loading" ? "Refreshing…" : "Refresh"}</button></div>
      <section className="card audit-filter-card"><div className="filter-toolbar audit-filters"><div className="field filter-search"><label htmlFor="audit-search">Search request or resource ID</label><input id="audit-search" value={search} placeholder="UUID or request ID" onChange={(event) => setSearch(event.target.value)} /></div><div className="field"><label htmlFor="audit-action">Action</label><select id="audit-action" value={action} onChange={(event) => setAction(event.target.value)}><option value="all">All actions</option><option value="voice.created">Voice created</option><option value="generation.created">Generation created</option><option value="generation.downloaded">Generation downloaded</option><option value="api_key.revoked">API key revoked</option><option value="moderation.reported">Report submitted</option></select></div><div className="field"><label htmlFor="audit-actor">Actor</label><select id="audit-actor" value={actor} onChange={(event) => setActor(event.target.value)}><option value="all">All actors</option><option value="user">User</option><option value="api_key">API key</option><option value="worker">Worker</option><option value="moderator">Moderator</option><option value="system">System</option></select></div></div><p className="field-hint audit-safe-note">Payloads, source text, audio bytes, signed URLs, API-key secrets, and webhook secrets are redacted at the service boundary.</p></section>
      {loadState === "loading" ? <section className="card"><LoadingState label="Loading audit events…" /></section> : null}
      {loadState === "error" ? <section className="card"><ErrorState title="Audit events could not be loaded" description="Retry without changing your filters." /></section> : null}
      {loadState === "ready" && auditRows.length === 0 ? <section className="card audit-empty-card"><EmptyState title="No audit events yet" description="Authorized workspace activity will appear here in newest-first order. Audit rows are append-only and cannot be edited from the UI." /></section> : null}
    </>
  );
}
