"use client";
import Link from "next/link";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useData } from "@/lib/use-data";
import { Breadcrumbs, Empty, Loading, LoadError } from "./page-state";
import { SyncButton, SyncFeedback, useSync } from "./sync";

export function CoursePage({ id }: { id: number }) {
  const sync = useSync();
  const load = useCallback(async () => {
    const [course, weeks] = await Promise.all([api.course(id), api.weeks(id)]);
    return { course, weeks };
  }, [id]);
  const state = useData(load, `${sync.result?.id ?? ""}:${sync.result?.status ?? ""}`);
  if (state.loading) return <Loading label="this course" />;
  if (state.error || !state.data) return <><Breadcrumbs items={[]} /><LoadError message="Could not load this course. It may be unavailable, or the backend may be offline." retry={state.retry} /></>;
  const { course, weeks } = state.data;
  const needsReview = weeks.reduce((count, week) => count + (week.resources_need_review ?? 0), 0);
  return <>
    <Breadcrumbs items={[{ label: course.code }]} />
    <div className="page-heading"><div><p className="eyebrow">{course.code}</p><h1>{course.name}</h1><p className="muted">{weeks.length} modules · Materials and ideas, in course order.</p></div><SyncButton scope={{ course_id: id }} disabled={!course.canvas_course_id} /></div>
    {(sync.busy || sync.result || sync.error) && <SyncFeedback />}
    {needsReview > 0 && <p className="small muted">Parsing review: {needsReview} material{needsReview === 1 ? " needs" : "s need"} attention</p>}
    <section className="course-section"><div className="section-heading"><h2>Course modules</h2><span className="small muted">Choose where to begin</span></div>
      {weeks.length ? <div className="module-list">{weeks.map((week, index) => <Link key={week.id} href={`/weeks/${week.id}`} className="module-row"><span className="module-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><div><h3>{week.title}</h3><span className="small muted">Explore learning content & materials</span>{week.resource_count !== undefined && <span className="small muted"> · {week.resource_count} materials</span>}{!!week.resources_need_review && <p className="small muted">⚠ {week.resources_need_review} material{week.resources_need_review === 1 ? " needs" : "s need"} parsing review</p>}{!!week.parsing_reports_unavailable && <p className="small muted">{week.parsing_reports_unavailable} parsing reports unavailable</p>}</div><span className="arrow" aria-hidden="true">↗</span></Link>)}</div> : <Empty title="No modules yet">Sync this course to bring in its Canvas modules.</Empty>}
    </section>
  </>;
}
