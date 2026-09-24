# V2.1 Resource classification

V1 remains the stable foundation. Resources now carry an educational `resource_type`: `lecture`, `tutorial`, or `other`. This is separate from the existing CORE/READING/UNKNOWN processing policy; readings are still intentionally ignored by default.

## Storage and migration

One non-null Resource column is added with a database and application default of `other`, constrained to the three supported values. The existing idempotent SQLite startup upgrade uses `ALTER TABLE ADD COLUMN`. It does not recreate tables or the database, change identifiers or paths, or delete chunks/knowledge. Repeated startup preserves assigned roles.

Existing V1 Resources initially become `other`. Migration does not guess roles from incomplete historical metadata or contact Canvas. New ordinary syncs classify discovered resources; an unchanged file can receive a role update without downloading, parsing or calling AI. The metadata-only update preserves `updated_at` and Canvas timestamps, so current knowledge remains current. Dry runs never persist role changes. Ignored readings remain untouched.

## Central rules

The existing `services/material_classification.py` owns the deterministic role helper. It looks for whole words `lecture`/`lectures` and `tutorial`/`tutorials`, plus separated `LEC`/`TUT` labels. Normalization handles case, Unicode, underscores and punctuation. It does not read PDFs or use an LLM.

Evidence priority is:

1. Canonical filename and display name.
2. Module Item title and link text.
3. Page title.
4. Module title.
5. Nearby Page text retained by the existing safe HTML extractor.

The minimal V2.2a conflict guard treats the first three levels as direct signals. Explicit assignment, assessment, homework or reading intent (including plural labels and numeric suffixes such as `Assignment1`) contributes `other` evidence at the Module level. It suppresses Module/nearby-only inference, but cannot override an explicit Lecture/Tutorial filename, item/link title or Page title. Module and nearby inference remain available when this conflict is absent. These are deterministic priorities, not confidence scores. The evidence survives duplicate discovery merging; the separate reading-download policy is unchanged.

One unambiguous role at the strongest matching level wins. Conflicting roles at that level, or no matching role, yield `other`. Duplicate discoveries merge evidence before classification, preserving canonical file identity and first-owner Module behavior. A specific tutorial filename can override a broad Page named "Lecture and Tutorial". An ambiguous filename can inherit "Week 5 Tutorial" from its Page. Slides, exercises, workshop, lab and generic chapter names alone remain `other`; no new categories or semantic guesses are introduced.

## API and interface

`ResourceCreate`/`ResourceRead` and `StudyResource` expose the constrained field with a backward-compatible default. `GET /api/weeks/{week_id}/resources` returns `resource_type`; sync discovery events also include the selected role. No new endpoint is needed.

Original Materials on the Week page displays a compact textual Lecture, Tutorial or Other material label. Lecture and Tutorial also have distinct colors. File links, parsing-health disclosure, knowledge presentation and the Dashboard remain unchanged. Older responses without the field render as Other material.

## Validation and boundaries

Synthetic tests cover filenames, Page/Module context, conflict handling, migration preservation/idempotence, API serialization, direct/Page-linked sync, dry-run non-mutation and unchanged-file classification without reprocessing or knowledge invalidation. Frontend tests cover labels and original file links.

This phase does not backfill old roles automatically, redesign the learning interface, change knowledge prompts, call real providers, sync Canvas, create embeddings, add RAG or generate page screenshots.
