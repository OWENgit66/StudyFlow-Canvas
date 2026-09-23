# Public parsing and knowledge validation summary

This summary omits private course names, filenames, source text, generated learning content and page-specific findings. Detailed live-validation reports and screenshots stay local and are excluded from Git. The [V1 release record](v1-release.md) describes the completed workflow; historical phase counts below are not new test runs.

## PDF parsing and quality

The live validation checked physical PDF page numbers, preserved titles and bullet order, chunk boundaries, database provenance and unchanged source files. Structured PyMuPDF extraction preserves raw text, cleaned text and span metadata in parsing results. Layout warnings identify possible superscript/subscript loss, unusual symbol positioning, empty/scanned pages and replacement characters. The parser never guesses or repairs formulas.

Repeated header/footer removal is conservative: candidates must lie in the outer 8% of the page, use a font no larger than 80% of the median body size, contain at most 100 characters, share a normalized position, and occur on at least three pages and 70% of the document. Normal text requires at least eight characters and two words. Visual page-number removal additionally requires agreement with the physical PDF page. Ambiguous matches and text repeated in the body are kept; source page metadata remains intact.

The original parsing suite reached 174 passed and one skipped test; the quality update reached 192 passed and one skipped test. Coverage includes raw-text preservation, layout metadata, Unicode warnings, conservative margin cleanup, safe paths, transaction rollback and chunks that never cross pages. See [parser documentation](documents.md) and [parsing health UI](parsing-health.md).

## AI knowledge safeguards

Live validation exposed limitations beyond JSON validity: valid citations alone do not prove support, model review can miss unsupported claims, and flattened mathematics can be misinterpreted. Subsequent updates added application-owned evidence, bounded semantic review, warning-aware prompt copies, per-item filtering and deterministic checks for unreadable operators and incomplete equations. Original PDFs and stored chunks were preserved.

Offline replay confirmed the identified symbolic failure modes were blocked before semantic review. Ordinary automated tests use independently authored synthetic fixtures, isolated databases and mocked providers. The final Phase 5 suite reached 413 passed, one skipped and zero failed tests. The skip reflects Windows symlink permissions. No result is presented as proof of semantic correctness; users can consult original source pages.

The later authorized V1 workflow passed single-resource generation, persistence, source navigation and unchanged-file sync checks. Public aggregate results are in the [V1 release record](v1-release.md); implementation details are in [AI knowledge](ai-knowledge.md). Private reports are deliberately absent from a source checkout.
