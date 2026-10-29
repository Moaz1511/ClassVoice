"use client";

import { useState } from "react";

export function ProfileSettingsScreen() {
  const [displayName, setDisplayName] = useState("Moaz");
  const [locale, setLocale] = useState("en-US");
  const [theme, setTheme] = useState("system");
  const [saveMessage, setSaveMessage] = useState("");
  const [exportOpen, setExportOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deletePhrase, setDeletePhrase] = useState("");
  const [deleteAcknowledged, setDeleteAcknowledged] = useState(false);

  function saveProfile() {
    setSaveMessage("Profile save handoff is ready; no mutation was sent from this placeholder screen.");
  }
  function requestExport() {
    setExportOpen(false);
    setSaveMessage("Export request handoff is ready; the server will create an asynchronous export and notify you when it is ready.");
  }
  const canDelete = deletePassword.length >= 12 && deletePhrase === "DELETE MY ACCOUNT" && deleteAcknowledged;

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Account</p><h1>Profile settings</h1><p>Manage your account identity, locale, appearance, and data controls.</p></div></div>
      {saveMessage ? <div className="notice" role="status">{saveMessage}</div> : null}
      <div className="settings-grid">
        <section className="card" aria-labelledby="profile-heading"><div className="card-kicker">Personal details</div><h2 id="profile-heading">Profile</h2><div className="settings-form"><div className="field"><label htmlFor="profile-name">Display name</label><input id="profile-name" value={displayName} maxLength={120} onChange={(event) => setDisplayName(event.target.value)} /></div><div className="field"><label htmlFor="profile-email">Email</label><input id="profile-email" value="moaz@example.edu" readOnly /><span className="verified-label"><span className="status-dot" />Verified email</span></div><div className="field"><label htmlFor="profile-locale">Locale</label><select id="profile-locale" value={locale} onChange={(event) => setLocale(event.target.value)}><option value="en-US">English (US)</option><option value="en-GB">English (UK)</option><option value="bn-BD">বাংলা (BD)</option></select></div><div className="field"><label htmlFor="profile-theme">Theme</label><select id="profile-theme" value={theme} onChange={(event) => setTheme(event.target.value)}><option value="system">System preference</option><option value="light">Light</option><option value="dark">Dark</option></select></div><button className="button button-primary" type="button" onClick={saveProfile}>Save profile</button></div></section>
        <section className="card" aria-labelledby="export-heading"><div className="card-kicker">Privacy controls</div><h2 id="export-heading">Your data</h2><p className="muted">Exports include account/workspace metadata, consent receipts, and audit records you are authorized to access. Private audio remains protected by storage policy.</p><div className="action-column"><button className="button button-secondary" type="button" onClick={() => setExportOpen(true)}>Export my data</button><button className="button button-danger" type="button" onClick={() => setDeleteOpen(true)}>Delete account</button></div></section>
      </div>

      {exportOpen ? <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="export-dialog-title"><div className="modal-header"><div><p className="eyebrow">Asynchronous export</p><h2 id="export-dialog-title">Export your data?</h2></div><button className="icon-button" type="button" aria-label="Close export dialog" onClick={() => setExportOpen(false)}>×</button></div><div className="modal-body"><p>The server will create an export job and send a notification when the private archive is ready. The archive link will be short-lived and authorization-checked.</p></div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setExportOpen(false)}>Cancel</button><button className="button button-primary" type="button" onClick={requestExport}>Request export</button></div></section></div> : null}
      {deleteOpen ? <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-account-title"><div className="modal-header"><div><p className="eyebrow">Irreversible account action</p><h2 id="delete-account-title">Delete account?</h2></div><button className="icon-button" type="button" aria-label="Close delete account dialog" onClick={() => setDeleteOpen(false)}>×</button></div><div className="modal-body"><p>Deletion requires recent password re-authentication, queues workspace and asset cascade cleanup, and may not be reversible.</p><ul className="safety-list"><li>Profile, sessions, memberships, and owned workspace access</li><li>Voice profiles, consent records, samples, projects, generation jobs, and outputs</li><li>API keys, webhook endpoints, and deliveries; append-only audit evidence is retained or redacted by policy</li></ul><div className="field"><label htmlFor="delete-password">Re-enter password</label><input id="delete-password" type="password" value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} autoComplete="current-password" /></div><div className="field"><label htmlFor="delete-phrase">Type DELETE MY ACCOUNT</label><input id="delete-phrase" value={deletePhrase} onChange={(event) => setDeletePhrase(event.target.value)} /></div><label className="checkbox-field"><input type="checkbox" checked={deleteAcknowledged} onChange={(event) => setDeleteAcknowledged(event.target.checked)} /><span>I understand the complete cascade listed above and that private audio cleanup is asynchronous.</span></label></div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setDeleteOpen(false)}>Cancel</button><button className="button button-danger" type="button" disabled={!canDelete} onClick={() => { setDeleteOpen(false); setSaveMessage("Deletion handoff is ready; no account mutation was sent from this placeholder screen."); }}>Delete account</button></div></section></div> : null}
    </>
  );
}
