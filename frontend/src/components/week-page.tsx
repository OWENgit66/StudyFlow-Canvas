"use client";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useData } from "@/lib/use-data";
import { Breadcrumbs, Empty, Loading, LoadError } from "./page-state";
import { LearningContent, type LearningResource } from "./learning-content";
import { ResourceItem } from "./resource-item";
import { SyncButton, SyncFeedback, useSync } from "./sync";

export function WeekPage({ id }: { id: number }) {
  const sync = useSync();
  const [selected, setSelected] = useState("");
  const load = useCallback(async () => {
    const [week, resources] = await Promise.all([api.week(id), api.resources(id)]);
    const [course, entries] = await Promise.all([api.course(week.course_id), Promise.all(resources.map(async resource => {
      try { return { resource, response: await api.knowledge(resource.id) } as LearningResource; }
      catch { return { resource, response: null, error: true } as LearningResource; }
    }))]);
    return { week, course, resources, entries };
  }, [id]);
  const state = useData(load, `${sync.result?.id ?? ""}:${sync.result?.status ?? ""}`);
  if (state.loading) return <Loading label="this module" />;
  if (state.error || !state.data) return <><Breadcrumbs items={[]} /><LoadError message="Could not load this module. Please check the backend connection." retry={state.retry} /></>;
  const { week, course, resources, entries } = state.data;
  const parsingReviewCount = resources.filter(r => r.parsing_health?.status === "review" || r.parsing_health?.status === "unable_to_parse").length;
  const selectedResource = resources.find(resource => String(resource.id) === selected && resource.canvas_file_id);
  const scope = { course_id: course.id, ...(week.canvas_module_id ? { module_id: week.canvas_module_id } : {}), ...(selectedResource ? { file_id: selectedResource.canvas_file_id! } : {}) };
  return <>
    <Breadcrumbs items={[{ label: course.code, href: `/courses/${course.id}` }, { label: week.title }]} />
    <div className="page-heading"><div><p className="eyebrow">{course.code} · LEARNING NOTES</p><h1>{week.title}</h1><p className="muted">{course.name}</p></div><a className="button secondary" href="#materials">Original materials <span aria-hidden="true">↓</span></a></div>
    <div className="module-toolbar"><p className="small muted">{resources.length} original materials · Sources stay close to every idea.</p>
      {!!week.canvas_module_id && !!course.canvas_course_id && <div className="module-sync"><label className="sr-only" htmlFor="sync-material">Sync scope</label><select id="sync-material" value={selected} disabled={sync.busy} onChange={event => setSelected(event.target.value)}><option value="">All materials in this module</option>{resources.filter(resource => resource.canvas_file_id).map(resource => <option key={resource.id} value={resource.id}>{resource.filename}</option>)}</select><SyncButton scope={scope} /></div>}
    </div>
    {(sync.busy || sync.result || sync.error) && <SyncFeedback />}
    {entries.some(entry => entry.error) && <div role="alert" className="inline-error">Some learning notes could not be loaded. Your original materials are still available. <button onClick={state.retry} className="text-link">Try again</button></div>}
    <div className="learning-layout"><aside className="page-index"><p className="eyebrow">IN THIS MODULE</p><a href="#overview">Overview</a>
      {([ ["concepts", "Key concepts"], ["key_points", "Key points"], ["formulas", "Formulas"], ["examples", "Examples"], ["exam_focus", "Exam focus"], ["questions", "Practice questions"] ] as const).filter(([key]) => entries.some(entry => entry.response?.stale === false && (key === "formulas" ? entry.response.extraction.knowledge.formulas.some(formula => formula.reliable === true) : entry.response.extraction.knowledge[key].length))).map(([key, title]) => <a href={`#${key.replace("_", "-")}`} key={key}>{title}</a>)}
      <a href="#materials">Original materials</a></aside><div className="learning-main">
      <LearningContent entries={entries} />
      <section className="learning-section" id="materials"><div className="section-heading"><h2>Original materials</h2><span className="count">{resources.length}</span></div><p className="section-note muted">Go back to the lecture. Read in context.</p>
        {parsingReviewCount > 0 && <p className="small muted">Parsing review: {parsingReviewCount} material{parsingReviewCount === 1 ? " needs" : "s need"} attention</p>}
        {resources.length ? <div className="resource-list">{resources.map(resource => <ResourceItem key={resource.id} resource={resource} />)}</div> : <Empty title="No materials here yet">Sync this module to bring in its course files.</Empty>}
      </section>
    </div></div>
  </>;
}
