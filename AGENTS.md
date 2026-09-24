# StudyFlow — AI Development Instructions

This file defines the development rules for AI coding agents working on
StudyFlow.

All coding agents must read and follow this file before modifying the
repository.

---

# 1. Project Vision

StudyFlow is a personal AI-powered university learning system.

Its purpose is to transform university course materials into a structured,
searchable and source-grounded learning environment.

StudyFlow should help the user:

- automatically sync course materials from Canvas LMS
- organize materials by semester, course and week/module
- understand lecture concepts
- learn from tutorials and worked examples
- preserve original slide/page context
- identify document parsing problems
- ask questions grounded in original course materials
- always trace generated knowledge back to its source

StudyFlow is not intended to be a generic LMS or social learning platform.

---

# 2. Current Project Status

## StudyFlow V1 — COMPLETE / STABLE

V1 already provides:

Canvas LMS integration

→ active-semester filtering

→ incremental material sync

→ human-readable materials storage

→ PDF parsing

→ page-level extraction

→ document chunking

→ parsing-quality warnings

→ LLM structured knowledge extraction

→ source/chunk provenance validation

→ formula and symbolic safety filtering

→ semantic grounding

→ SQLite persistence

→ course / week learning interface

→ source-page links

→ parsing-health UI

→ Canvas sync progress UI

→ local Windows launcher

V1 should now be treated as a stable foundation.

Do not redesign or rewrite V1 architecture unless:

1. a reproducible bug exists, or
2. a V2 requirement genuinely requires a small backward-compatible change.

Prefer extending V1 over replacing it.

---

# 3. StudyFlow V2 Goals

V2 extends StudyFlow in four major directions.

## 3.1 Resource Classification

Course resources should be classified into learning roles such as:

- lecture
- tutorial
- lab
- workshop
- reading
- other

The initial V2 implementation should prioritize:

- lecture
- tutorial
- other

Do not introduce unnecessary resource categories before they are needed.

---

## 3.2 Visual Course Material

PDF pages may contain important information that cannot be represented
reliably as extracted text.

Examples:

- flow diagrams
- architecture diagrams
- protocol diagrams
- charts
- timelines
- tables
- mathematical layouts
- annotated figures

V2 should preserve page-level visual context.

The intended model is approximately:

Resource
→ DocumentPage
→ DocumentChunk

DocumentPage may contain:

- resource_id
- page_number
- cleaned_text
- screenshot_path
- parsing warnings
- has_visual
- visual metadata

The original slide/page remains the source of truth.

AI-generated visual descriptions must never replace the original slide.

---

## 3.3 Lecture and Tutorial Separation

Lecture and Tutorial resources have different educational roles.

Lecture materials should focus on:

- concepts
- definitions
- theory
- architecture
- processes
- formulas
- key ideas

Tutorial materials should focus on:

- problems
- exercises
- worked examples
- solution steps
- techniques
- common mistakes
- practice

Do not process Lecture and Tutorial resources with identical knowledge
extraction prompts once V2 separation is implemented.

---

## 3.4 Retrieval-Augmented Generation

V2 will introduce RAG.

The first RAG implementation must be:

# Course-scoped RAG

Example:

User opens COMP9121

→ asks a question

→ retrieval searches only COMP9121

→ relevant DocumentChunks are retrieved

→ LLM answers using only retrieved course material

→ answer contains source references

Do not begin with global cross-university retrieval.

Course-level retrieval must work reliably first.

---

# 4. RAG Source of Truth

RAG must retrieve from:

DocumentChunk

and original course material.

Do NOT use AI-generated summaries as the primary retrieval source.

Correct architecture:

Question
→ query embedding
→ DocumentChunk retrieval
→ source validation
→ LLM answer
→ citations

Incorrect architecture:

Question
→ search AI summary
→ answer

AI-generated Summary / Concept / TutorialKnowledge may be used as
secondary metadata but not as the primary source of truth.

---

# 5. RAG Citations

Every RAG answer should preserve source attribution whenever possible.

Example:

Answer

...

Sources:

Lecture Week 2
Page 21

