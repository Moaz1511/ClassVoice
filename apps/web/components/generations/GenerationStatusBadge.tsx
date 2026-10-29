export type GenerationStatus = "created" | "queued" | "processing" | "succeeded" | "failed" | "cancel_requested" | "canceled";

const statusLabels: Record<GenerationStatus, string> = {
  created: "Created",
  queued: "Queued",
  processing: "Processing",
  succeeded: "Succeeded",
  failed: "Failed",
  cancel_requested: "Cancel requested",
  canceled: "Canceled",
};

const statusTones: Record<GenerationStatus, "success" | "danger" | "warning" | "neutral"> = {
  created: "neutral",
  queued: "neutral",
  processing: "warning",
  succeeded: "success",
  failed: "danger",
  cancel_requested: "warning",
  canceled: "neutral",
};

export function GenerationStatusBadge({ status }: Readonly<{ status: GenerationStatus }>) {
  const tone = statusTones[status];
  return <span className={`status-badge status-badge-${tone}`}><span className="status-dot" aria-hidden="true" />{statusLabels[status]}</span>;
}
