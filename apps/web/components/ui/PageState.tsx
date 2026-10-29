import Link from "next/link";

type StateAction = Readonly<{
  href: string;
  label: string;
}>;

export function LoadingState({ label = "Loading…" }: Readonly<{ label?: string }>) {
  return (
    <div className="page-state" aria-live="polite" aria-busy="true">
      <div className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: Readonly<{
  title: string;
  description: string;
  action?: StateAction;
}>) {
  return (
    <div className="page-state" role="status">
      <span className="state-icon" aria-hidden="true">✦</span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action ? <Link className="button button-secondary" href={action.href}>{action.label}</Link> : null}
    </div>
  );
}

export function ErrorState({
  title = "We couldn’t load this workspace view",
  description = "Try again in a moment. If this keeps happening, share the request ID with your workspace administrator.",
  requestId,
}: Readonly<{
  title?: string;
  description?: string;
  requestId?: string;
}>) {
  return (
    <div className="page-state page-state-error" role="alert">
      <span className="state-icon" aria-hidden="true">!</span>
      <h3>{title}</h3>
      <p>{description}</p>
      {requestId ? <code className="request-id">Request ID: {requestId}</code> : null}
      <Link className="button button-secondary" href="/dashboard">Return to dashboard</Link>
    </div>
  );
}
