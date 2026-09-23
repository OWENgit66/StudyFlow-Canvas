import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ResourceItem } from "@/components/resource-item";
import { CoursePage } from "@/components/course-page";
import { SyncProvider } from "@/components/sync";
import { SyncProgress } from "@/components/sync-progress";
import { api } from "@/lib/api";
import type { ParsingHealth } from "@/lib/types";
import { resource, course, week, syncResult } from "./fixtures";

const health: ParsingHealth = { status: "review", total_pages: 41, pages_with_text: 40, pages_need_review: 3,
  pages_with_encoding_warnings: 0, possible_scanned_pdf: false, issues: [
    { page_number: 12, category: "suspicious_formula_layout", label: "Formula layout may be unreliable", explanation: "Compare formulas with the original slide.", severity: "warning", occurrences: 1 },
    { page_number: 18, category: "unreadable_symbol", label: "Unreadable symbol detected", explanation: "A PDF glyph could not be reliably interpreted.", severity: "warning", occurrences: 2 },
    { page_number: 38, category: "empty_text", label: "No extractable text", explanation: "Its contents were not interpreted as text.", severity: "critical", occurrences: 1 },
  ] };

it("shows a healthy resource without claiming unreviewed files are healthy", () => {
  const view = render(<ResourceItem resource={{ ...resource, parsing_health: { ...health, status: "healthy", pages_need_review: 0, issues: [] } }} />);
  expect(screen.getByText(/Parsing looks good/)).toBeVisible();
  expect(screen.queryByText("Review issues")).not.toBeInTheDocument();
  view.rerender(<ResourceItem resource={resource} />);
  expect(screen.getByText("Parsing review not available yet")).toBeVisible();
  expect(screen.queryByText(/Parsing looks good/)).not.toBeInTheDocument();
});

it("expands exact warning pages, friendly categories and safe page links then collapses", async () => {
  render(<ResourceItem resource={{ ...resource, parsing_health: health }} />);
  expect(screen.getByText(/3 pages need review/)).toBeVisible();
  expect(screen.getByText(/38 pages without detected issues/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Open page 18", hidden: true })).not.toBeVisible();
  await userEvent.click(screen.getByText("Review issues"));
  for (const issue of health.issues) {
    expect(screen.getByText(`Page ${issue.page_number}`)).toBeVisible();
    expect(screen.getByText(issue.label)).toBeVisible();
    expect(screen.getByRole("link", { name: `Open page ${issue.page_number}` })).toHaveAttribute("href", `/api/resources/7/file#page=${issue.page_number}`);
  }
  expect(document.body.textContent).not.toMatch(/suspicious_formula_layout|unreadable_symbol|bbox|span_indices|local_path/);
  await userEvent.click(screen.getByText("Review issues"));
  expect(screen.getByText("Page 18")).not.toBeVisible();
});

it.each(["stale", "unavailable", "unable_to_parse"] as const)("does not display old page warnings when the report is %s", status => {
  render(<ResourceItem resource={{ ...resource, parsing_health: { ...health, status } }} />);
  expect(screen.queryByText("Review issues")).not.toBeInTheDocument();
  expect(screen.queryByText("Page 18")).not.toBeInTheDocument();
  expect(screen.queryByText(/Parsing looks good/)).not.toBeInTheDocument();
});

it("identifies possible scanned PDFs and retains the original link", () => {
  render(<ResourceItem resource={{ ...resource, parsing_health: { ...health, possible_scanned_pdf: true } }} />);
  expect(screen.getByText(/Possible scanned PDF/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/api/resources/7/file");
});

it("sums course review counts and shows per-module counts", async () => {
  const spies = [vi.spyOn(api, "activeSync").mockResolvedValue(null), vi.spyOn(api, "course").mockResolvedValue(course),
    vi.spyOn(api, "weeks").mockResolvedValue([{ ...week, resource_count: 3, resources_need_review: 1 },
      { ...week, id: 4, title: "Revision", resource_count: 2, resources_need_review: 2 }])];
  try {
    render(<SyncProvider><CoursePage id={2} /></SyncProvider>);
    expect(await screen.findByText("Parsing review: 3 materials need attention")).toBeVisible();
    expect(screen.getByRole("link", { name: /Link layer/ })).toHaveTextContent("1 material needs parsing review");
    expect(screen.getByRole("link", { name: /Revision/ })).toHaveTextContent("2 materials need parsing review");
    expect(screen.queryByText("Review issues")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Page \d+$/)).not.toBeInTheDocument();
  } finally { spies.forEach(spy => spy.mockRestore()); }
});

it("keeps parsing review counts out of live sync without treating warnings as failures", () => {
  render(<SyncProgress result={{ ...syncResult, status: "running", files_failed: 0,
    details: { progress: { stage: "generation", parsing_review_pages: 3 }, discovery_complete: true } }} cancelling={false} cancel={async () => {}} error={null} />);
  expect(screen.queryByText(/pages need review|Parsed with notes/)).not.toBeInTheDocument();
  expect(screen.getByText("Failed").parentElement).toHaveTextContent("Failed0");
  expect(screen.queryByText(/Needs attention/)).not.toBeInTheDocument();
});
