"use client";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, APIError } from "@/lib/api";
import type { SyncResult, SyncScope } from "@/lib/types";
import { SyncProgress, SyncIssues, SyncTiming } from "./sync-progress";

interface SyncState {
  busy: boolean; result: SyncResult | null; error: string | null;
  run: (scope: SyncScope) => Promise<void>;
  cancel: () => Promise<void>; cancelling: boolean;
}
const SyncContext = createContext<SyncState | null>(null);
export function SyncProvider({ children }: { children: ReactNode }) {
  const lock = useRef(false);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = starting || result?.status === "running";
  useEffect(() => {
    let mounted = true;
    api.activeSync().then(current => {
      if (mounted && current && !lock.current) { lock.current = true; setResult(current); }
    }).catch(() => {});
    return () => { mounted = false; };
  }, []);
  const runningId = result?.status === "running" ? result.id : null;
  useEffect(() => {
    if (runningId === null) return;
    let mounted = true, failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const current = await api.syncStatus(runningId!);
        if (!mounted) return;
        failures = 0; setResult(current);
        if (current.status !== "running") { lock.current = false; setCancelling(false); return; }
      } catch {
        if (!mounted) return;
        if (++failures >= 3) {
          setError("Cannot read sync progress. The backend may still be processing; check its status before starting again.");
          setResult(null); setCancelling(false); lock.current = false; return;
        }
      }
      if (mounted) timer = setTimeout(poll, 1000);
    }
    timer = setTimeout(poll, 1000);
    return () => { mounted = false; clearTimeout(timer); };
  }, [runningId]);
  async function run(scope: SyncScope) {
    if (lock.current) return;
    lock.current = true; setStarting(true); setError(null); setResult(null); setCancelling(false);
    try {
      const current = await api.sync(scope); setResult(current);
      if (current.status !== "running") lock.current = false;
    }
    catch (error) {
      setError(error instanceof APIError && error.status === 409
        ? "A Canvas sync is already running. Please wait before trying again."
        : "Canvas sync could not finish. Check the backend connection and try again. A sync may still be running; check its status before retrying.");
      lock.current = false;
    } finally { setStarting(false); }
  }
  async function cancel() {
    if (!result || result.status !== "running" || cancelling) return;
    setCancelling(true);
    try { setResult(await api.cancelSync(result.id)); }
    catch { setCancelling(false); setError("Cancellation could not be confirmed. Progress will continue to update; try Cancel Sync again."); }
  }
  return <SyncContext.Provider value={{ busy, result, error, run, cancel, cancelling }}>{children}</SyncContext.Provider>;
}
export function useSync() {
  const context = useContext(SyncContext);
  if (!context) throw new Error("SyncProvider is required");
  return context;
}
export function SyncButton({ scope, disabled = false }: { scope: SyncScope; disabled?: boolean }) {
  const sync = useSync();
  return <button className="button" disabled={disabled || sync.busy} onClick={() => void sync.run(scope)}>
    <span aria-hidden="true" className={sync.busy ? "spin" : ""}>↻</span> {sync.busy ? "Syncing Canvas…" : "Sync Canvas"}
  </button>;
}
export function SyncFeedback({ previous }: { previous?: SyncResult | null }) {
  const sync = useSync();
  const result = sync.result ?? previous;
  if (sync.busy) return <SyncProgress result={sync.result} cancelling={!!(sync.cancelling || sync.result?.details?.cancel_requested)} cancel={sync.cancel} error={sync.error} />;
  if (sync.error) return <div className="sync-feedback error" role="alert">{sync.error}</div>;
  if (!result) return <p className="small muted sync-footnote">Canvas has not been synced yet.</p>;
  const label = result.details?.dry_run && result.status === "completed" ? "Canvas dry run completed" : { running: "Canvas sync in progress", completed: "Sync completed", completed_with_errors: "Sync completed with issues", failed: "Canvas sync failed", cancelled: "Sync cancelled" }[result.status];
  return <details className="sync-feedback" key={result.id}>
    <summary><span className={`status-dot ${result.status === "failed" ? "warning" : ""}`} />{label}<span className="muted small">{result.completed_at ? new Date(result.completed_at).toLocaleString() : "In progress"}</span></summary>
    <dl className="sync-counts">{[
      ["Courses", result.courses_processed], ["Files found", result.files_discovered],
      ["New downloads", Math.max(0, result.files_downloaded - result.files_updated)],
      ["Updated", result.files_updated], ["Unchanged / skipped", result.files_skipped], ["Failed", result.files_failed],
    ].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>
    {result.details?.dry_run && <p className="small">Discovery only. No materials were downloaded, parsed, or sent to AI.</p>}
    <SyncTiming result={result} />
    <SyncIssues result={result} />
    {result.status === "cancelled" && <p>{result.details?.files_analyzed ?? 0} resources completed · {result.files_skipped} skipped · {result.files_failed} failed · {Math.max(0, result.files_discovered - (result.details?.files_analyzed ?? 0) - result.files_skipped - result.files_failed)} not processed{!result.details?.discovery_complete && " among discovered files; discovery was unfinished"}</p>}
    {result.status === "cancelled" && <p className="small">Stopped safely. Completed materials were kept; unfinished files can be resumed by a new sync.</p>}
  </details>;
}