Tutorial Week 2
Page 4

The user should be able to open the original material.

Never invent:

- page numbers
- resource names
- chunk IDs
- citations

Source IDs returned by the model must be validated against actual
retrieved chunks.

---

# 6. V2 Development Order

V2 must be developed incrementally.

Follow this order unless there is a strong technical reason not to.

## V2.1 — Resource Classification

Implement:

lecture
tutorial
other

Then expand only when required.

---

## V2.2 — DocumentPage and Visual Preservation

Add page-level representation.

Support:

- page screenshot generation
- page text
- parsing warnings
- visual flag

Do not introduce Vision AI yet unless explicitly requested.

---

## V2.3 — Separate Lecture / Tutorial Knowledge Pipelines

Lecture:

- concepts
- theory
- definitions
- formulas
- architecture

Tutorial:

- problems
- examples
- solutions
- steps
- mistakes

---

## V2.4 — Embeddings and Vector Retrieval

Create embeddings from DocumentChunks.

Do not embed AI-generated summaries as the primary knowledge source.

Metadata should include enough information to filter by:

- course
- week
- resource
- resource_type
- page

---

## V2.5 — Course RAG

Implement:

Ask this course

with:

- retrieval
- grounded generation
- source citations

---

## V2.6 — Multimodal RAG

Only after text RAG works reliably.

For visually important retrieved pages:

DocumentChunk
+
DocumentPage screenshot

→ Vision-capable model

→ answer

Do not send every course page to a Vision model by default.

---

# 7. Current Technology Stack

Unless a strong reason exists, preserve the current stack.

Frontend:

- Next.js
- TypeScript
- Tailwind CSS

Backend:

- Python
- FastAPI

Current database:

- SQLite

V2 may migrate to:

- PostgreSQL
- pgvector

but only when the RAG/vector phase actually requires it.

Do not migrate databases early merely because pgvector may be useful
later.

Document Processing:

- PyMuPDF

AI:

- LLMProvider abstraction
- OpenAIProvider
- DeepSeekProvider

Do not tightly couple StudyFlow business logic to one AI vendor.

---

# 8. Provider Abstraction

AI features must use the existing provider abstraction.

Business services should not directly instantiate vendor clients.

Correct:

KnowledgeService
→ LLMProvider

RAGService
→ LLMProvider

Incorrect:

KnowledgeService
→ direct DeepSeek SDK calls

Provider switching should remain configuration-driven.

---

# 9. Canvas Responsibilities

CanvasService is responsible for:

- Canvas API communication
- authentication
- course discovery
- module discovery
- file discovery
- page retrieval
- file metadata
- downloads

CanvasService must NOT:

- parse PDFs
- generate AI knowledge
- create embeddings
- answer RAG questions

Keep service boundaries clear.

---

# 10. Canvas Pages

Some courses place lecture materials inside Canvas Pages rather than
direct File Module Items.

StudyFlow should support:

Module
→ Page
→ Canvas-hosted course file
→ existing Resource pipeline

Prefer resolving Page-linked Canvas files to their canonical Canvas File
object.

Use canvas_file_id when available.

Do not create duplicate Resources when the same file appears:

- directly in a Module
- inside a Canvas Page
- in multiple Pages

---

# 11. Reading Material Filtering

Supplementary reading materials should not be processed by default.

Examples:

- Required Reading
- Recommended Reading
- Journal Article
- Research Paper
- Book Chapter
- Further Reading
- Supplementary Reading

Classify materials where practical as:

CORE_MATERIAL
READING_MATERIAL
UNKNOWN

Default:

CORE_MATERIAL
→ process

READING_MATERIAL
→ ignore intentionally

UNKNOWN
→ handle conservatively and report

Do not count intentionally ignored reading materials as failures.

Use context such as:

- filename
- Module Item title
- Canvas Page title
- surrounding link text

Do not classify solely by file extension.

---

# 12. Semester Scope

Normal Canvas sync should process only the active semester.

Filtering should occur BEFORE expensive module/file/page processing.

Historical courses may remain in the database.

Historical materials should not be automatically deleted.

Do not hard-code a semester throughout the codebase.

