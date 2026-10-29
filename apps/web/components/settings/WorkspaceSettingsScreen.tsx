"use client";

import { useState } from "react";
import { EmptyState } from "../ui/PageState";

export function WorkspaceSettingsScreen() {
  const [workspaceName, setWorkspaceName] = useState("My workspace");
  const [retention, setRetention] = useState("90");
  const [message, setMessage] = useState("");

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Administration</p><h1>Workspace settings</h1><p>Manage workspace identity, members, roles, and retention defaults.</p></div></div>
      {message ? <div className="notice" role="status">{message}</div> : null}
      <div className="settings-grid"><section className="card" aria-labelledby="workspace-heading"><div className="card-kicker">Workspace identity</div><h2 id="workspace-heading">Workspace defaults</h2><div className="settings-form"><div className="field"><label htmlFor="workspace-name">Workspace name</label><input id="workspace-name" value={workspaceName} maxLength={120} onChange={(event) => setWorkspaceName(event.target.value)} /></div><div className="field"><label htmlFor="workspace-retention">Output retention</label><select id="workspace-retention" value={retention} onChange={(event) => setRetention(event.target.value)}><option value="30">30 days</option><option value="90">90 days</option><option value="365">365 days</option><option value="indefinite">Indefinite (policy permitting)</option></select><span className="field-hint">Retention never overrides consent revocation or deletion requests.</span></div><button className="button button-primary" type="button" onClick={() => setMessage("Workspace settings save handoff is ready; no mutation was sent from this placeholder screen.")}>Save workspace settings</button></div></section><section className="card" aria-labelledby="members-heading"><div className="card-kicker">Access control</div><h2 id="members-heading">Members and roles</h2><EmptyState title="No member directory loaded" description="Workspace owners and admins will manage invitations, roles, and disabled memberships here after the workspace API is connected." /></section></div>
    </>
  );
}
