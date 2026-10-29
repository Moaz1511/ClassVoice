"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorState } from "../ui/PageState";
import { GenerationStatus, GenerationStatusBadge } from "./GenerationStatusBadge";

type DetailLoadState = "loading" | "ready" | "not_found" | "error";

const stateCopy: Record<GenerationStatus, string> = {
  created: "The job was accepted and is waiting for queue publication.",
  queued: "The job is waiting for an available worker.",
  processing: "The worker is rendering audio. This view refreshes with bounded backoff.",
  succeeded: "The private audio output is ready for signed playback or download.",
  failed: "The worker reported a safe error. Retry is available only when the job is retryable.",
  cancel_requested: "Cancellation was requested and will be applied at the next safe worker boundary.",
  canceled: "The job was canceled before a final output was produced.",
};

export function GenerationDetailScreen({ generationId }: Readonly<{ generationId: string }>) {
  const [loadState, setLoadState] = useState<DetailLoadState>("not_found");
  const [status] = useState<GenerationStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const [pollDelayMs, setPollDelayMs] = useState(1000);
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    if (!polling) return undefined;
    const timeout = window.setTimeout(() => {
      setPolling(false);
      setPollDelayMs((current) => Math.min(current * 2, 8_000));
      setActionMessage("Status refresh is waiting for the authenticated generation client; no job mutation was sent.");
    }, 500);
    return () => window.clearTimeout(timeout);
  }, [polling]);

  function refreshStatus() {
    setLoadState("loading");
    setPolling(true);
    window.setTimeout(() => setLoadState("not_found"), 500);
  }

  function requestCancel() {
    setActionMessage("Cancellation handoff is ready; the authenticated cancel endpoint has not been called.");
  }

  function requestRetry() {
    setActionMessage("Retry handoff is ready; the authenticated retry endpoint has not been called.");
  }

  function requestDownload() {
    setActionMessage("A signed download URL is issued only after a succeeded job is authorized. No private URL is exposed here.");
  }

  const active = status === "created" || status === "queued" || status === "processing" || status === "cancel_requested";
  const canCancel = active;
  const canRetry = status === "failed" || status === "canceled";
  const canDownload = status === "succeeded";

  return (
    <>
      <div className="breadcrumb" aria-label="Breadcrumb"><Link href="/generations">Generations</Link><span aria-hidden="true">/</span><span>Generation detail</span></div>
      <div className="page-heading"><div><p className="eyebrow">Generation job</p><h1>Output details</h1><p>Review job status, safe metadata, and signed output controls.</p></div><button className="button button-secondary" type="button" onClick={refreshStatus} disabled={loadState === "loading"}>{loadState === "loading" ? "Refreshing…" : "Refresh status"}</button></div>
      {actionMessage ? <div className="notice" role="status">{actionMessage}</div> : null}
      {loadState === "loading" ? <section className="card"><div className="page-state"><div className="spinner" aria-hidden="true" /><p>Refreshing job status with {pollDelayMs / 1000}s backoff…</p></div></section> : null}
      {loadState === "not_found" ? <section className="card generation-not-found" role="alert"><span className="state-icon" aria-hidden="true">!</span><h2>Generation is unavailable</h2><p>The requested job cannot be loaded or is no longer accessible in this workspace. We do not reveal whether an inaccessible job exists.</p><code>{generationId}</code><Link className="button button-secondary" href="/generations">Return to generations</Link></section> : null}
      {loadState === "error" ? <section className="card"><ErrorState title="Generation status could not be loaded" description="Retry without submitting a duplicate generation request." /></section> : null}
      {loadState === "ready" && status ? <><section className="card generation-status-banner"><div><div className="card-kicker">Current state</div><h2>{stateCopy[status]}</h2><p className="muted">Job IDs and hashes are safe metadata; source text is not displayed in collection views.</p></div><GenerationStatusBadge status={status} /></section><div className="generation-detail-grid"><section className="card audio-player-card" aria-labelledby="player-heading"><div className="card-kicker">Audio output</div><h2 id="player-heading">{canDownload ? "Signed playback" : "Output not ready"}</h2><div className="audio-player-placeholder"><span className="state-icon" aria-hidden="true">▶</span><span>{canDownload ? "The player will receive a short-lived signed URL." : "Playback controls appear after a private output asset is available."}</span></div><button className="button button-primary" type="button" disabled={!canDownload} onClick={requestDownload}>Download signed output</button></section><section className="card" aria-labelledby="metadata-heading"><div className="card-kicker">Safe metadata</div><h2 id="metadata-heading">Provenance</h2><dl className="metadata-list"><div><dt>Job ID</dt><dd><code>{generationId}</code></dd></div><div><dt>Voice</dt><dd>Authorized voice metadata only</dd></div><div><dt>Model</dt><dd>Recorded per job</dd></div><div><dt>Input text</dt><dd>SHA-256 only</dd></div><div><dt>Output checksum</dt><dd>{canDownload ? "Available" : "Pending"}</dd></div></dl></section></div><section className="card generation-actions"><div><div className="card-kicker">Job controls</div><h2>Lifecycle actions</h2></div><div className="action-row"><button className="button button-secondary" type="button" disabled={!canCancel} onClick={requestCancel}>Cancel generation</button><button className="button button-secondary" type="button" disabled={!canRetry} onClick={requestRetry}>Retry generation</button><button className="button button-secondary" type="button" disabled={!canDownload} onClick={requestDownload}>Download</button></div></section></> : null}
    </>
  );
}
