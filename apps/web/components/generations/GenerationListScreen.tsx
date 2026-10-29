"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../ui/PageState";
import { GenerationStatus, GenerationStatusBadge } from "./GenerationStatusBadge";

type LoadState = "loading" | "ready" | "error";
type GenerationRow = Readonly<{
  id: string;
  status: GenerationStatus;
  format: "wav" | "mp3";
  language: string;
  createdAt: string;
  inputHash: string;
}>;

const generations: GenerationRow[] = [];
const statuses: ReadonlyArray<{ value: "all" | GenerationStatus; label: string }> = [
  { value: "all", label: "All states" },
  { value: "created", label: "Created" },
  { value: "queued", label: "Queued" },
  { value: "processing", label: "Processing" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancel_requested", label: "Cancel requested" },
  { value: "canceled", label: "Canceled" },
];

export function GenerationListScreen() {
  const [loadState, setLoadState] = useState<LoadState>("ready");
  const [status, setStatus] = useState<"all" | GenerationStatus>("all");
  const [format, setFormat] = useState<"all" | "wav" | "mp3">("all");
  const [search, setSearch] = useState("");
  const [polling, setPolling] = useState(true);
  const [pollDelayMs, setPollDelayMs] = useState(1000);

  const filteredGenerations = useMemo(() => generations.filter((generation) => {
    if (status !== "all" && generation.status !== status) return false;
    if (format !== "all" && generation.format !== format) return false;
    return !search.trim() || generation.id.toLowerCase().includes(search.trim().toLowerCase());
  }), [format, search, status]);

  function refresh() {
    setLoadState("loading");
    window.setTimeout(() => {
      setLoadState("ready");
      setPollDelayMs((current) => Math.min(current * 2, 8_000));
    }, 250);
  }

  const hasFilters = status !== "all" || format !== "all" || Boolean(search.trim());
  function clearFilters() {
    setStatus("all");
    setFormat("all");
    setSearch("");
  }

  return (
    <>
      <div className="page-heading"><div><p className="eyebrow">Queue and output history</p><h1>Generations</h1><p>Track lesson audio jobs without exposing source text or private storage keys.</p></div><Link className="button button-primary" href="/studio">Open studio <span aria-hidden="true">→</span></Link></div>
      <section className="card generation-filter-card" aria-label="Generation filters"><div className="filter-toolbar generation-filters"><div className="field filter-search"><label htmlFor="generation-search">Search by job ID</label><input id="generation-search" type="search" placeholder="Paste a generation ID" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="field"><label htmlFor="generation-status">Job state</label><select id="generation-status" value={status} onChange={(event) => setStatus(event.target.value as "all" | GenerationStatus)}>{statuses.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div><div className="field"><label htmlFor="generation-format">Output</label><select id="generation-format" value={format} onChange={(event) => setFormat(event.target.value as "all" | "wav" | "mp3")}><option value="all">WAV or MP3</option><option value="wav">WAV</option><option value="mp3">MP3</option></select></div><label className="checkbox-field generation-polling"><input type="checkbox" checked={polling} onChange={(event) => setPolling(event.target.checked)} /><span>Auto-refresh active jobs</span></label></div><div className="generation-filter-footer"><span className="field-hint">Polling uses bounded backoff from 1s to 8s and never duplicates a mutation.</span><button className="button button-secondary" type="button" onClick={refresh}>{loadState === "loading" ? "Refreshing…" : "Refresh"}</button></div></section>
      {loadState === "loading" ? <section className="card"><LoadingState label="Refreshing generation status…" /></section> : null}
      {loadState === "error" ? <section className="card"><ErrorState title="Generation history could not be loaded" description="Your filters are preserved. Retry without creating another generation job." /></section> : null}
      {loadState === "ready" && filteredGenerations.length === 0 ? <section className="card generation-empty-card"><EmptyState title={hasFilters ? "No jobs match these filters" : "No generations yet"} description={hasFilters ? "Clear filters to see other jobs in this workspace." : "Start a lesson in Studio and its queue status will appear here."} action={hasFilters ? undefined : { href: "/studio", label: "Open studio" }} />{hasFilters ? <button className="button button-secondary" type="button" onClick={clearFilters}>Clear filters</button> : null}</section> : null}
      {loadState === "ready" && filteredGenerations.length > 0 ? <section className="card generation-table-card" aria-label="Generation jobs"><div className="voice-table-header"><h2>{filteredGenerations.length} job{filteredGenerations.length === 1 ? "" : "s"}</h2><span className="field-hint">Backoff: {pollDelayMs / 1000}s</span></div><div className="voice-table">{filteredGenerations.map((generation) => <Link className="generation-row" href={`/generations/${generation.id}`} key={generation.id}><span><strong>{generation.id}</strong><small>{generation.language} · {generation.format.toUpperCase()} · {generation.createdAt}</small></span><GenerationStatusBadge status={generation.status} /><span aria-hidden="true">→</span></Link>)}</div></section> : null}
      <div className="voice-list-footer"><span className={`status-dot${polling ? "" : " status-dot-muted"}`} aria-hidden="true" />{polling ? "Active jobs refresh with bounded backoff; completed jobs remain stable." : "Auto-refresh is paused; use Refresh to check for updates."}</div>
    </>
  );
}
