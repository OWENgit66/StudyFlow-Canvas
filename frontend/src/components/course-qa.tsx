"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, APIError, fileURL } from "@/lib/api";
import type { CourseAnswer, CourseIndexStatus } from "@/lib/types";

export function CourseQA({ courseId }: { courseId: number }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<CourseAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const [index, setIndex] = useState<CourseIndexStatus | null>(null);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try { const status = await api.indexStatus(courseId); if (active) setIndex(status); }
      catch { if (active) setIndex({ state: "unavailable", message: "Could not check Course Q&A readiness. Check that the backend is running.", total_chunks: 0, indexed_chunks: 0, missing_chunks: 0 }); }
      if (active) timer = setTimeout(refresh, 10000);
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [courseId]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending.current || !question.trim() || index?.state !== "ready") return;
    pending.current = true;
    setLoading(true); setError(""); setAnswer(null);
    try { setAnswer(await api.ask(courseId, question.trim())); }
    catch (failure) {
      setError(failure instanceof APIError && failure.status === 503
        ? "Course Q&A is temporarily unavailable. This course may not have a ready index, or the service may be busy."
        : "Could not answer this question. Please try again later.");
    } finally { pending.current = false; setLoading(false); }
  }
  return <section className="course-section" aria-labelledby="course-qa-title">
    <div className="section-heading"><h2 id="course-qa-title">Course Q&A</h2></div>
    {index?.state !== "ready" && <p role="status">{index?.message ?? "Preparing Course Q&A…"}</p>}
    <form onSubmit={submit} className="course-qa-form">
      <label htmlFor="course-question">Ask your course</label>
      <textarea id="course-question" value={question} onChange={e => setQuestion(e.target.value)}
        maxLength={4000} rows={3} disabled={loading} placeholder="What is CRC?" required />
      <div><button type="submit" className="button primary" disabled={loading || !question.trim() || index?.state !== "ready"}>Ask</button></div>
    </form>
    {loading && <p role="status">Finding course evidence and preparing your answer…</p>}
    {error && <p role="alert">{error}</p>}
    {answer && <div aria-live="polite" className="course-qa-result">
      <h3>Answer</h3><p className="course-qa-answer">{answer.answer}</p>
      {answer.sources.length > 0 && <><h3>Sources</h3><ul className="course-qa-sources">{answer.sources.map(source => {
        const label = `[${source.citation_id}] ${source.week} — ${source.title}${source.page ? ` · Page ${source.page}` : ""}`;
        // Only use the existing material endpoint; never render model-supplied URLs/HTML.
        const expected = `/api/resources/${source.resource_id}/file${source.page ? `#page=${source.page}` : ""}`;
        return <li key={source.citation_id}>{source.source_url === expected
          ? <a href={fileURL(source.resource_id, source.page ?? undefined)} target="_blank" rel="noopener noreferrer">{label}</a>
          : <span>{label}</span>}</li>;
      })}</ul></>}
    </div>}
  </section>;
}