Use one centralized active-semester source of truth.

---

# 13. Document Parsing Safety

Existing V1 parsing safeguards must remain.

Preserve:

- page numbers
- parsing warnings
- formula-layout warnings
- unreadable symbol detection
- scanned-page detection
- source provenance

Never guess missing formulas or unreadable symbols.

The original PDF remains authoritative.

---

# 14. DocumentPage Rules

V2 page screenshots must:

- correspond to the correct Resource
- preserve human-readable page numbering
- be generated deterministically
- remain linked to the original PDF page

Avoid duplicating full PDF files unnecessarily.

Screenshot storage should be configurable and organized.

Do not commit generated private slide screenshots to Git.

---

# 15. Visual Processing Rules

Do not automatically call a Vision model for every page.

Preferred strategy:

PDF
→ deterministic extraction
→ page screenshot
→ visual detection
→ only selected pages use Vision when required

Use expensive AI only when it adds meaningful value.

---

# 16. Embedding Rules

Embeddings should represent original DocumentChunk content.

Each embedding must remain traceable to:

- chunk_id
- resource_id
- page_number
- course
- week/module
- resource_type

Store the embedding model/version.

If embedding models change, the system should be able to identify stale
embeddings.

---

# 17. Vector Search

Do not mix retrieval logic directly into API route handlers.

Use a dedicated abstraction such as:

RetrievalService

or equivalent existing architecture.

Responsibilities:

Query
→ embedding
→ metadata filtering
→ vector search
→ ranked chunks

Generation belongs elsewhere.

---

# 18. Course RAG Rules

Initial RAG must default to one Course.

Example:

course_id = 12

Search only that course.

Future global search may be added later.

Do not silently search unrelated courses unless the UI clearly requests
cross-course search.

---

# 19. Lecture / Tutorial Retrieval

Resource type should become retrieval metadata.

Initial retrieval may search both.

Future ranking may prioritize:

Concept questions
→ Lecture

Problem-solving questions
→ Tutorial

Do not implement complex intent classification before basic RAG works.

---

# 20. Hallucination and Grounding

Existing V1 grounding principles remain mandatory.

LLMs must not be trusted to invent:

- facts
- formulas
- citations
- page numbers
- source IDs

RAG output must use only supplied retrieved material.

If evidence is insufficient:

the system should say that the available course material does not provide
enough evidence.

Do not answer from general model knowledge while pretending it came from
the course.

---

# 21. Frontend V2 Information Architecture

Keep the existing hierarchy:

Dashboard
→ Course
→ Week / Module

Within a Week:

Lecture
Tutorial
Resources

should become visibly separate where data exists.

Example:

Week 5

Lecture
- Overview
- Concepts
- Slide visuals
- Formulas

Tutorial
- Exercises
- Worked examples
- Solutions

Original Materials

Ask StudyFlow

Do not overload the main Dashboard with low-level information.

---

# 22. Parsing Health UI

Keep the existing progressive disclosure model.

Dashboard:
no detailed parsing warnings

Course:
week/resource aggregate status

Week:
resource health

Resource review:
exact pages and warning types

This behavior should not regress.

---

# 23. Sync Progress UI

Keep current live sync progress features.

The user should be able to see:

- current course
- current module
- current resource
- current processing stage
- overall progress
- completed
- skipped
- failed
- processing

Do not regress to a static:

"Syncing Canvas..."

message.

---

# 24. V1 Backward Compatibility

V2 migrations must preserve:

- existing Resources
- existing DocumentChunks
- current Knowledge
- Canvas file identity
- source page links
- stale/current knowledge behavior
- materials paths

Do not destroy V1 user data during migrations.

If a destructive migration is genuinely necessary:

stop and explain before executing it.

---

# 25. Database Migrations

V2 introduces more persistent structures.

Do not casually delete and recreate the database.

Use proper migration strategy when schema changes become meaningful.

Before migrations:

inspect current schema and existing data.

Protect user data.

---

# 26. Secrets

Never hard-code or commit:

- Canvas tokens
- DeepSeek API keys
- OpenAI API keys
- database credentials

