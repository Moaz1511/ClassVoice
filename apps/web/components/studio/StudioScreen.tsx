"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

const MAX_TEXT_LENGTH = 10_000;
const DRAFT_PREFIX = "classvoice.studio.draft.";

type SaveState = "idle" | "saving" | "saved" | "error";
type PendingAction = Readonly<{ kind: "navigate" | "clear"; href?: string }>;

type EditorSettings = Readonly<{
  voiceId: string;
  language: string;
  outputFormat: "wav" | "mp3";
  speed: number;
  stability: number;
  style: number;
}>;

const defaultSettings: EditorSettings = {
  voiceId: "",
  language: "en-US",
  outputFormat: "wav",
  speed: 1,
  stability: 0.5,
  style: 0.25,
};

function draftKey(projectId: string) {
  return `${DRAFT_PREFIX}${encodeURIComponent(projectId)}`;
}

function settingsEqual(left: EditorSettings, right: EditorSettings) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function StudioScreen({ projectId = "new" }: Readonly<{ projectId?: string }>) {
  const router = useRouter();
  const pathname = usePathname();
  const [projectName, setProjectName] = useState(projectId === "new" ? "Untitled lesson" : "Lesson project");
  const [text, setText] = useState("");
  const [settings, setSettings] = useState<EditorSettings>(defaultSettings);
  const [savedText, setSavedText] = useState("");
  const [savedName, setSavedName] = useState(projectId === "new" ? "Untitled lesson" : "Lesson project");
  const [savedSettings, setSavedSettings] = useState<EditorSettings>(defaultSettings);
  const [hydrated, setHydrated] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveMessage, setSaveMessage] = useState("");
  const [generateMessage, setGenerateMessage] = useState("");
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  const isDirty = hydrated && (text !== savedText || projectName !== savedName || !settingsEqual(settings, savedSettings));
  const characterCount = text.length;
  const exceedsLimit = characterCount > MAX_TEXT_LENGTH;
  const canGenerate = Boolean(text.trim()) && !exceedsLimit && Boolean(settings.voiceId) && saveState !== "saving";

  useEffect(() => {
    try {
      const draft = window.localStorage.getItem(draftKey(projectId));
      if (draft) {
        const parsed: unknown = JSON.parse(draft);
        if (typeof parsed === "object" && parsed !== null && "text" in parsed && typeof parsed.text === "string") setText(parsed.text);
      }
    } catch {
      setSaveMessage("The local draft could not be restored; you can continue without it.");
    } finally {
      setHydrated(true);
    }
  }, [projectId]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      if (text) window.localStorage.setItem(draftKey(projectId), JSON.stringify({ text, savedAt: new Date().toISOString() }));
      else window.localStorage.removeItem(draftKey(projectId));
    } catch {
      setSaveMessage("The browser could not save this local draft. Keep this tab open until you save or copy your text.");
    }
  }, [hydrated, projectId, text]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const interceptInternalNavigation = (event: MouseEvent) => {
      if (!isDirty || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (!(event.target instanceof Element)) return;
      const anchor = event.target.closest("a");
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const href = anchor.getAttribute("href");
      if (!href || !href.startsWith("/") || href === pathname || href.startsWith("/studio#")) return;
      event.preventDefault();
      event.stopPropagation();
      setPendingAction({ kind: "navigate", href });
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", interceptInternalNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", interceptInternalNavigation, true);
    };
  }, [isDirty, pathname]);

  const settingsSummary = useMemo(() => `${settings.language} · ${settings.outputFormat.toUpperCase()} · ${settings.speed.toFixed(2)}×`, [settings]);

  function saveLocally() {
    try {
      window.localStorage.setItem(`${DRAFT_PREFIX}metadata.${encodeURIComponent(projectId)}`, JSON.stringify({ projectName, settings, savedAt: new Date().toISOString() }));
      setSavedText(text);
      setSavedName(projectName);
      setSavedSettings(settings);
      setSaveState("saved");
      setSaveMessage("Project metadata and editor settings are saved locally; server sync is pending API client integration.");
    } catch {
      setSaveState("error");
      setSaveMessage("Project could not be saved in this browser. Check storage permissions and retry.");
    }
  }

  function saveProject() {
    if (!projectName.trim()) {
      setSaveState("error");
      setSaveMessage("Project name is required before saving.");
      return;
    }
    setSaveState("saving");
    window.setTimeout(saveLocally, 220);
  }

  function discardAndContinue() {
    if (pendingAction?.kind === "clear") {
      setText("");
      setPendingAction(null);
      return;
    }
    const href = pendingAction?.href;
    try { window.localStorage.removeItem(draftKey(projectId)); } catch { /* best-effort cleanup */ }
    setPendingAction(null);
    if (href) router.push(href);
  }

  function saveAndContinue() {
    saveLocally();
    if (pendingAction?.kind === "clear") setText("");
    const href = pendingAction?.href;
    setPendingAction(null);
    if (href) router.push(href);
  }

  function updateSettings(patch: Partial<EditorSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
    setSaveState("idle");
  }

  function handleGenerate() {
    if (!settings.voiceId) {
      setGenerateMessage("Select a Ready voice with active consent before generating. Revoked or not-ready voices cannot be selected.");
      return;
    }
    if (!text.trim()) {
      setGenerateMessage("Add lesson text before generating audio.");
      return;
    }
    if (exceedsLimit) {
      setGenerateMessage(`Shorten the lesson to ${MAX_TEXT_LENGTH.toLocaleString()} characters before generating.`);
      return;
    }
    setGenerateMessage("Generation handoff is ready; the authenticated generation client will be connected in the next queue step.");
  }

  return (
    <>
      <div className="breadcrumb" aria-label="Breadcrumb"><Link href="/dashboard">Dashboard</Link><span aria-hidden="true">/</span><span>Studio</span></div>
      <div className="page-heading studio-heading"><div><p className="eyebrow">Academic voice studio</p><h1>{projectId === "new" ? "New lesson" : projectName}</h1><p>Draft text stays in this browser until you explicitly generate; saved settings never include raw text.</p></div><div className="studio-heading-actions"><span className={`draft-indicator${isDirty ? " dirty" : ""}`} role="status"><span className="status-dot" />{isDirty ? "Unsaved changes" : "Saved"}</span><button className="button button-primary" type="button" onClick={saveProject} disabled={saveState === "saving"}>{saveState === "saving" ? "Saving…" : "Save project"}</button></div></div>

      <div className="studio-layout">
        <section className="card studio-editor-card" aria-labelledby="editor-heading">
          <div className="studio-card-header"><div><div className="card-kicker">Editor</div><h2 id="editor-heading">Lesson content</h2></div><span className={`character-count${exceedsLimit ? " over-limit" : ""}`}>{characterCount.toLocaleString()} / {MAX_TEXT_LENGTH.toLocaleString()}</span></div>
          <div className="field studio-project-name"><label htmlFor="project-name">Project name</label><input id="project-name" value={projectName} maxLength={160} onChange={(event) => { setProjectName(event.target.value); setSaveState("idle"); }} /></div>
          <div className="field"><label htmlFor="lesson-text">Lesson text</label><textarea id="lesson-text" value={text} maxLength={MAX_TEXT_LENGTH + 500} onChange={(event) => { setText(event.target.value); setSaveState("idle"); setGenerateMessage(""); }} placeholder="Write or paste the lesson text you want your teacher voice to narrate…" rows={17} aria-describedby="lesson-text-help" /></div>
          <div className="editor-footer"><span id="lesson-text-help" className="field-hint">Text is retained only in this browser draft until you generate.</span><button className="button button-secondary" type="button" onClick={() => isDirty ? setPendingAction({ kind: "clear" }) : setText("")} disabled={!text}>Clear</button></div>
          {exceedsLimit ? <div className="form-error" role="alert">This text exceeds the 10,000-character generation limit.</div> : null}
          {generateMessage ? <div className="notice" role="status">{generateMessage}</div> : null}
          {saveMessage ? <div className={saveState === "error" ? "form-error" : "form-success"} role="status">{saveMessage}</div> : null}
          <div className="studio-generate-row"><span className="muted">{settingsSummary}</span><button className="button button-primary" type="button" disabled={!canGenerate} onClick={handleGenerate}>Generate audio <span aria-hidden="true">→</span></button></div>
        </section>

        <aside className="studio-sidebar">
          <section className="card studio-settings-card" aria-labelledby="settings-heading"><div className="card-kicker">Saved editor settings</div><h2 id="settings-heading">Generation settings</h2><div className="field"><label htmlFor="studio-voice">Voice</label><select id="studio-voice" value={settings.voiceId} onChange={(event) => updateSettings({ voiceId: event.target.value })}><option value="">Choose a Ready voice</option><option value="__none" disabled>No ready voices available</option></select><span className="field-hint">Revoked, archived, and processing voices are excluded.</span></div><div className="field"><label htmlFor="studio-language">Language</label><select id="studio-language" value={settings.language} onChange={(event) => updateSettings({ language: event.target.value })}><option value="en-US">English (US)</option><option value="en-GB">English (UK)</option><option value="bn-BD">বাংলা (BD)</option></select></div><div className="field"><label htmlFor="studio-format">Output format</label><select id="studio-format" value={settings.outputFormat} onChange={(event) => updateSettings({ outputFormat: event.target.value as "wav" | "mp3" })}><option value="wav">WAV · lossless</option><option value="mp3">MP3 · compact</option></select></div><div className="field range-field"><label htmlFor="studio-speed">Speed <output>{settings.speed.toFixed(2)}×</output></label><input id="studio-speed" type="range" min="0.5" max="2" step="0.05" value={settings.speed} onChange={(event) => updateSettings({ speed: Number(event.target.value) })} /></div><div className="field range-field"><label htmlFor="studio-stability">Stability <output>{Math.round(settings.stability * 100)}%</output></label><input id="studio-stability" type="range" min="0" max="1" step="0.05" value={settings.stability} onChange={(event) => updateSettings({ stability: Number(event.target.value) })} /></div><div className="field range-field"><label htmlFor="studio-style">Style <output>{Math.round(settings.style * 100)}%</output></label><input id="studio-style" type="range" min="0" max="1" step="0.05" value={settings.style} onChange={(event) => updateSettings({ style: Number(event.target.value) })} /></div></section>
          <section className="card studio-output-card" aria-labelledby="output-heading"><div className="card-kicker">Output rail</div><h2 id="output-heading">No generation yet</h2><p className="muted">Generation states and audio playback will appear here after the queue integration is enabled.</p><div className="output-state"><span className="state-icon" aria-hidden="true">▶</span><span>Ready when a consented voice is selected</span></div></section>
        </aside>
      </div>

      {pendingAction ? <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="unsaved-dialog-title"><div className="modal-header"><div><p className="eyebrow">Unsaved draft</p><h2 id="unsaved-dialog-title">{pendingAction.kind === "clear" ? "Clear this lesson text?" : "Leave Studio?"}</h2></div><button className="icon-button" type="button" aria-label="Stay in Studio" onClick={() => setPendingAction(null)}>×</button></div><div className="modal-body"><p>{pendingAction.kind === "clear" ? "Your draft text has not been sent to the server. Choose whether to save project settings before clearing it." : "Your draft text has not been sent to the server. Choose whether to save project settings before leaving."}</p></div><div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setPendingAction(null)}>Stay</button><button className="button button-secondary" type="button" onClick={discardAndContinue}>Discard</button><button className="button button-primary" type="button" onClick={saveAndContinue}>Save project</button></div></section></div> : null}
    </>
  );
}
