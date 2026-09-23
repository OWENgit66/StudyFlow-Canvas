// Learning-facing projections of real backend schemas. Diagnostic fields in
// KnowledgeResponse are deliberately not consumed by the learning interface.
export interface Semester { id: number; name: string; year: number; term: string; is_active?: boolean; canvas_term_id?: number | null }
export interface Course { id: number; semester_id: number; canvas_course_id: number | null; code: string; name: string }
export interface CourseCardData extends Course { module_count: number; parsed_resource_count: number; current_knowledge_count?: number; latest_module: string | null }
export interface Week { id: number; course_id: number; week_number: number; title: string; canvas_module_id: number | null; resource_count?: number; resources_need_review?: number; parsing_reports_unavailable?: number }
export interface ParsingHealth {
  status: "healthy" | "review" | "unable_to_parse" | "unknown" | "stale" | "unavailable" | "unsupported";
  total_pages: number | null; pages_with_text: number | null; pages_need_review: number;
  pages_with_encoding_warnings: number; possible_scanned_pdf: boolean | null;
  issues: { page_number: number; category: string; label: string; explanation: string; severity: "info" | "warning" | "critical"; occurrences: number }[];
}
export interface Resource {
  id: number; week_id: number; canvas_file_id: number | null; filename: string; file_type: string;
  sync_status: "pending" | "downloaded" | "parsed" | "processing" | "completed" | "failed";
  file_available: boolean; size_bytes: number | null;
  parsing_health?: ParsingHealth | null;
}
export interface Sourced { source_pages: number[] }
export interface Concept extends Sourced { name: string; definition: string; explanation: string; importance: "low" | "medium" | "high" }
export interface Point extends Sourced { content: string }
export interface Example extends Sourced { description: string }
export interface Question extends Sourced { question: string; answer: string }
export interface Formula { formula: string; explanation: string | null; source_page: number; reliable: boolean }
export interface Knowledge {
  topic: string; overview: string; concepts: Concept[]; key_points: Point[];
  formulas: Formula[]; examples: Example[]; exam_focus: Point[]; questions: Question[];
}
export interface KnowledgeResponse { resource_id: number; stale: boolean; extraction: { knowledge: Knowledge } }
export interface SyncScope { semester_id?: number; course_id?: number; module_id?: number; file_id?: number }
export interface SyncResult {
  id: number; status: "running" | "completed" | "completed_with_errors" | "failed" | "cancelled";
  started_at: string; completed_at: string | null; courses_processed: number;
  files_discovered: number; files_downloaded: number; files_updated: number; files_skipped: number; files_failed: number;
  details?: {
    dry_run?: boolean;
    progress?: { stage: string; course_code?: string | null; course_name?: string | null; module?: string | null; filename?: string | null;
      course_id?: number | null; module_id?: number | null; resource_id?: number | null; updated_at?: string | null; processing?: boolean;
      steps?: Record<string, "pending" | "current" | "completed" | "failed" | "skipped">; batch?: number | null; batches?: number | null; parsing_review_pages?: number | null };
    files_analyzed?: number; files_parsed?: number; cancel_requested?: boolean; discovery_complete?: boolean;
    files_checked?: number; discovery_incomplete?: boolean;
    errors?: { stage: string; course_code?: string | null; filename?: string | null }[];
  };
}
export interface DashboardData { semesters: Semester[]; active_semester: Semester | null; courses: CourseCardData[]; latest_sync: SyncResult | null }
