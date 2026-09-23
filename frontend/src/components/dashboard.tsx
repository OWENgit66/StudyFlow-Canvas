"use client";
import Link from "next/link";
import { api } from "@/lib/api";
import { useData } from "@/lib/use-data";
import type { CourseCardData } from "@/lib/types";
import { Empty, Loading, LoadError } from "./page-state";
import { SyncButton, SyncFeedback, useSync } from "./sync";

export function CourseCard({ course, semester }: { course: CourseCardData; semester: string }) {
  return <Link className="course-card" href={`/courses/${course.id}`}>
    <div className="card-top"><span className="eyebrow">{course.code}</span><span className="arrow" aria-hidden="true">↗</span></div>
    <h3>{course.name}</h3><p className="muted small">{semester}</p>
    <div className="course-counts"><span><strong>{course.module_count}</strong> modules</span><span><strong>{course.parsed_resource_count}</strong> parsed materials</span><span><strong>{course.current_knowledge_count ?? 0}</strong> current learning notes</span></div>
    <div className="card-latest"><span className="small muted">Latest module</span><span>{course.latest_module ?? "No modules yet"}</span></div>
  </Link>;
}
export function Dashboard() {
  const sync = useSync();
  const state = useData(api.dashboard, `${sync.result?.id ?? ""}:${sync.result?.status ?? ""}`);
  if (state.loading) return <Loading label="your courses" />;
  if (state.error || !state.data) return <LoadError message="Could not load your courses. Check that the backend is running." retry={state.retry} />;
  const { courses, latest_sync, active_semester: semester } = state.data;
  const visible = courses.filter(c => c.semester_id === semester?.id);
  return <>
    <div className="hero"><div><p className="eyebrow">YOUR LEARNING SPACE</p><h1>Your courses,<br /><em>connected.</em></h1><p className="hero-description">A place for your materials, the ideas that matter,<br className="desktop-break" /> and the sources behind them.</p></div>
      <div className="semester-panel"><span className="eyebrow">CURRENT SEMESTER</span>
        <h2>{semester?.name ?? "No active semester configured"}</h2>
        <p className="small muted">Only courses in your current Canvas term are synced.</p><SyncButton disabled={!semester} scope={semester ? { semester_id: semester.id } : {}} />
      </div></div>
    <SyncFeedback previous={latest_sync} />
    <section className="course-section"><div className="section-heading"><h2>My courses <span className="count">{visible.length}</span></h2><span className="small muted">Your semester, at a glance</span></div>
      {semester && visible.length ? <div className="course-grid">{visible.map(course => <CourseCard key={course.id} course={course} semester={semester.name} />)}</div> : <Empty title="Your courses will feel at home here.">No course materials have been synced yet. Use Sync Canvas to get started.</Empty>}
    </section>
    <p className="reading-note"><span aria-hidden="true">↳</span> Start with a course. Explore a module. Follow an idea back to its source.</p>
  </>;
}
