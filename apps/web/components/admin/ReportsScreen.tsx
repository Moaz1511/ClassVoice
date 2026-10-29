"use client";

import { useState } from "react";
import { EmptyState } from "../ui/PageState";

type ReportStatus = "open" | "reviewing" | "resolved" | "dismissed";
const reportStatuses: ReportStatus[] = ["open", "reviewing", "resolved", "dismissed"];

export function ReportsScreen() {
  const [resourceType, setResourceType] = useState("voice_profile");
  const [resourceId, setResourceId] = useState("");
  const [reason, setReason] = useState("consent_concern");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ReportStatus | "all">("open");
  const [message, setMessage] = useState("");

  function submitReport() {
    if (!resourceId.trim()) { setMessage("Enter the resource ID so moderators can investigate the report."); return; }
    if (!description.trim()) { setMessage("Add a concise description; it will be bounded and visible only to authorized moderators."); return; }
    setMessage("Report submission handoff is ready; no report was sent from this placeholder screen.");
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Safety operations</p><h1>Safety reports</h1><p>Report suspected misuse and review bounded moderation metadata without exposing source audio.</p></div></div>
      {message ? <div className="notice" role="status">{message}</div> : null}
      <div className="reports-layout"><section className="card" aria-labelledby="submit-report-heading"><div className="card-kicker">Workspace member</div><h2 id="submit-report-heading">Submit a report</h2><p className="muted">Keep descriptions factual. Do not paste source text, audio, secrets, or private URLs.</p><div className="settings-form"><div className="field"><label htmlFor="report-resource-type">Resource type</label><select id="report-resource-type" value={resourceType} onChange={(event) => setResourceType(event.target.value)}><option value="voice_profile">Voice profile</option><option value="generation_job">Generation job</option><option value="project">Project</option><option value="webhook_endpoint">Webhook endpoint</option></select></div><div className="field"><label htmlFor="report-resource-id">Resource ID</label><input id="report-resource-id" value={resourceId} placeholder="UUID" onChange={(event) => setResourceId(event.target.value)} /></div><div className="field"><label htmlFor="report-reason">Reason</label><select id="report-reason" value={reason} onChange={(event) => setReason(event.target.value)}><option value="consent_concern">Consent concern</option><option value="impersonation">Impersonation</option><option value="unsafe_content">Unsafe content</option><option value="privacy">Privacy issue</option><option value="other">Other</option></select></div><div className="field"><label htmlFor="report-description">Description</label><textarea id="report-description" rows={6} maxLength={2_000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe what moderators should review…" /></div><div className="editor-footer"><span className="field-hint">{description.length.toLocaleString()} / 2,000</span><button className="button button-primary" type="button" onClick={submitReport}>Submit report</button></div></div></section><section className="card" aria-labelledby="review-reports-heading"><div className="card-kicker">Moderator/admin</div><h2 id="review-reports-heading">Review queue</h2><div className="field"><label htmlFor="report-status">Status</label><select id="report-status" value={status} onChange={(event) => setStatus(event.target.value as ReportStatus | "all")}><option value="all">All reports</option>{reportStatuses.map((item) => <option value={item} key={item}>{item}</option>)}</select></div><EmptyState title="No reports to review" description="New reports appear newest-first for authorized moderators. Rows contain bounded metadata and descriptions only." /></section></div>
    </>
  );
}
