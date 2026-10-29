"use client";

import { useState } from "react";

export function WorkspaceSwitcher() {
  const [open, setOpen] = useState(false);

  return (
    <div className="workspace-switcher">
      <button
        className="workspace-switcher-trigger"
        type="button"
        aria-expanded={open}
        aria-controls="workspace-switcher-panel"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="workspace-switcher-mark" aria-hidden="true">MW</span>
        <span className="workspace-switcher-copy">
          <span className="workspace-switcher-label">Workspace</span>
          <strong>My workspace</strong>
        </span>
        <span className="workspace-switcher-chevron" aria-hidden="true">⌄</span>
      </button>
      {open ? (
        <div className="workspace-switcher-panel" id="workspace-switcher-panel" role="status">
          <strong>Workspace switching is coming soon</strong>
          <p>Your personal workspace is active. Additional workspaces will appear here after the workspace API is connected.</p>
        </div>
      ) : null}
    </div>
  );
}
