"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../ui/PageState";
import { VoiceStatusBadge } from "./VoiceStatusBadge";

type VoiceStatus = "draft" | "validating" | "processing" | "ready" | "rejected" | "revoked" | "archived";
type LoadState = "loading" | "ready" | "error";

type VoiceRow = Readonly<{
  id: string;
  name: string;
  languageCode: string;
  status: VoiceStatus;
  consentStatus: "accepted" | "revoked" | "expired";
  updatedAt: string;
}>;

const voices: VoiceRow[] = [];

const statusOptions: ReadonlyArray<{ value: "all" | VoiceStatus; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "ready", label: "Ready" },
  { value: "draft", label: "Draft" },
  { value: "validating", label: "Validating" },
  { value: "processing", label: "Processing" },
  { value: "rejected", label: "Needs attention" },
  { value: "revoked", label: "Consent revoked" },
  { value: "archived", label: "Archived" },
];

export function VoiceListScreen() {
  const [loadState, setLoadState] = useState<LoadState>("ready");
  const [status, setStatus] = useState<"all" | VoiceStatus>("all");
  const [language, setLanguage] = useState("all");
  const [owner, setOwner] = useState("all");
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const filteredVoices = useMemo(() => voices.filter((voice) => {
    if (!includeArchived && voice.status === "archived") return false;
    if (status !== "all" && voice.status !== status) return false;
    if (language !== "all" && voice.languageCode !== language) return false;
    if (search.trim() && !voice.name.toLowerCase().includes(search.trim().toLowerCase())) return false;
    return true;
  }), [includeArchived, language, search, status]);

  function retry() {
    setLoadState("loading");
    window.setTimeout(() => setLoadState("ready"), 250);
  }

  const hasFilters = status !== "all" || language !== "all" || owner !== "all" || Boolean(search.trim()) || includeArchived;
  function clearFilters() {
    setStatus("all");
    setLanguage("all");
    setOwner("all");
    setSearch("");
    setIncludeArchived(false);
  }

  return (
    <>
      <div className="page-heading">
        <div><p className="eyebrow">Consent and quality</p><h1>Voice profiles</h1><p>Manage teacher voices that are approved for academic generation.</p></div>
        <Link className="button button-primary" href="/voices/new">Create voice <span aria-hidden="true">→</span></Link>
      </div>

      <section className="card voice-filter-card" aria-label="Voice profile filters">
        <div className="filter-toolbar">
          <div className="field filter-search"><label htmlFor="voice-search">Search voices</label><input id="voice-search" type="search" placeholder="Search by name" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
          <div className="field"><label htmlFor="voice-status">Status</label><select id="voice-status" value={status} onChange={(event) => setStatus(event.target.value as "all" | VoiceStatus)}>{statusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>
          <div className="field"><label htmlFor="voice-language">Language</label><select id="voice-language" value={language} onChange={(event) => setLanguage(event.target.value)}><option value="all">All languages</option><option value="en-US">English (US)</option><option value="en-GB">English (UK)</option><option value="bn-BD">বাংলা (BD)</option></select></div>
          <div className="field"><label htmlFor="voice-owner">Owner</label><select id="voice-owner" value={owner} onChange={(event) => setOwner(event.target.value)}><option value="all">Everyone</option><option value="me">Created by me</option></select></div>
        </div>
        <label className="checkbox-field filter-checkbox"><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} /><span>Include archived voices</span></label>
      </section>

      {loadState === "loading" ? <section className="card"><LoadingState label="Loading voice profiles…" /></section> : null}
      {loadState === "error" ? <section className="card"><ErrorState title="Voice profiles could not be loaded" description="Your filters are preserved. Retry the request or return to the dashboard." /></section> : null}
      {loadState === "ready" && filteredVoices.length === 0 ? (
        <section className="card voice-empty-card">
          <EmptyState
            title={hasFilters ? "No voices match these filters" : "No voice profiles yet"}
            description={hasFilters ? "Clear one or more filters to see other workspace voices." : "A consented reference sample is required before a teacher voice can be used for generation."}
            action={hasFilters ? undefined : { href: "/voices/new", label: "Create a voice profile" }}
          />
          {hasFilters ? <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button> : null}
        </section>
      ) : null}
      {loadState === "ready" && filteredVoices.length > 0 ? (
        <section className="card voice-table-card" aria-label="Voice profiles table">
          <div className="voice-table-header"><h2>{filteredVoices.length} voice profile{filteredVoices.length === 1 ? "" : "s"}</h2><button className="button button-secondary" type="button" onClick={retry}>Refresh</button></div>
          <div className="voice-table" role="table">
            {filteredVoices.map((voice) => <Link className="voice-row" href={`/voices/${voice.id}`} key={voice.id} role="row"><span><strong>{voice.name}</strong><small>{voice.languageCode} · Updated {voice.updatedAt}</small></span><VoiceStatusBadge status={voice.status} /><span aria-hidden="true">→</span></Link>)}
          </div>
        </section>
      ) : null}
      <div className="voice-list-footer"><span className="status-dot" aria-hidden="true" />{loadState === "error" ? "Last request failed; no cached private data is shown." : "Voice data is scoped to the active workspace and loaded only after authentication."}</div>
    </>
  );
}
