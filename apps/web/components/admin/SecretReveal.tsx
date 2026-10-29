"use client";

import { useState } from "react";

export function SecretReveal({
  kind,
  secret,
  warning = "Copy this secret now. It cannot be shown again.",
  onDismiss,
}: Readonly<{
  kind: "API key" | "webhook signing secret";
  secret: string | null;
  warning?: string;
  onDismiss: () => void;
}>) {
  const [copied, setCopied] = useState(false);

  if (!secret) return null;
  const secretValue = secret;

  async function copySecret() {
    try {
      await navigator.clipboard.writeText(secretValue);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="secret-reveal" role="alert" aria-live="assertive">
      <div><div className="card-kicker">One-time {kind}</div><h3>Copy this secret before closing</h3><p>{warning}</p></div>
      <code className="secret-value">{secretValue}</code>
      <div className="secret-actions"><button className="button button-secondary" type="button" onClick={copySecret}>{copied ? "Copied" : "Copy secret"}</button><button className="button button-primary" type="button" onClick={onDismiss}>I copied it</button></div>
    </div>
  );
}
