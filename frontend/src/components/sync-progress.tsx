"use client";
import { useEffect, useState } from "react";
import type { SyncResult } from "@/lib/types";

const steps = [
  ["discovery", "File discovered"], ["download", "Downloaded"], ["parse", "Parsed"],
  ["generation", "Learning notes generated"], ["review", "Knowledge reviewed"], ["persistence", "Result saved"],
] as const;
export function stageLabel(stage: string): string {
  return ({ discovery: "Discovering courses", checking: "Checking course materials", download: "Downloading material",
    parse: "Reading document", generation: "Generating learning notes", knowledge: "Knowledge processing",
    review: "Checking generated knowledge", persistence: "Saving learning material", completed: "Complete" } as Record<string, string>)[stage] ?? "Preparing materials";
}
export function duration(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  return value >= 3600 ? `${Math.floor(value / 3600)}h ${Math.floor(value % 3600 / 60)}m ${value % 60}s`
    : value >= 60 ? `${Math.floor(value / 60)}m ${value % 60}s` : `${value}s`;
}
export function SyncTiming({ result, running = false }: { result?: SyncResult | null; running?: boolean }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  if (!result) return null;
  const elapsed = ((result.completed_at ? Date.parse(result.completed_at) : now) - Date.parse(result.started_at)) / 1000;
  const stamp = result.details?.progress?.updated_at;
  const age = stamp ? Math.max(0, (now - Date.parse(stamp)) / 1000) : null;
  return <div className="sync-timing small muted">
    <span>{running ? "Running for" : "Duration"} {duration(elapsed)}</span>
    {running && <span>{age === null ? "Waiting for a progress timestamp" : `Last update ${duration(age)} ago`}</span>}
    {running && age !== null && age >= 60 && <p>The current request may still be running. No newer progress update has arrived.</p>}
  </div>;
}
export function SyncIssues({ result }: { result?: SyncResult | null }) {
  const issues = result?.details?.errors;
  if (!issues?.length) return null;
  const files = result?.files_failed ?? 0;
  return <details className="sync-issues"><summary>Needs attention · {files ? `${files} file${files === 1 ? "" : "s"}` : `${issues.length} discovery issue${issues.length === 1 ? "" : "s"}`}</summary>
    <ul>{issues.map((issue, index) => <li key={index}>{issue.course_code ?? "Course"} · {issue.filename ?? "Material discovery"} — {stageLabel(issue.stage)} failed</li>)}</ul>
  </details>;
}
export function ResourcePipeline({ result }: { result: SyncResult }) {
  const progress = result.details?.progress;
  if (!progress?.filename) return null;
  return <ol className="sync-pipeline" aria-label="Current resource pipeline">
    {steps.map(([key, label]) => {
      const state = progress.steps?.[key] ?? "pending";
      const symbol = ({ completed: "✓", current: "→", pending: "○", failed: "!", skipped: "–" } as Record<string, string>)[state] ?? "○";
      return <li key={key} data-state={state} aria-current={state === "current" ? "step" : undefined}>
        <span aria-hidden="true">{symbol}</span><span>{state === "current" ? stageLabel(key === "discovery" ? "checking" : key) : label}</span><span className="sr-only"> — {state}</span>
      </li>;
    })}
  </ol>;
}
export function SyncProgress({ result, cancelling, cancel, error }: {
  result: SyncResult | null | undefined; cancelling: boolean; cancel: () => Promise<void>; error: string | null;
}) {
  const progress = result?.details?.progress;
  const discovered = result?.files_discovered ?? 0, completed = result?.details?.files_analyzed ?? 0;
  const skipped = result?.files_skipped ?? 0, failed = result?.files_failed ?? 0;
  const settled = Math.min(discovered, result?.details?.dry_run ? (result.details.files_checked ?? 0) + failed : completed + skipped + failed);
  const known = result?.details?.discovery_complete && !result.details.discovery_incomplete;
  return <section className="sync-feedback sync-progress" aria-label="Sync progress">
    <div className="sync-heading"><h2>{result?.details?.dry_run ? "Checking Canvas · dry run" : "Syncing Canvas"}</h2>
      <button className="button secondary" disabled={!result || cancelling} onClick={() => void cancel()}>{cancelling ? "Cancelling…" : "Cancel Sync"}</button></div>
    <div className="sync-current" role="status" aria-live="polite">
      <dl className="sync-identity">
        <div><dt>Course</dt><dd>{progress?.course_code ? `${progress.course_code} · ${progress.course_name ?? ""}` : "Finding current-semester courses…"}</dd></div>
        <div><dt>Module</dt><dd>{progress?.module ?? "Checking available modules…"}</dd></div>
        <div><dt>File</dt><dd>{progress?.filename ?? "Discovering course materials…"}</dd></div>
      </dl>
      <p className="sync-operation"><strong>Current operation:</strong> {stageLabel(progress?.stage ?? "discovery")}
        {progress?.stage === "generation" && progress.batch && progress.batches ? <span className="small muted"> · Batch {progress.batch} / {progress.batches}</span> : null}</p>
    </div>
    {result && <ResourcePipeline result={result} />}
    {known ? <>
      <p className="sync-overall">{settled} / {discovered} resources {result?.details?.dry_run ? "checked" : "processed"}
        {discovered > 0 && <span> · {Math.floor(settled / discovered * 100)}% · {Math.max(0, discovered - settled)} remaining</span>}</p>
      {discovered > 0 && <progress aria-label="Overall sync progress" value={settled} max={discovered} />}
    </> : <>
      <p className="sync-overall">{result?.details?.discovery_incomplete ? "Discovery incomplete — counts cover found materials only." : "Checking Canvas… Total materials not yet known."}</p>
      <progress aria-label="Discovering course materials" />
    </>}
    <dl className="sync-counts">{[["Discovered", discovered], ["Completed", completed], ["In progress", progress?.processing ? 1 : 0], ["Skipped", skipped], ["Failed", failed]].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>
    <SyncTiming result={result} running />
    {cancelling && <p className="small">Stopping at the next safe boundary. The current request may need to finish. Completed materials are kept.</p>}
    <SyncIssues result={result} />
    {error && <p role="alert">{error}</p>}
  </section>;
}
