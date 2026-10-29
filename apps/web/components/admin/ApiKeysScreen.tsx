"use client";

import { useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../ui/PageState";
import { SecretReveal } from "./SecretReveal";

type KeyStatus = "active" | "revoked" | "expired";
type ApiKeyRecord = Readonly<{ id: string; name: string; prefix: string; scopes: string[]; status: KeyStatus; expiresAt: string | null; lastUsedAt: string | null }>;
type LoadState = "loading" | "ready" | "error";

const records: ApiKeyRecord[] = [];
const scopeOptions = ["voices:read", "voices:write", "projects:read", "projects:write", "generations:create", "generations:read", "api_keys:read", "api_keys:write", "webhooks:read", "webhooks:write"];

export function ApiKeysScreen() {
  const [loadState, setLoadState] = useState<LoadState>("ready");
  const [statusFilter, setStatusFilter] = useState<"all" | KeyStatus>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["generations:create", "generations:read"]);
  const [expiry, setExpiry] = useState("90");
  const [formMessage, setFormMessage] = useState("");
  const [issuedSecret, setIssuedSecret] = useState<string | null>(null);

  const visibleRecords = records.filter((record) => statusFilter === "all" || record.status === statusFilter);
  function refresh() {
    setLoadState("loading");
    window.setTimeout(() => setLoadState("ready"), 250);
  }
  function toggleScope(scope: string) {
    setScopes((current) => current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope]);
  }
  function createKey() {
    if (!name.trim()) { setFormMessage("Give this key a recognizable name."); return; }
    if (scopes.length === 0) { setFormMessage("Select at least one scope."); return; }
    setFormMessage("The authenticated API will issue this key and return its secret exactly once. No secret is generated in the browser.");
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Workspace administration</p><h1>API keys</h1><p>Issue scoped machine credentials for approved ClassVoice agents. Secrets are never recoverable after creation.</p></div><button className="button button-primary" type="button" onClick={() => { setCreateOpen(true); setFormMessage(""); }}>Create API key <span aria-hidden="true">→</span></button></div>
      <section className="card admin-toolbar"><div className="field"><label htmlFor="api-key-status">Status</label><select id="api-key-status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | KeyStatus)}><option value="all">All keys</option><option value="active">Active</option><option value="expired">Expired</option><option value="revoked">Revoked</option></select></div><p className="field-hint">The list shows prefixes, scopes, expiry, and last-used time only.</p><button className="button button-secondary" type="button" onClick={refresh}>{loadState === "loading" ? "Refreshing…" : "Refresh"}</button></section>
      {issuedSecret ? <SecretReveal kind="API key" secret={issuedSecret} onDismiss={() => setIssuedSecret(null)} /> : null}
      {loadState === "loading" ? <section className="card"><LoadingState label="Loading API-key metadata…" /></section> : null}
      {loadState === "error" ? <section className="card"><ErrorState title="API keys could not be loaded" description="Retry without exposing or regenerating any secret." /></section> : null}
      {loadState === "ready" && visibleRecords.length === 0 ? <section className="card admin-empty-card"><EmptyState title="No API keys yet" description="Create a scoped key for an agent or integration. The secret will be shown once by the server and then only its prefix will remain visible." action={{ href: "#create-api-key", label: "Create an API key" }} /></section> : null}
      {loadState === "ready" && visibleRecords.length > 0 ? <section className="card admin-table-card"><div className="voice-table-header"><h2>{visibleRecords.length} key{visibleRecords.length === 1 ? "" : "s"}</h2><span className="field-hint">Secrets are not listed</span></div>{visibleRecords.map((record) => <div className="admin-row" key={record.id}><div><strong>{record.name}</strong><small>{record.prefix}… · {record.scopes.join(", ")}</small></div><span className={`status-badge status-badge-${record.status === "active" ? "success" : "neutral"}`}>{record.status}</span><button className="button button-secondary" type="button" disabled={record.status !== "active"} onClick={() => setRevokeId(record.id)}>Revoke</button></div>)}</section> : null}

      {createOpen ? <div className="modal-backdrop"><section className="modal admin-modal" id="create-api-key" role="dialog" aria-modal="true" aria-labelledby="api-key-dialog-title"><div className="modal-header"><div><p className="eyebrow">One-time secret issuance</p><h2 id="api-key-dialog-title">Create an API key</h2></div><button className="icon-button" type="button" aria-label="Close create API key dialog" onClick={() => setCreateOpen(false)}>×</button></div><div className="modal-body"><div className="field"><label htmlFor="api-key-name">Name</label><input id="api-key-name" value={name} maxLength={100} placeholder="Lesson agent" onChange={(event) => setName(event.target.value)} /></div><fieldset className="scope-fieldset"><legend>Scopes</legend><div className="scope-grid">{scopeOptions.map((scope) => <label className="checkbox-field" key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={() => toggleScope(scope)} /><span>{scope}</span></label>)}</div></fieldset><div className="field"><label htmlFor="api-key-expiry">Expiration</label><select id="api-key-expiry" value={expiry} onChange={(event) => setExpiry(event.target.value)}><option value="30">30 days</option><option value="90">90 days</option><option value="365">365 days</option><option value="never">No expiration (admin policy permitting)</option></select></div>{formMessage ? <div className="notice" role="status">{formMessage}</div> : null}</div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setCreateOpen(false)}>Cancel</button><button className="button button-primary" type="button" onClick={createKey}>Create key</button></div></section></div> : null}
      {revokeId ? <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="revoke-key-title"><div className="modal-header"><div><p className="eyebrow">Immediate access change</p><h2 id="revoke-key-title">Revoke this API key?</h2></div><button className="icon-button" type="button" aria-label="Close revoke dialog" onClick={() => setRevokeId(null)}>×</button></div><div className="modal-body"><p>Machine requests using this key will be rejected immediately. This action cannot be undone.</p></div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setRevokeId(null)}>Cancel</button><button className="button button-danger" type="button" onClick={() => { setRevokeId(null); setFormMessage("Revoke handoff is ready; no mutation was sent from this placeholder screen."); }}>Revoke key</button></div></section></div> : null}
    </>
  );
}
