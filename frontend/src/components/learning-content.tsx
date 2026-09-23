"use client";
import { useId, useState, type ReactNode } from "react";
import { fileURL } from "@/lib/api";
import type { Concept, KnowledgeResponse, Question, Resource } from "@/lib/types";

export function SourceReference({ resource, pages }: { resource: Resource; pages: number[] }) {
  return <div className="source-reference"><span>Source</span>{[...new Set(pages)].filter(page => Number.isInteger(page) && page > 0).map(page => resource.file_available
    ? <a key={page} href={fileURL(resource.id, page)} target="_blank" rel="noopener noreferrer">{resource.filename} · Page {page} <span aria-hidden="true">↗</span></a>
    : <span key={page}>{resource.filename} · Page {page} (file unavailable)</span>)}</div>;
}
export function ConceptCard({ concept, resource }: { concept: Concept; resource: Resource }) {
  return <article className="concept-card"><div className="concept-heading"><h3>{concept.name}</h3><span className="importance">{concept.importance} importance</span></div>
    {concept.definition && <p className="definition">{concept.definition}</p>}{concept.explanation && <p className="prose">{concept.explanation}</p>}<SourceReference resource={resource} pages={concept.source_pages} /></article>;
}
export function QuestionCard({ question, resource, number }: { question: Question; resource: Resource; number: number }) {
  const [open, setOpen] = useState(false);
  const answerId = useId();
  return <article className="question-card"><p className="eyebrow">QUESTION {String(number).padStart(2, "0")}</p><h3>{question.question}</h3>
    <button className="answer-button" aria-expanded={open} aria-controls={answerId} onClick={() => setOpen(!open)}>{open ? "Hide Answer" : "Show Answer"}<span aria-hidden="true">{open ? "−" : "+"}</span></button>
    <div id={answerId} hidden={!open} className="answer prose">{question.answer}</div><SourceReference resource={resource} pages={question.source_pages} /></article>;
}
function Section({ id, title, children, note }: { id: string; title: string; children: ReactNode; note?: string }) {
  return <section className="learning-section" id={id}><div className="section-heading"><h2>{title}</h2></div>{note && <p className="section-note muted">{note}</p>}{children}</section>;
}
export interface LearningResource { resource: Resource; response: KnowledgeResponse | null; error?: boolean }
export function LearningContent({ entries }: { entries: LearningResource[] }) {
  // Defense in depth: historical responses never reach any learning section.
  const current = entries.filter(entry => entry.response?.stale === false && entry.response.resource_id === entry.resource.id);
  const concepts = current.flatMap(({ resource, response }) => response!.extraction.knowledge.concepts.map(item => ({ item, resource })));
  const points = current.flatMap(({ resource, response }) => response!.extraction.knowledge.key_points.map(item => ({ item, resource })));
  const formulas = current.flatMap(({ resource, response }) => response!.extraction.knowledge.formulas.filter(item => item.reliable === true).map(item => ({ item, resource })));
  const examples = current.flatMap(({ resource, response }) => response!.extraction.knowledge.examples.map(item => ({ item, resource })));
  const exams = current.flatMap(({ resource, response }) => response!.extraction.knowledge.exam_focus.map(item => ({ item, resource })));
  const questions = current.flatMap(({ resource, response }) => response!.extraction.knowledge.questions.map(item => ({ item, resource })));
  if (!current.length) return <section className="knowledge-empty" id="overview"><span className="eyebrow">LEARNING CONTENT</span><h2>Your materials come first.</h2><p>No current learning notes are available for this module yet. You can read the original materials below.</p><p className="small muted">Older notes are kept out of view when they no longer match the current material or quality checks.</p></section>;
  return <>
    <Section id="overview" title="Overview">{current.map(({ resource, response }) => <div className="overview" key={resource.id}>{current.length > 1 && <p className="small muted">{resource.filename}</p>}<p className="prose">{response!.extraction.knowledge.overview}</p></div>)}</Section>
    {!!concepts.length && <Section id="concepts" title="Key concepts"><div className="concept-grid">{concepts.map(({ item, resource }, index) => <ConceptCard key={`${resource.id}-${index}`} concept={item} resource={resource} />)}</div></Section>}
    {!!points.length && <Section id="key-points" title="Key points"><ul className="learning-bullets">{points.map(({ item, resource }, index) => <li key={index}><p className="prose">{item.content}</p><SourceReference resource={resource} pages={item.source_pages} /></li>)}</ul></Section>}
    {!!formulas.length && <Section id="formulas" title="Formulas">{formulas.map(({ item, resource }, index) => <article className="formula-card" key={index}><pre>{item.formula}</pre>{item.explanation && <p className="prose">{item.explanation}</p>}<SourceReference resource={resource} pages={[item.source_page]} /></article>)}</Section>}
    {!!examples.length && <Section id="examples" title="Examples">{examples.map(({ item, resource }, index) => <article className="example" key={index}><p className="prose">{item.description}</p><SourceReference resource={resource} pages={item.source_pages} /></article>)}</Section>}
    {!!exams.length && <Section id="exam-focus" title="Exam focus" note="Explicit assessment cues found in these materials. This is not a prediction of exam content."><ul className="learning-bullets">{exams.map(({ item, resource }, index) => <li key={index}><p>{item.content}</p><SourceReference resource={resource} pages={item.source_pages} /></li>)}</ul></Section>}
    {!!questions.length && <Section id="questions" title="Practice questions" note="Pause, think it through, then reveal the answer.">{questions.map(({ item, resource }, index) => <QuestionCard key={`${resource.id}-${index}`} question={item} resource={resource} number={index + 1} />)}</Section>}
  </>;
}
