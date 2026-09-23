// Isolated automated-test fixtures. Production imports none of this data.
import type { DashboardData, KnowledgeResponse, Resource, SyncResult, Week } from "@/lib/types";
export const course = { id: 2, semester_id: 1, canvas_course_id: 100, code: "NET101", name: "Networks and distributed systems", module_count: 2, parsed_resource_count: 1, latest_module: "Revision" };
export const week: Week = { id: 3, course_id: 2, week_number: 2, title: "Link layer", canvas_module_id: 400 };
export const resource: Resource = { id: 7, week_id: 3, canvas_file_id: 500, filename: "Lecture.pdf", file_type: "pdf", sync_status: "completed", file_available: true, size_bytes: 2200000 };
export const syncResult: SyncResult = { id: 1, status: "completed", started_at: "2026-09-01T10:00:00Z", completed_at: "2026-09-01T10:01:00Z", courses_processed: 1, files_discovered: 5, files_downloaded: 3, files_updated: 1, files_skipped: 2, files_failed: 0 };
export const dashboard: DashboardData = { semesters: [{ id: 1, year: 2026, term: "S2", name: "2026 Semester 2" }], active_semester: { id: 1, year: 2026, term: "S2", name: "2026 Semester 2", is_active: true }, courses: [course], latest_sync: null };
export const knowledge: KnowledgeResponse = { resource_id: 7, stale: false, extraction: { knowledge: {
  topic: "Frames", overview: "The link layer moves data in frames.",
  concepts: [{ name: "Frame", definition: "A unit of link-layer data.", explanation: "Frames carry data between neighboring devices.", importance: "high", source_pages: [2] }],
  key_points: [{ content: "Frames carry data.", source_pages: [2] }],
  formulas: [{ formula: "F = D + H", explanation: "The original notation.", source_page: 4, reliable: true }],
  examples: [{ description: "The lecture shows an Ethernet frame.", source_pages: [3] }],
  exam_focus: [{ content: "Learning outcome: identify a frame.", source_pages: [1] }],
  questions: [{ question: "What carries data?", answer: "A frame carries data.", source_pages: [2] }],
} } };
