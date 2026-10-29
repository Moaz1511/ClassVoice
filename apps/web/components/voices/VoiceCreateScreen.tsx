"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

type CreateStage = "consent_unread" | "consent_accepted" | "sample_selected" | "uploading" | "validating" | "processing" | "ready" | "sample_invalid" | "error";

const MAX_FILE_SIZE = 25_000_000;
const allowedExtensions = ["wav", "mp3", "m4a"];

function extensionFor(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

export function VoiceCreateScreen() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [stage, setStage] = useState<CreateStage>("consent_unread");
  const [consentModalOpen, setConsentModalOpen] = useState(false);
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [file, setFile] = useState<File | null>(null);
  const [validationMessage, setValidationMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (stage !== "uploading") return undefined;
    const timeout = window.setTimeout(() => {
      setStage("error");
      setErrorMessage("Secure upload is not connected in this build. No audio file was sent or stored. Retry after the authenticated upload client is enabled.");
    }, 650);
    return () => window.clearTimeout(timeout);
  }, [stage]);

  function acceptConsent() {
    setConsentAccepted(true);
    setStage("consent_accepted");
    setConsentModalOpen(false);
  }

  function selectFile(nextFile: File | undefined) {
    if (!nextFile) return;
    const extension = extensionFor(nextFile);
    if (!allowedExtensions.includes(extension)) {
      setFile(null);
      setStage("sample_invalid");
      setValidationMessage("Unsupported format. Choose a WAV, MP3, or M4A file.");
      return;
    }
    if (nextFile.size > MAX_FILE_SIZE) {
      setFile(null);
      setStage("sample_invalid");
      setValidationMessage("This file is larger than 25 MB. Choose a shorter reference sample.");
      return;
    }
    setFile(nextFile);
    setValidationMessage("The server will check duration (6–30 seconds), silence, clipping, channels, and speaker consistency.");
    setErrorMessage("");
    setStage("sample_selected");
  }

  function startUpload() {
    if (!consentAccepted) {
      setErrorMessage("Read and acknowledge the consent statement before uploading a sample.");
      setStage("consent_unread");
      return;
    }
    if (!file) {
      setErrorMessage("Choose a reference sample before starting the secure upload.");
      setStage("sample_invalid");
      return;
    }
    if (!name.trim()) {
      setErrorMessage("Add a voice name before starting the secure upload.");
      return;
    }
    setErrorMessage("");
    setStage("uploading");
  }

  function replaceSample() {
    setFile(null);
    setValidationMessage("");
    setErrorMessage("");
    setStage(consentAccepted ? "consent_accepted" : "consent_unread");
    inputRef.current?.click();
  }

  const uploadDisabled = stage === "uploading" || stage === "validating" || stage === "processing" || stage === "ready";
  const progressStage = stage === "uploading" || stage === "validating" || stage === "processing";

  return (
    <>
      <div className="breadcrumb" aria-label="Breadcrumb"><Link href="/voices">Voice profiles</Link><span aria-hidden="true">/</span><span>Create voice</span></div>
      <div className="page-heading"><div><p className="eyebrow">Consent-first setup</p><h1>Create a voice profile</h1><p>Verify permission, provide one clean reference sample, and let the server validate it before processing.</p></div></div>

      <div className="voice-create-layout">
        <section className="card voice-create-main" aria-labelledby="voice-details-heading">
          <div className="step-heading"><span className="step-number">1</span><div><h2 id="voice-details-heading">Voice details</h2><p className="muted">These labels are workspace metadata and never change the source audio.</p></div></div>
          <div className="form-grid-two">
            <div className="field"><label htmlFor="voice-name">Voice name</label><input id="voice-name" value={name} maxLength={120} placeholder="e.g. Professor Rahman" onChange={(event) => setName(event.target.value)} /><span className="field-hint">1–120 visible characters</span></div>
            <div className="field"><label htmlFor="voice-language">Primary language</label><select id="voice-language" value={language} onChange={(event) => setLanguage(event.target.value)}><option value="en-US">English (US)</option><option value="en-GB">English (UK)</option><option value="bn-BD">বাংলা (BD)</option></select></div>
          </div>

          <div className="step-heading step-heading-spaced"><span className="step-number">2</span><div><h2>Consent and permission</h2><p className="muted">Consent is recorded with a statement version and SHA-256 attestation hash.</p></div></div>
          <div className={`consent-panel${consentAccepted ? " accepted" : ""}`}>
            <div><strong>{consentAccepted ? "Consent statement acknowledged" : "Permission is required"}</strong><p>{consentAccepted ? "The consent receipt will be attached to the voice profile when the API is connected." : "You must confirm that you own this voice or have permission to use it."}</p></div>
            <button className="button button-secondary" type="button" onClick={() => setConsentModalOpen(true)}>{consentAccepted ? "Review statement" : "View consent statement"}</button>
          </div>
          <label className="checkbox-field consent-checkbox"><input type="checkbox" checked={consentAccepted} onChange={(event) => { setConsentAccepted(event.target.checked); setStage(event.target.checked ? "consent_accepted" : "consent_unread"); }} /><span>I own this voice or have permission from the speaker to create and use this profile for academic content.</span></label>

          <div className="step-heading step-heading-spaced"><span className="step-number">3</span><div><h2>Reference sample</h2><p className="muted">Use one speaker, clear speech, and a quiet room. Maximum file size is 25 MB.</p></div></div>
          <button className={`dropzone${file ? " has-file" : ""}`} type="button" onClick={() => inputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); selectFile(event.dataTransfer.files[0]); }} aria-label="Choose an audio reference sample">
            <span className="dropzone-icon" aria-hidden="true">↑</span>
            <strong>{file ? file.name : "Choose or drop an audio file"}</strong>
            <span>{file ? `${Math.ceil(file.size / 1024)} KB selected` : "WAV, MP3, or M4A · 6–30 seconds recommended"}</span>
          </button>
          <input ref={inputRef} className="sr-only" type="file" accept="audio/wav,audio/x-wav,audio/mpeg,audio/mp4,.wav,.mp3,.m4a" onChange={(event) => selectFile(event.target.files?.[0])} />
          {validationMessage ? <p className="validation-note" role="status">{validationMessage}</p> : null}
          {stage === "sample_invalid" ? <div className="form-error" role="alert">{validationMessage || "This sample needs attention. Choose another file."}<button className="inline-action" type="button" onClick={replaceSample}>Replace sample</button></div> : null}
          {errorMessage ? <div className="form-error" role="alert">{errorMessage}</div> : null}

          <div className="action-row voice-create-actions"><Link className="button button-secondary" href="/voices">Cancel</Link><button className="button button-primary" type="button" disabled={uploadDisabled} onClick={startUpload}>{progressStage ? "Validating sample…" : "Start secure upload"} <span aria-hidden="true">→</span></button></div>
          {stage === "error" ? <button className="button button-secondary" type="button" onClick={() => setStage(file ? "sample_selected" : "consent_accepted")}>Retry setup</button> : null}
        </section>

        <aside className="card voice-create-aside" aria-labelledby="validation-heading"><div className="card-kicker">Server validation</div><h2 id="validation-heading">What happens next</h2><ol className="validation-list"><li className={stage === "uploading" ? "active" : ""}><strong>Secure upload</strong><span>Private quarantine storage with an idempotency key.</span></li><li className={stage === "validating" || stage === "processing" ? "active" : ""}><strong>Audio checks</strong><span>Magic bytes, duration, silence, clipping, channels, and speaker warnings.</span></li><li className={stage === "ready" ? "active" : ""}><strong>Ready gate</strong><span>Consent, sample, and approved model evidence must all be present.</span></li></ol><p className="notice">No embeddings, raw storage keys, or audio bytes are displayed in this interface.</p></aside>
      </div>

      {consentModalOpen ? <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="consent-dialog-title"><div className="modal-header"><div><p className="eyebrow">Consent statement · v1</p><h2 id="consent-dialog-title">Permission to create a voice profile</h2></div><button className="icon-button" type="button" aria-label="Close consent statement" onClick={() => setConsentModalOpen(false)}>×</button></div><div className="modal-body"><p>I confirm that I am the speaker or have the speaker’s permission to create and use this voice profile for lawful educational content. I understand that consent can be revoked, which immediately blocks new generation jobs.</p><p className="muted">The API records the statement version, text hash, accepting actor, and timestamp. This screen does not upload audio until the consent checkbox is accepted.</p></div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setConsentModalOpen(false)}>Not now</button><button className="button button-primary" type="button" onClick={acceptConsent}>I understand &amp; acknowledge</button></div></section></div> : null}
    </>
  );
}
