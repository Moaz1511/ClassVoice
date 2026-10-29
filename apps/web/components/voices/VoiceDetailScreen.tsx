"use client";

import Link from "next/link";
import { useState } from "react";
import { EmptyState, ErrorState } from "../ui/PageState";
import { VoiceStatusBadge } from "./VoiceStatusBadge";

export function VoiceDetailScreen({ voiceId }: Readonly<{ voiceId: string }>) {
  const [confirmAction, setConfirmAction] = useState<"revoke" | "delete" | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const loadedVoiceName: string | null = null;

  function confirmLifecycleAction() {
    if (confirmAction === "delete" && (!loadedVoiceName || deleteConfirmation.trim() !== loadedVoiceName)) return;
    setMessage(confirmAction === "revoke" ? "Consent revocation is ready for the API handoff. No mutation was sent." : "Permanent deletion is ready for the API handoff. No mutation was sent.");
    setConfirmAction(null);
    setDeleteConfirmation("");
  }

  return (
    <>
      <div className="breadcrumb" aria-label="Breadcrumb"><Link href="/voices">Voice profiles</Link><span aria-hidden="true">/</span><span>Voice detail</span></div>
      <div className="page-heading"><div><p className="eyebrow">Voice profile</p><h1>Voice details</h1><p>Review consent, validation evidence, and lifecycle actions before using a voice in Studio.</p></div><button className="button button-secondary" type="button" disabled aria-disabled="true">Use in studio</button></div>

      {message ? <div className="form-success" role="status">{message}</div> : null}
      <section className="card detail-status-banner" aria-labelledby="detail-status-heading"><div><div className="card-kicker">Current status</div><h2 id="detail-status-heading">This voice is not available</h2><p className="muted">The requested voice could not be loaded from the authenticated workspace. We do not reveal whether an inaccessible voice exists.</p></div><VoiceStatusBadge status="rejected" /></section>
      <div className="voice-detail-grid">
        <section className="card" aria-labelledby="preview-heading"><div className="card-kicker">Sample preview</div><h2 id="preview-heading">Preview unavailable</h2><EmptyState title="No preview asset" description="A private preview appears only after a validated sample is available." /></section>
        <section className="card" aria-labelledby="receipt-heading"><div className="card-kicker">Consent receipt</div><h2 id="receipt-heading">Receipt unavailable</h2><dl className="metadata-list"><div><dt>Voice ID</dt><dd><code>{voiceId}</code></dd></div><div><dt>Statement version</dt><dd>Not loaded</dd></div><div><dt>Consent status</dt><dd>Not loaded</dd></div><div><dt>Attestation hash</dt><dd>Never displayed until authorized</dd></div></dl></section>
        <section className="card" aria-labelledby="quality-heading"><div className="card-kicker">Quality metrics</div><h2 id="quality-heading">Validation evidence</h2><ul className="metric-list"><li><span>Duration</span><strong>Not loaded</strong></li><li><span>Silence / clipping</span><strong>Not loaded</strong></li><li><span>Speaker warning</span><strong>Not loaded</strong></li><li><span>Model readiness</span><strong>Not loaded</strong></li></ul></section>
        <section className="card" aria-labelledby="actions-heading"><div className="card-kicker">Lifecycle</div><h2 id="actions-heading">Dangerous actions</h2><p className="muted">Revoking consent blocks new jobs immediately. Deleting queues private audio and derived assets for asynchronous cascade cleanup.</p><div className="action-column"><button className="button button-secondary" type="button" onClick={() => setConfirmAction("revoke")}>Revoke consent</button><button className="button button-danger" type="button" onClick={() => setConfirmAction("delete")}>Delete permanently</button></div></section>
      </div>

      {confirmAction ? <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="lifecycle-dialog-title"><div className="modal-header"><div><p className="eyebrow">Confirm lifecycle action</p><h2 id="lifecycle-dialog-title">{confirmAction === "revoke" ? "Revoke consent?" : "Delete this voice permanently?"}</h2></div><button className="icon-button" type="button" aria-label="Close confirmation" onClick={() => { setConfirmAction(null); setDeleteConfirmation(""); }}>×</button></div><div className="modal-body">{confirmAction === "revoke" ? <p>New generation jobs will be blocked immediately. Existing completed outputs are retained according to workspace retention rules.</p> : <><p>This queues deletion of the voice profile, reference samples, derived assets, and related metadata. This action cannot be undone.</p>{loadedVoiceName ? <div className="field"><label htmlFor="delete-voice-confirmation">Type the voice name to confirm</label><input id="delete-voice-confirmation" value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} placeholder={loadedVoiceName} /></div> : <p className="form-error">The authorized voice name is unavailable, so deletion is disabled until the voice loads successfully.</p>}</>}</div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => { setConfirmAction(null); setDeleteConfirmation(""); }}>Cancel</button><button className={`button ${confirmAction === "delete" ? "button-danger" : "button-primary"}`} type="button" disabled={confirmAction === "delete" && (!loadedVoiceName || deleteConfirmation.trim() !== loadedVoiceName)} onClick={confirmLifecycleAction}>{confirmAction === "revoke" ? "Revoke consent" : "Delete voice"}</button></div></section></div> : null}
    </>
  );
}
