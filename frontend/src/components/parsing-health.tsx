import type { Resource } from "@/lib/types";
import { fileURL } from "@/lib/api";

export function ParsingReview({ resource }: { resource: Resource }) {
  const health = resource.parsing_health;
  if (!['pdf', '.pdf', 'application/pdf'].includes(resource.file_type.toLowerCase())) return <p className="small muted">Parsing not supported for this file type.</p>;
  const status = health?.status ?? "unknown";
  if (!health || !["healthy", "review"].includes(status)) {
    const messages: Record<string, string> = { unknown: "Parsing review not available yet", stale: "PDF changed — parsing review needs updating",
      unavailable: "Parsing review unavailable — original PDF is unavailable", unable_to_parse: "Unable to parse this PDF — review the original", unsupported: "Parsing not supported for this file type" };
    return <p className="parsing-status small">{messages[status] ?? "Parsing review not available yet"}</p>;
  }
  const pages = [...new Set(health.issues.map(issue => issue.page_number))].sort((a, b) => a - b);
  const normalPages = Math.max(0, (health.total_pages ?? 0) - health.pages_need_review);
  return <div className="parsing-health">
    <p className="parsing-status small">{health.total_pages} pages · {health.pages_need_review
      ? `⚠ ${health.pages_need_review} page${health.pages_need_review === 1 ? " needs" : "s need"} review` : "✓ Parsing looks good"}</p>
    {health.possible_scanned_pdf && <p className="small">Possible scanned PDF — compare with the original.</p>}
    {!!health.pages_need_review && <p className="small muted">{normalPages} page{normalPages === 1 ? "" : "s"} without detected issues</p>}
    <details className="parsing-details">
      <summary>{health.pages_need_review ? "Review issues" : "Parsing details"}</summary>
      <p className="small muted">{health.total_pages} total pages · {health.pages_with_text} pages with text · {health.pages_need_review} warning pages · {health.pages_with_encoding_warnings} pages with encoding issues</p>
      <p className="small muted">{health.possible_scanned_pdf ? "Possible scanned document" : "No document-wide scan indicators detected"}. Automated checks may not catch every extraction issue.</p>
      {pages.map(page => <section className="parsing-page" key={page} aria-label={`Review Page ${page}`}>
        <h4>Page {page}</h4>
        {health.issues.filter(issue => issue.page_number === page).map(issue => <div key={issue.category}>
          <p className="small"><span className={`parsing-severity ${issue.severity}`}>{issue.severity === "info" ? "Info" : issue.severity === "critical" ? "Unable to extract reliably" : "Review"}</span> <strong>{issue.label}</strong></p>
          <p className="small muted">{issue.explanation}</p>
        </div>)}
        {resource.file_available && <a className="text-link" href={fileURL(resource.id, page)} target="_blank" rel="noopener noreferrer">Open page {page}</a>}
      </section>)}
      {!!pages.length && <p className="small muted">Page numbers refer to PDF pages. If your viewer opens at the beginning, navigate to the page shown above.</p>}
    </details>
  </div>;
}
