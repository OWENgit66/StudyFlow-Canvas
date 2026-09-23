import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SyncFeedback, SyncProvider } from "@/components/sync";
import { CoursePage } from "@/components/course-page";
import { api } from "@/lib/api";
import type { SyncResult } from "@/lib/types";
import { course, week } from "./fixtures";

let running: SyncResult;
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-23T10:06:42Z"));
  running = { id: 12, status: "running", started_at: "2026-09-23T10:00:00Z", completed_at: null,
    courses_processed: 1, files_discovered: 12, files_downloaded: 5, files_updated: 0, files_skipped: 1, files_failed: 1,
    details: { discovery_complete: true, files_analyzed: 5, progress: {
      stage: "generation", filename: "Lecture.pdf", course_code: "NET101", course_name: "Networks", module: "Week 07",
      processing: true, updated_at: "2026-09-23T10:06:39Z", batch: 2, batches: 4,
      steps: { discovery: "completed", download: "completed", parse: "completed", generation: "current", review: "pending", persistence: "pending" },
    }, errors: [{ stage: "download", course_code: "NET101", filename: "Failed.pdf" }] },
  };
  vi.spyOn(api, "activeSync").mockImplementation(async () => structuredClone(running));
  vi.spyOn(api, "syncStatus").mockImplementation(async () => structuredClone(running));
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
async function mount(children = <SyncFeedback />) {
  let view!: ReturnType<typeof render>;
  await act(async () => { view = render(<SyncProvider>{children}</SyncProvider>); });
  return view;
}
const tick = (ms = 1000) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

it("shows indeterminate discovery without invented percentages even when some files were found", async () => {
  running.details!.discovery_complete = false;
  running.details!.progress = { stage: "checking", course_code: "NET101", module: "Week 07", processing: false };
  await mount();
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
  expect(screen.getByText(/Total materials not yet known/)).toBeVisible();
  expect(document.body.textContent).not.toContain("%");
  running.details!.discovery_complete = true;
  await tick();
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "7");
  expect(screen.getByRole("progressbar")).toHaveAttribute("max", "12");
  expect(screen.getByText(/58% · 5 remaining/)).toBeVisible();
});

it("renders exact identity, counts, batches, elapsed time and confirmed pipeline transitions", async () => {
  await mount();
  for (const text of ["NET101 · Networks", "Week 07", "Lecture.pdf", "Running for 6m 42s", "Last update 3s ago"]) expect(screen.getByText(text)).toBeVisible();
  expect(screen.getByText(/Batch 2 \/ 4/)).toBeVisible();
  const pipeline = screen.getByRole("list", { name: "Current resource pipeline" });
  expect(within(pipeline).getByText("Parsed").closest("li")).toHaveAttribute("data-state", "completed");
  expect(within(pipeline).getByText("Generating learning notes").closest("li")).toHaveAttribute("aria-current", "step");
  expect(within(pipeline).getByText("Knowledge reviewed").closest("li")).toHaveAttribute("data-state", "pending");
  for (const [label, count] of [["Completed", "5"], ["Skipped", "1"], ["Failed", "1"], ["In progress", "1"]]) {
    expect(within(screen.getByText(label).parentElement!).getByText(count)).toBeVisible();
  }
  running.details!.progress!.stage = "review";
  running.details!.progress!.steps!.generation = "completed";
  running.details!.progress!.steps!.review = "current";
  await tick();
  expect(within(pipeline).getByText("Learning notes generated").closest("li")).toHaveAttribute("data-state", "completed");
  expect(within(pipeline).getByText("Checking generated knowledge").closest("li")).toHaveAttribute("aria-current", "step");
  expect(within(pipeline).getByText("Result saved").closest("li")).toHaveAttribute("data-state", "pending");
  expect(screen.queryByText(/Batch 2/)).not.toBeInTheDocument();
});

it.each(["completed", "completed_with_errors", "failed", "cancelled"] as const)("stops polling after %s", async status => {
  await mount();
  running.status = status; running.completed_at = "2026-09-23T10:06:43Z";
  await tick();
  expect(screen.queryByRole("region", { name: "Sync progress" })).not.toBeInTheDocument();
  const calls = vi.mocked(api.syncStatus).mock.calls.length;
  await tick(20000);
  expect(api.syncStatus).toHaveBeenCalledTimes(calls);
  if (status === "cancelled") expect(screen.getByText(/5 resources completed · 1 skipped · 1 failed · 5 not processed/)).toBeInTheDocument();
});

it("never overlaps status requests and does not fake a heartbeat while waiting", async () => {
  let resolve!: (value: SyncResult) => void;
  vi.mocked(api.syncStatus).mockImplementation(() => new Promise(done => { resolve = done; }));
  await mount(); await tick(65000);
  expect(api.syncStatus).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/No newer progress update has arrived/)).toBeVisible();
  await act(async () => { resolve(running); });
  await tick();
  expect(api.syncStatus).toHaveBeenCalledTimes(2);
});

it("keeps failures expandable during processing and allows course browsing", async () => {
  vi.spyOn(api, "course").mockResolvedValue(course);
  vi.spyOn(api, "weeks").mockResolvedValue([week]);
  await mount(<CoursePage id={2} />);
  expect(screen.getByRole("link", { name: /Link layer/ })).toHaveAttribute("href", "/weeks/3");
  expect(screen.getByRole("region", { name: "Sync progress" })).toBeVisible();
  fireEvent.click(screen.getByText("Needs attention · 1 file"));
  expect(screen.getByText("NET101 · Failed.pdf — Downloading material failed")).toBeVisible();
  running.details!.progress!.steps!.generation = "failed";
  running.details!.progress!.processing = false;
  await tick();
  expect(screen.getByText("Learning notes generated").closest("li")).toHaveAttribute("data-state", "failed");
});

it("does not claim a full-scope percentage after a discovery failure", async () => {
  running.details!.discovery_incomplete = true;
  await mount();
  expect(screen.getByText(/Discovery incomplete/)).toBeVisible();
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
});
