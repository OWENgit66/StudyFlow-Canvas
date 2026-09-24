import { fileURL } from "@/lib/api";
import type { Resource } from "@/lib/types";
import { ParsingReview } from "./parsing-health";

function fileSize(bytes: number | null) {
  if (bytes === null) return null;
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
export function ResourceItem({ resource }: { resource: Resource }) {
  const role = resource.resource_type ?? "other";
  const roleLabel = { lecture: "Lecture", tutorial: "Tutorial", other: "Other material" }[role];
  const status = { pending: "Awaiting download", downloaded: "Downloaded", parsed: "Parsed", processing: "Preparing", completed: "Processed", failed: "Needs attention" }[resource.sync_status];
  return <article className="resource-row"><span className="file-icon" aria-hidden="true">↧</span><div className="resource-info"><h3>{resource.filename}</h3><span className={`resource-type resource-type-${role}`}>{roleLabel}</span><p className="small muted">{resource.file_type.toUpperCase()}{resource.size_bytes !== null && ` · ${fileSize(resource.size_bytes)}`} · {status}</p><ParsingReview resource={resource} /></div>
    {resource.file_available ? <div className="resource-actions"><a className="text-link" href={fileURL(resource.id)} target="_blank" rel="noopener noreferrer">Open <span aria-hidden="true">↗</span></a><a className="small muted" href={fileURL(resource.id, undefined, true)}>Download</a></div> : <span className="small muted">File unavailable</span>}</article>;
}
