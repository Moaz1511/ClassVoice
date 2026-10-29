const statusLabels: Record<string, string> = {
  draft: "Draft",
  validating: "Validating",
  processing: "Processing",
  ready: "Ready",
  rejected: "Needs attention",
  revoked: "Consent revoked",
  archived: "Archived",
};

export function VoiceStatusBadge({ status }: Readonly<{ status: string }>) {
  const label = statusLabels[status] ?? "Unknown status";
  const tone = status === "ready" ? "success" : status === "revoked" || status === "rejected" ? "danger" : "neutral";
  return <span className={`status-badge status-badge-${tone}`}><span className="status-dot" aria-hidden="true" />{label}</span>;
}
