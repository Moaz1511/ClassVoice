import Link from "next/link";
import { EmptyState } from "./PageState";

type PlaceholderCopy = Readonly<{
  title: string;
  description: string;
  emptyTitle: string;
  emptyDescription: string;
  action?: Readonly<{ href: string; label: string }>;
}>;

const routeCopy: Record<string, PlaceholderCopy> = {
  voices: {
    title: "Voice profiles",
    description: "Create and manage consented teacher voice profiles for your academic content.",
    emptyTitle: "No voice profiles yet",
    emptyDescription: "A verified consent record and a clean reference sample are required before a voice can be used for generation.",
    action: { href: "/voices/new", label: "Create a voice profile" },
  },
  studio: {
    title: "Studio",
    description: "Prepare lesson text, choose a voice, and review generation settings before submitting audio.",
    emptyTitle: "Studio is ready for your first lesson",
    emptyDescription: "The editor and generation controls will appear here when the project API is connected.",
    action: { href: "/voices/new", label: "Start with a voice profile" },
  },
  generations: {
    title: "Generations",
    description: "Track queued, completed, and failed audio jobs in this workspace.",
    emptyTitle: "No generations yet",
    emptyDescription: "Completed audio and safe retry controls will appear here after your first studio run.",
    action: { href: "/studio", label: "Open studio" },
  },
  "api-keys": {
    title: "API keys",
    description: "Manage scoped machine credentials for approved ClassVoice agent integrations.",
    emptyTitle: "No API keys issued",
    emptyDescription: "Keys are shown once at creation and never expose their secret again. The API key manager is not connected yet.",
    action: { href: "/docs/api", label: "Read API guidance" },
  },
  webhooks: {
    title: "Webhooks",
    description: "Deliver signed generation events to trusted HTTPS endpoints.",
    emptyTitle: "No webhook endpoints",
    emptyDescription: "Endpoint verification, replay protection, and delivery history will appear here after integration wiring.",
    action: { href: "/docs/api", label: "Read API guidance" },
  },
  "admin/reports": {
    title: "Safety reports",
    description: "Review moderation reports and resolve safety issues with an auditable decision.",
    emptyTitle: "No reports to review",
    emptyDescription: "New reports will be queued here for authorized moderators. This view contains no live report data yet.",
  },
  "admin/audit": {
    title: "Audit log",
    description: "Inspect immutable workspace activity with request correlation and redacted metadata.",
    emptyTitle: "No activity to show",
    emptyDescription: "Workspace events will appear here when the audit API is connected. Secrets and raw audio are never displayed.",
  },
  "settings/profile": {
    title: "Profile settings",
    description: "Update your display name, email verification, and sign-in preferences.",
    emptyTitle: "Profile settings are coming next",
    emptyDescription: "Your account is protected. Profile mutations will be connected after the web API client integration.",
  },
  "settings/workspace": {
    title: "Workspace settings",
    description: "Manage members, roles, and workspace-level defaults.",
    emptyTitle: "Workspace settings are coming next",
    emptyDescription: "Membership and role controls will be available to workspace owners and administrators.",
  },
  "settings/safety": {
    title: "Safety settings",
    description: "Review consent, retention, and generation safety defaults.",
    emptyTitle: "Safety controls are coming next",
    emptyDescription: "Safety defaults will be loaded from the API before any generation can be submitted.",
  },
  "docs/api": {
    title: "API documentation",
    description: "Build a safe agent integration with the typed ClassVoice API contract.",
    emptyTitle: "API reference is being prepared",
    emptyDescription: "The checked-in OpenAPI contract is ready for client generation; interactive documentation will be mounted here next.",
    action: { href: "/api-keys", label: "Manage API keys" },
  },
};

function copyForRoute(route: string): PlaceholderCopy {
  const root = route.split("/")[0] ?? route;
  return routeCopy[route] ?? routeCopy[root] ?? {
    title: "Workspace view",
    description: "This authenticated workspace route is reserved for the next integration slice.",
    emptyTitle: "This view is ready for integration",
    emptyDescription: "No private data is loaded until the authenticated API client is connected.",
    action: { href: "/dashboard", label: "Return to dashboard" },
  };
}

export function PlaceholderPage({ route }: Readonly<{ route: string }>) {
  const copy = copyForRoute(route);
  return (
    <>
      <div className="breadcrumb" aria-label="Breadcrumb">
        <Link href="/dashboard">Dashboard</Link><span aria-hidden="true">/</span><span>{copy.title}</span>
      </div>
      <div className="page-heading">
        <div><h1>{copy.title}</h1><p>{copy.description}</p></div>
      </div>
      <section className="card placeholder-card" aria-labelledby="placeholder-heading">
        <EmptyState title={copy.emptyTitle} description={copy.emptyDescription} action={copy.action} />
      </section>
      <p className="implementation-note">Placeholder state · Authenticated shell only · No private data loaded</p>
    </>
  );
}
