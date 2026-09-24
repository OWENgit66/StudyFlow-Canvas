# Canvas Page-linked materials

Module items of type `Page` now contribute files to the existing sync pipeline. Direct `File` items retain the same behavior. Page HTML itself is not parsed into DocumentChunks or sent to an LLM.

## Discovery and ownership

`CanvasService.get_page(course_id, page_url_or_id)` uses the official `GET /api/v1/courses/:course_id/pages/:url_or_id` endpoint. String locators are Page slugs; integer locators use `page_id:<id>` to avoid ambiguity with numeric slugs. Locked, missing-body and malformed responses fail safely.

Python's standard-library `HTMLParser` extracts anchor references without rendering HTML or executing scripts. It recognizes same-origin Canvas file/attachment/download routes, file-browser preview IDs, `data-api-endpoint`, and same-origin `data-file-id` attributes. Relative links and HTML entities are resolved. Scripts, forms, styles and templates are ignored; embedded viewers and Page navigation are not crawled. HTML size and link count are bounded.

Canvas references resolve through the existing `get_file()` method. Their canonical file ID remains the Resource identity, irrespective of whether discovery came from a direct File item, one Page or several Pages/Modules. A file is processed once per sync. Its first discovered Module owns a new Resource; existing Resources retain their owner. Safe sync event metadata records the discovery method and source Page title. The same semester/course/module storage paths, download handling, DocumentService and KnowledgeService are reused.

## Incremental behavior

Canvas file `updated_at`, rather than Page modification time, determines NEW / UPDATED / UNCHANGED. Editing Page prose does not reprocess an unchanged completed file. Existing resume behavior for incomplete Resources remains available.

## Core teaching materials and readings

The shared `MaterialClassifier` applies to direct File items and Page-discovered files. It uses Module/Item/Page titles, anchor text, nearby headings and paragraph/list-item text, plus canonical filename/display name when metadata is needed. It does not inspect document contents or infer a role from `.pdf`.

| Classification | Default action |
| --- | --- |
| `CORE_MATERIAL` | Existing download/parse/AI pipeline |
| `READING_MATERIAL` | Intentionally skip; no download, parsing, chunks or AI |
| `UNKNOWN` | Preserve existing processing behavior and report for review |

Explicit reading/reference phrases take precedence over core phrases, including when the same file has multiple discovery contexts. This is deterministic regardless of link order. Existing ownership and canonical-ID deduplication remain unchanged. Generic filenames such as `Chapter 6.pdf` are UNKNOWN without context; a reading Page/Module makes them READING, while an explicit lecture context can make them CORE. `Book Chapter` is an explicit reading label.

This is a configurable phrase heuristic, not a semantic assessment: a teaching topic containing words like "reading" or "paper" can be conservatively marked READING. Sync events record matched field/phrase reasons for review. Nearby context is bounded; unrelated Page prose is not treated as a global keyword bag. Classification cannot resolve every ambiguous layout or label.

`MATERIAL_IGNORE_READINGS=true` is the default. Optional `MATERIAL_CORE_TERMS` and `MATERIAL_READING_TERMS` replace the built-in pipe-separated literal phrase lists; omit these settings to retain the defaults shown in `.env.example`. A deliberate `MATERIAL_IGNORE_READINGS=false` opts readings into normal processing while retaining their classification. No local `.env` file is modified automatically.

Known readings are skipped before metadata requests, so an inaccessible reading link does not become a file failure. Filename-only reading evidence is checked immediately after metadata retrieval, before timestamp/lock checks or Resource mutations. Ignoring a previously processed Resource does not delete its existing files, chunks or knowledge, locally or on Canvas.

Sync details include `core_materials_discovered`, `reading_materials_discovered`, `ignored_reading_materials` and `unknown_materials`. These count unique classified file identities, not anchor occurrences. Ignored readings increment `files_skipped` and receive an `ignored_reading_material` event; they do not increment `files_failed`. Each event includes `material_classification` and safe `classification_reasons`. Files whose metadata cannot be resolved and have no explicit reading context retain the existing error behavior; they are not silently counted as classified.

External direct PDFs use separate nullable Resource fields: `external_source_key` and `external_revision`. An additive, idempotent SQLite upgrade adds these fields to existing databases. No external identity is stored in `canvas_file_id`.

The source key hashes the normalized full HTTPS URL, including its query and excluding its fragment. The revision hashes a strong ETag and/or valid Last-Modified value together with size. Signed-query rotation can produce a new identity; this conservative fallback does not claim to deduplicate different external URLs that happen to serve the same bytes. Raw external URLs are not persisted in Resources or sync diagnostics.

## External PDF boundaries

Only direct `.pdf` paths on public HTTPS port 443 are candidates. Discovery uses HEAD without downloading the body. A complete successful response must supply a bounded positive Content-Length, PDF/octet-stream content type and a reliable revision validator. Hosts that do not support this contract are reported as unsupported/unresolved.

External access never sends Canvas credentials, cookies or proxy credentials. Every redirect is revalidated; private, loopback, link-local and mixed public/private DNS answers are rejected. Connections pin a vetted public address while checking TLS against the original hostname. Downloads must match discovery metadata and begin with the PDF signature before the existing bounded storage writer publishes them. This transport uses Python's standard library and adds no dependency.

Drive/OneDrive share pages, external tools, arbitrary navigation and non-PDF external URLs are not downloaded. Canonical Canvas non-PDF files retain existing behavior: they may be stored, but the PDF-only parsing/AI pipeline marks them unsupported.

## Diagnostics and dry run

The existing SyncRecord `details` includes:

| Counter | Meaning |
| --- | --- |
| `pages_inspected` | Page Module Items attempted |
| `pages_loaded` | Accessible Page responses loaded |
| `page_links_found` | Recognized material-link occurrences, before deduplication |
| `page_linked_files_discovered` | Unique identities referenced by Pages |
| `page_files_resolved` | Unique Page-referenced Canvas Files with accessible canonical metadata |
| `page_links_unsupported` | Unsupported anchor references and rejected external candidates |
| `page_links_unresolved` | Page-referenced file metadata failures |

Unsupported counts include ordinary navigation links, not just unavailable course materials. Warnings preserve safe Page/Module identifiers without HTML, signed URLs or credential values. Page and file failures are isolated so other resources can continue.

Readings skipped from context do not need canonical metadata, so they can contribute to Page-linked discovery and ignored counts without contributing to `page_files_resolved`.

Use the existing `POST /api/sync?dry_run=true&background=true` with a local `course_id` to restrict discovery. Dry run reads Page bodies and file metadata, records classifications and sync diagnostics, and does not download materials, parse documents, call AI or create/update Resources. Semester filtering still precedes Module/Page processing. Review the resulting sync record before authorizing paid processing.

Automated tests mock all Canvas, external-download and AI interactions. Coverage includes canonical resolution, safe link handling, duplicates, ownership, unchanged/updated files, scope filtering, failure isolation, external transport boundaries and additive schema upgrades. Real-course evidence stays in ignored local data, outside public fixtures and documentation.

References: [Canvas Pages API](https://developerdocs.instructure.com/services/canvas/resources/pages), [Canvas endpoint attributes](https://developerdocs.instructure.com/services/canvas/basics/file.endpoint_attributes).