Use environment variables.

Never log full secrets.

---

# 27. Private University Content

Do not commit:

- downloaded course PDFs
- screenshots of private course materials
- extracted private course content
- SQLite databases containing course text
- private validation reports

Keep `.gitignore` protections intact.

---

# 28. Before Modifying Code

Every task must begin by:

1. Read AGENTS.md.
2. Inspect repository structure.
3. Inspect relevant existing files.
4. Check whether functionality already exists.
5. Review relevant tests.
6. Plan the smallest compatible change.

Do not assume the repository is empty.

---

# 29. Engineering Workflow

For every task:

Understand

→ Inspect

→ Plan

→ Implement

→ Run

→ Test

→ Fix

→ Verify

Never mark code complete merely because it was written.

When execution tools are available, actually run the implementation.

---

# 30. Do Not Duplicate Services

Before creating new:

- services
- schemas
- models
- components
- utilities

check whether the responsibility already exists.

Avoid:

service_v2.py
new_service.py
service_fixed.py

Extend existing architecture when practical.

---

# 31. Testing

New V2 functionality must include tests.

Automated tests must not rely on:

- real Canvas credentials
- paid DeepSeek/OpenAI calls
- private course files

Use:

- mocks
- fixtures
- temporary files
- test databases

Real integration testing should occur only after automated tests pass.

---

# 32. Paid AI Calls

Do not make real paid AI requests during ordinary automated testing.

Before a real provider test:

1. automated tests must pass
2. scope the test to one resource/query
3. avoid repeated paid calls
4. report usage when available

---

# 33. Performance and Cost

Avoid unnecessary AI usage.

Examples:

Do not:

- re-embed unchanged chunks
- re-run Vision on unchanged pages
- re-analyze unchanged resources
- regenerate knowledge unnecessarily

Use content identity/version information.

Incremental processing is a core StudyFlow principle.

---

# 34. Error Isolation

One failed Resource or Page should not destroy an entire Course sync.

One failed embedding should not delete valid DocumentChunks.

One failed Vision page should not invalidate unrelated pages.

Preserve completed work whenever safe.

---

# 35. Logging

Logs should help diagnose:

Canvas
Document parsing
Embeddings
Retrieval
AI generation
RAG
Sync

Never log:

API keys
Authorization headers
full sensitive documents unnecessarily

---

# 36. UI Philosophy

StudyFlow is a learning product.

The UI should be:

Clean
Minimal
Academic
Readable

Do not make it resemble an infrastructure/admin console.

Technical details should be progressively disclosed only when useful.

---

# 37. Scope Control

Do not spontaneously introduce:

- microservices
- Kafka
- Kubernetes
- Redis
- distributed queues
- GraphQL
- authentication systems
- social features

StudyFlow is currently a local single-user application.

Use the simplest architecture that reliably supports the feature.

---

# 38. V2 Stop Conditions

Do not implement all V2 features at once.

Each V2 phase must be completed, tested and reviewed before starting the
next one.

Current intended order:

V2.1 Resource Classification
V2.2 DocumentPage / Slide Visuals
V2.3 Lecture / Tutorial Pipelines
V2.4 Embedding / Retrieval
V2.5 Course RAG
V2.6 Multimodal RAG

Do not automatically proceed to the next phase after completing one.

---

# 39. Definition of Done

A task is complete only when:

- implementation exists
- relevant tests pass
- existing behavior has no obvious regression
- documentation is updated if necessary
- data safety is preserved
- private data is not exposed
- the feature was actually verified

---

# 40. Communication

After completing work, report briefly:

1. What changed
2. Which files changed
3. Architecture impact
4. Tests run
5. Test results
6. Real integration performed or not
7. Remaining limitations
8. Whether the requested phase is complete

Do not claim something works if it was not actually verified.

---

# 41. Core Principle

StudyFlow should grow incrementally from a stable V1.

Never sacrifice:

- source traceability
- data safety
- correctness
- maintainability

for faster feature expansion.

The goal is not to add the largest number of AI features.

The goal is to build a reliable learning system grounded in the user's
actual university course materials.