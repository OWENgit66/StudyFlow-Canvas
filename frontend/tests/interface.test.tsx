import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { Dashboard } from "@/components/dashboard";
import { CoursePage } from "@/components/course-page";
import { WeekPage } from "@/components/week-page";
import { LearningContent } from "@/components/learning-content";
import { SyncProvider } from "@/components/sync";
import { course, dashboard, knowledge, resource, syncResult, week } from "./fixtures";

type Reply = { body: unknown; status?: number };
let routes: Record<string, Reply>;
let fetchMock: Mock<(url: string, init?: RequestInit) => Promise<Response>>;
const renderPage = (page: React.ReactNode) => render(<SyncProvider>{page}</SyncProvider>);
beforeEach(() => {
  routes = {
    "/api/sync/current": { body: null },
    "/api/study/dashboard": { body: structuredClone(dashboard) },
    "/api/courses/2": { body: course }, "/api/courses/2/weeks": { body: [week, { ...week, id: 4, title: "Revision" }] },
    "/api/weeks/3": { body: week }, "/api/weeks/3/resources": { body: [resource] },
    "/api/resources/7/knowledge": { body: structuredClone(knowledge) }, "/api/sync?background=true": { body: syncResult },
  };
  fetchMock = vi.fn(async (url: string) => {
    const route = routes[url];
    if (!route) throw new Error(`Unexpected request: ${url}`);
    return new Response(JSON.stringify(route.body), { status: route.status ?? 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
});

describe("course browsing", () => {
  it("renders real response course cards, counts, semester and destination", async () => {
    renderPage(<Dashboard />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading your courses");
    const card = await screen.findByRole("link", { name: /NET101/ });
    expect(card).toHaveAttribute("href", "/courses/2");
    expect(card).toHaveTextContent("Networks and distributed systems");
    expect(card).toHaveTextContent("2 modules");
    expect(card).toHaveTextContent("1 parsed materials");
    expect(screen.getAllByText("2026 Semester 2")).toHaveLength(2);
    expect(screen.queryByText(/learning progress/i)).not.toBeInTheDocument();
  });
  it("preserves non-week Canvas module names", async () => {
    renderPage(<CoursePage id={2} />);
    expect(await screen.findByRole("link", { name: /Revision/ })).toHaveAttribute("href", "/weeks/4");
    expect(screen.getByRole("link", { name: /Link layer/ })).toHaveAttribute("href", "/weeks/3");
  });
  it("handles empty dashboard and empty course", async () => {
    routes["/api/study/dashboard"].body = { ...dashboard, courses: [] };
    const mounted = renderPage(<Dashboard />);
    expect(await screen.findByText(/No course materials have been synced/)).toBeVisible();
    mounted.unmount(); routes["/api/courses/2/weeks"].body = [];
    renderPage(<CoursePage id={2} />);
    expect(await screen.findByText("No modules yet")).toBeVisible();
  });
  it("shows a friendly backend error and supports retry", async () => {
    routes["/api/study/dashboard"] = { status: 500, body: { detail: "private-token traceback E:/private" } };
    renderPage(<Dashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your courses");
    expect(document.body.textContent).not.toMatch(/private-token|traceback|E:\/private/);
    routes["/api/study/dashboard"] = { body: dashboard };
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /NET101/ })).toBeVisible();
  });
});

describe("learning content", () => {
  it("renders overview, concepts, points, safe formulas, examples and explicit exam cues", async () => {
    renderPage(<WeekPage id={3} />);
    expect(await screen.findByText("The link layer moves data in frames.")).toBeVisible();
    for (const text of ["Frame", "A unit of link-layer data.", "Frames carry data between neighboring devices.", "Frames carry data.", "F = D + H", "The lecture shows an Ethernet frame.", "Learning outcome: identify a frame."]) expect(screen.getByText(text)).toBeVisible();
    expect(screen.getByText("high importance")).toBeVisible();
  });
  it("shows and hides answers without any additional request", async () => {
    renderPage(<WeekPage id={3} />);
    const button = await screen.findByRole("button", { name: "Show Answer" });
    const before = fetchMock.mock.calls.length;
    expect(screen.getByText("A frame carries data.")).not.toBeVisible();
    await userEvent.click(button);
    expect(screen.getByText("A frame carries data.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Hide Answer" })).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("button", { name: "Hide Answer" }));
    expect(screen.getByText("A frame carries data.")).not.toBeVisible();
    expect(fetchMock.mock.calls).toHaveLength(before);
  });
  it("links source filename and exact page to registered file endpoint", async () => {
    renderPage(<WeekPage id={3} />);
    const sources = await screen.findAllByRole("link", { name: /Lecture.pdf · Page 2/ });
    expect(sources[0]).toHaveAttribute("href", "/api/resources/7/file#page=2");
    expect(sources[0]).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/api/resources/7/file");
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/resources/7/file?download=true");
    expect(document.body.textContent).not.toMatch(/chunk_id|source_fingerprint/);
  });
  it("handles absent current knowledge and still shows materials", async () => {
    routes["/api/resources/7/knowledge"] = { status: 404, body: { detail: "No current knowledge" } };
    renderPage(<WeekPage id={3} />);
    expect(await screen.findByText(/No current learning notes/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open" })).toBeVisible();
    expect(screen.queryByText("Frame")).not.toBeInTheDocument();
  });
  it("does not render stale knowledge from an unexpected API response", async () => {
    routes["/api/resources/7/knowledge"].body = { ...knowledge, stale: true };
    renderPage(<WeekPage id={3} />);
    expect(await screen.findByText(/No current learning notes/)).toBeVisible();
    expect(screen.queryByText(knowledge.extraction.knowledge.overview)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(call => call[0]).join()).not.toContain("include_stale");
  });
  it("also rejects stale content at the rendering boundary", () => {
    render(<LearningContent entries={[{ resource, response: { ...knowledge, stale: true } }]} />);
    expect(screen.queryByText("Frame")).not.toBeInTheDocument();
  });
  it("hides empty exam focus and unsafe formulas", async () => {
    const data = structuredClone(knowledge);
    data.extraction.knowledge.exam_focus = [];
    data.extraction.knowledge.formulas[0].reliable = false;
    routes["/api/resources/7/knowledge"].body = data;
    renderPage(<WeekPage id={3} />);
    await screen.findByText("Frame");
    expect(screen.queryByRole("heading", { name: "Exam focus" })).not.toBeInTheDocument();
    expect(screen.queryByText("F = D + H")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Formulas" })).not.toBeInTheDocument();
    expect(screen.queryByText("No exam content")).not.toBeInTheDocument();
  });
  it("keeps materials accessible on knowledge read failure and retries", async () => {
    routes["/api/resources/7/knowledge"] = { status: 500, body: { detail: "SQLAlchemy private error" } };
    renderPage(<WeekPage id={3} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Some learning notes could not be loaded");
    expect(screen.getByRole("link", { name: "Open" })).toBeVisible();
    routes["/api/resources/7/knowledge"] = { body: knowledge };
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Frame")).toBeVisible();
  });
  it("handles no resources and unavailable originals", async () => {
    routes["/api/weeks/3/resources"].body = [];
    const mounted = renderPage(<WeekPage id={3} />);
    expect(await screen.findByText("No materials here yet")).toBeVisible();
    mounted.unmount();
    routes["/api/weeks/3/resources"].body = [{ ...resource, file_available: false, size_bytes: null }];
    renderPage(<WeekPage id={3} />);
    expect(await screen.findByText("File unavailable")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open" })).not.toBeInTheDocument();
  });
  it.each(["/api/weeks/3", "/api/courses/2"])("handles page failure at %s", async url => {
    routes[url] = { status: 500, body: {} };
    renderPage(url === "/api/courses/2" ? <CoursePage id={2} /> : <WeekPage id={3} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(await screen.findByRole("alert")).toBeVisible();
  });
});

describe("Canvas sync", () => {
  it("posts selected semester, prevents duplicate clicks, displays real counters", async () => {
    let finish: (response: Response) => void = () => {};
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url === "/api/sync?background=true" ? new Promise<Response>(resolve => { finish = resolve; }) : original(url, init));
    renderPage(<Dashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "Sync Canvas" }));
    expect(screen.getByRole("button", { name: "Syncing Canvas…" })).toBeDisabled();
    const call = fetchMock.mock.calls.find(call => call[0] === "/api/sync?background=true")!;
    expect(call[1]).toMatchObject({ method: "POST", body: JSON.stringify({ semester_id: 1 }) });
    finish(new Response(JSON.stringify(syncResult)));
    await screen.findByText("Sync completed");
    await userEvent.click(screen.getByText("Sync completed"));
    const counts = screen.getByText("New downloads").parentElement!;
    expect(within(counts).getByText("2")).toBeVisible();
    expect(within(screen.getByText("Unchanged / skipped").parentElement!).getByText("2")).toBeVisible();
    expect(fetchMock.mock.calls.filter(call => call[0] === "/api/sync?background=true")).toHaveLength(1);
    await waitFor(() => expect(fetchMock.mock.calls.filter(call => call[0] === "/api/study/dashboard").length).toBeGreaterThan(1));
  });
  it("can scope sync to a single known material", async () => {
    renderPage(<WeekPage id={3} />);
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Sync scope" }), "7");
    await userEvent.click(screen.getByRole("button", { name: "Sync Canvas" }));
    await screen.findByText("Sync completed");
    const call = fetchMock.mock.calls.find(call => call[0] === "/api/sync?background=true")!;
    expect(call[1]?.body).toBe(JSON.stringify({ course_id: 2, module_id: 400, file_id: 500 }));
  });
  it("shows friendly failure without leaking backend error bodies", async () => {
    routes["/api/sync?background=true"] = { status: 500, body: { detail: "secret-key private traceback" } };
    renderPage(<Dashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "Sync Canvas" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Canvas sync could not finish");
    expect(document.body.textContent).not.toMatch(/secret-key|traceback/);
    expect(screen.getByRole("button", { name: "Sync Canvas" })).toBeEnabled();
  });
  it("renders completed-with-errors as partial failure", async () => {
    routes["/api/sync?background=true"].body = { ...syncResult, status: "completed_with_errors", files_failed: 1 };
    renderPage(<Dashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "Sync Canvas" }));
    expect(await screen.findByText("Sync completed with issues")).toBeVisible();
  });

  it("shows only the active semester's courses", async () => {
    routes["/api/study/dashboard"].body = { ...dashboard, courses: [course, { ...course, id: 9, semester_id: 2, code: "HIST999" }] };
    renderPage(<Dashboard />);
    expect(await screen.findByText("CURRENT SEMESTER")).toBeVisible();
    expect(screen.getByRole("link", { name: /NET101/ })).toBeVisible();
    expect(screen.queryByText("HIST999")).not.toBeInTheDocument();
  });

  it("clearly distinguishes a dry run from completed processing", async () => {
    routes["/api/study/dashboard"].body = { ...dashboard, latest_sync: { ...syncResult, details: { dry_run: true } } };
    renderPage(<Dashboard />);
    await userEvent.click(await screen.findByText("Canvas dry run completed"));
    expect(screen.getByText("Discovery only. No materials were downloaded, parsed, or sent to AI.")).toBeVisible();
  });

  const running = { ...syncResult, status: "running", completed_at: null, files_discovered: 9, files_skipped: 2, files_failed: 1,
    details: { discovery_complete: true, files_analyzed: 3, progress: { course_code: "NET101", course_name: "Networks", module: "Week 07", filename: "Lecture.pdf", stage: "generation" } } };

  it("keeps Dashboard navigation and live progress free of document review details", async () => {
    const result = { ...running, details: { ...running.details,
      progress: { ...running.details.progress, parsing_review_pages: 3 } } };
    routes["/api/sync/current"].body = result;
    routes["/api/sync/1"] = { body: result };
    renderPage(<Dashboard />);
    const panel = await screen.findByRole("region", { name: "Sync progress" });
    expect(await screen.findByRole("link", { name: /NET101/ })).toBeVisible();
    expect(within(panel).getByText("Generating learning notes")).toBeVisible();
    expect(within(panel).getByText(/6 \/ 9 resources processed/)).toBeVisible();
    expect(screen.queryByText(/pages need review|Parsed with notes|Review issues|^Page \d+$/)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.includes("/resources"))).toBe(false);
  });

  it("restores a running sync, renders real telemetry, and polls through completion", async () => {
    routes["/api/sync/current"].body = running;
    routes["/api/sync/1"] = { body: syncResult };
    renderPage(<Dashboard />);
    const panel = await screen.findByRole("region", { name: "Sync progress" });
    for (const text of ["Generating learning notes", "NET101 · Networks", "Week 07", "Lecture.pdf", "Discovered", "Completed", "In progress", "Skipped", "Failed"]) expect(within(panel).getByText(text)).toBeVisible();
    expect(within(panel).getByRole("progressbar")).toHaveAttribute("value", "6");
    expect(within(panel).getByRole("progressbar")).toHaveAttribute("max", "9");
    expect(within(within(panel).getByText("Completed").parentElement!).getByText("3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Syncing Canvas…" })).toBeDisabled();
    expect(await screen.findByText("Sync completed", {}, { timeout: 2500 })).toBeVisible();
    expect(screen.getByRole("button", { name: "Sync Canvas" })).toBeEnabled();
    expect(screen.queryByRole("region", { name: "Sync progress" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(call => call[1]?.method === "POST")).toBe(false);
  });

  it("cancels cooperatively and returns the controls to normal", async () => {
    routes["/api/sync?background=true"] = { status: 202, body: running };
    routes["/api/sync/1/cancel"] = { body: { ...running, details: { ...running.details, cancel_requested: true } } };
    routes["/api/sync/1"] = { body: { ...syncResult, status: "cancelled" } };
    renderPage(<Dashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "Sync Canvas" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel Sync" }));
    expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
    expect(screen.getByText(/Stopping at the next safe boundary/)).toBeVisible();
    expect(await screen.findByText("Sync cancelled", {}, { timeout: 2500 })).toBeVisible();
    expect(screen.getByRole("button", { name: "Sync Canvas" })).toBeEnabled();
    expect(fetchMock.mock.calls.find(call => call[0].endsWith("/cancel"))?.[1]?.method).toBe("POST");
  });

  it("renders failed file identity with a safe stage label", async () => {
    routes["/api/sync?background=true"].body = { ...syncResult, status: "completed_with_errors", files_failed: 1,
      details: { errors: [{ stage: "knowledge", course_code: "NET101", filename: "Organisation.pdf", message: "secret-key traceback" }] } };
    renderPage(<Dashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "Sync Canvas" }));
    await userEvent.click(await screen.findByText("Sync completed with issues"));
    await userEvent.click(screen.getByText("Needs attention · 1 file"));
    expect(screen.getByText("NET101 · Organisation.pdf — Knowledge processing failed")).toBeVisible();
    expect(document.body.textContent).not.toMatch(/secret-key|traceback/);
  });

  it("recovers from repeated polling errors without starting another sync", async () => {
    routes["/api/sync/current"].body = running;
    routes["/api/sync/1"] = { status: 500, body: { detail: "secret traceback" } };
    renderPage(<Dashboard />);
    expect(await screen.findByRole("region", { name: "Sync progress" })).toBeVisible();
    expect(await screen.findByRole("alert", {}, { timeout: 4500 })).toHaveTextContent("Cannot read sync progress");
    expect(screen.getByRole("button", { name: "Sync Canvas" })).toBeEnabled();
    expect(document.body.textContent).not.toMatch(/secret|traceback/);
    expect(fetchMock.mock.calls.some(call => call[1]?.method === "POST")).toBe(false);
  });
});
