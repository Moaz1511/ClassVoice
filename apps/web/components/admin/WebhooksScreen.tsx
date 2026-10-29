"use client";

import { useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../ui/PageState";
import { SecretReveal } from "./SecretReveal";

type EndpointStatus = "pending_verification" | "active" | "disabled";
type DeliveryStatus = "pending" | "delivered" | "retrying" | "failed" | "abandoned";
type Endpoint = Readonly<{ id: string; url: string; events: string[]; status: EndpointStatus; failureCount: number; lastDeliveredAt: string | null }>;
type LoadState = "loading" | "ready" | "error";

const endpoints: Endpoint[] = [];
const eventOptions = ["generation.created", "generation.succeeded", "generation.failed", "generation.canceled", "voice.ready", "voice.revoked", "project.updated"];
const deliveryStates: DeliveryStatus[] = ["pending", "delivered", "retrying", "failed", "abandoned"];

export function WebhooksScreen() {
  const [loadState, setLoadState] = useState<LoadState>("ready");
  const [addOpen, setAddOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["generation.succeeded", "generation.failed"]);
  const [formMessage, setFormMessage] = useState("");
  const [issuedSecret, setIssuedSecret] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState("");

  function refresh() {
    setLoadState("loading");
    window.setTimeout(() => setLoadState("ready"), 250);
  }
  function toggleEvent(eventName: string) {
    setEvents((current) => current.includes(eventName) ? current.filter((item) => item !== eventName) : [...current, eventName]);
  }
  function addEndpoint() {
    if (!url.trim().startsWith("https://")) { setFormMessage("Use an HTTPS URL. The server also re-checks DNS and blocks private or loopback addresses."); return; }
    if (events.length === 0) { setFormMessage("Select at least one event."); return; }
    setFormMessage("The authenticated API will validate DNS/SSRF policy and return the signing secret exactly once. No endpoint or secret was created in the browser.");
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Workspace administration</p><h1>Webhooks</h1><p>Deliver signed, replay-protected generation events to trusted HTTPS endpoints.</p></div><button className="button button-primary" type="button" onClick={() => { setAddOpen(true); setFormMessage(""); }}>Add endpoint <span aria-hidden="true">→</span></button></div>
      <section className="card admin-toolbar"><p className="field-hint">Server validation rejects non-HTTPS URLs, credentials, fragments, private IPs, and unsafe redirects.</p><button className="button button-secondary" type="button" onClick={refresh}>{loadState === "loading" ? "Refreshing…" : "Refresh"}</button></section>
      {issuedSecret ? <SecretReveal kind="webhook signing secret" secret={issuedSecret} onDismiss={() => setIssuedSecret(null)} /> : null}
      {loadState === "loading" ? <section className="card"><LoadingState label="Loading webhook endpoints…" /></section> : null}
      {loadState === "error" ? <section className="card"><ErrorState title="Webhook endpoints could not be loaded" description="Retry without creating a duplicate endpoint or revealing a signing secret." /></section> : null}
      {loadState === "ready" && endpoints.length === 0 ? <section className="card admin-empty-card"><EmptyState title="No webhook endpoints" description="Add an HTTPS endpoint to receive signed events. The signing secret is shown once and then only its prefix remains visible." action={{ href: "#add-webhook", label: "Add a webhook endpoint" }} /></section> : null}
      {loadState === "ready" && endpoints.length > 0 ? <section className="card admin-table-card"><div className="voice-table-header"><h2>{endpoints.length} endpoint{endpoints.length === 1 ? "" : "s"}</h2><span className="field-hint">Secrets are not listed</span></div>{endpoints.map((endpoint) => <div className="admin-row" key={endpoint.id}><div><strong>{endpoint.url}</strong><small>{endpoint.events.join(", ")} · {endpoint.failureCount} consecutive failures</small></div><span className={`status-badge status-badge-${endpoint.status === "active" ? "success" : endpoint.status === "disabled" ? "danger" : "warning"}`}>{endpoint.status.replace("_", " ")}</span><button className="button button-secondary" type="button" disabled={endpoint.status !== "active"} onClick={() => setTestMessage("Test event handoff is ready; no delivery was sent from this placeholder screen.")}>Send test</button></div>)}</section> : null}
      <section className="card delivery-card" aria-labelledby="delivery-history-title"><div className="section-heading"><div><div className="card-kicker">Delivery history</div><h2 id="delivery-history-title">Signed event deliveries</h2></div><span className="field-hint">{deliveryStates.length} supported states</span></div><EmptyState title="No deliveries yet" description="Pending, delivered, retrying, failed, and abandoned delivery rows will appear after an endpoint is active." />{testMessage ? <div className="notice" role="status">{testMessage}</div> : null}</section>

      {addOpen ? <div className="modal-backdrop"><section className="modal admin-modal" id="add-webhook" role="dialog" aria-modal="true" aria-labelledby="webhook-dialog-title"><div className="modal-header"><div><p className="eyebrow">SSRF-safe endpoint setup</p><h2 id="webhook-dialog-title">Add webhook endpoint</h2></div><button className="icon-button" type="button" aria-label="Close add webhook dialog" onClick={() => setAddOpen(false)}>×</button></div><div className="modal-body"><div className="field"><label htmlFor="webhook-url">HTTPS endpoint URL</label><input id="webhook-url" type="url" value={url} placeholder="https://example.edu/classvoice/events" onChange={(event) => setUrl(event.target.value)} /><span className="field-hint">Redirects and private DNS/IP targets are rejected server-side.</span></div><fieldset className="scope-fieldset"><legend>Events</legend><div className="scope-grid">{eventOptions.map((eventName) => <label className="checkbox-field" key={eventName}><input type="checkbox" checked={events.includes(eventName)} onChange={() => toggleEvent(eventName)} /><span>{eventName}</span></label>)}</div></fieldset>{formMessage ? <div className="notice" role="status">{formMessage}</div> : null}</div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setAddOpen(false)}>Cancel</button><button className="button button-primary" type="button" onClick={addEndpoint}>Add endpoint</button></div></section></div> : null}
    </>
  );
}
