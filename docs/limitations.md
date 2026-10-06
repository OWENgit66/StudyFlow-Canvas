# Known limitations

## Answers and evidence

- Valid JSON and real citation IDs do not prove sentence-level grounding. Models can overgeneralize or misinterpret cited material.
- Evidence Hit@K is not complete question coverage, answer quality or factual correctness.
- Context has at most five chunks. Needed steps may lie outside retrieval or conservative continuity rules.
- Continuity matches repeated headings/query vocabulary; different headings, short continuation text and language mismatch can prevent expansion. It does not infer missing topics.
- Plain-text formatting is a prompt instruction, not a hard rendering guarantee.
- Adjacent continuity passed tests/local preview and was subsequently validated in a real browser IDEA9106 Course Q&A smoke test, as confirmed by the user. This single-query acceptance does not guarantee sentence-level grounding.

## Documents and classification

- PDF extraction can lose mathematical layout, symbols, diagrams and reading order. Warnings do not reconstruct content; original files remain authoritative.
- OCR and PPTX/DOCX text parsing are not supplied. Manual classification organizes unsupported files but does not make their contents searchable.
- Classification confidence is heuristic. Naming variation remains ambiguous; manual override takes precedence.
- Source fingerprints/reports do not guarantee detection of files silently replaced outside the application workflow.

## Operations and privacy

- One local user and one backend worker; no authentication or hardened public-network deployment configuration.
- Existing process/SQLite handle work without distributed queues. Do not restart the backend during maintenance CLI indexing; startup treats remaining indexing flags as interrupted work.
- Cancellation is cooperative: an in-flight provider call or local indexing operation may finish before stopping.
- Local model caches are prepared separately and excluded from Git. Ordinary Ask/indexing does not silently download them.
- Knowledge generation, explicit LLM classification fallback and Q&A can send private text to a configured provider and incur fees. Local-first does not mean every operation stays offline.
- In-process cosine is suitable for the current local prototype; no high-concurrency/large-scale vector performance claim is made.

## Measurement

Classification regression has 30 samples; retrieval has ten questions from one course. Classification holdout is pending. Later multi-course/context work does not inherit an unseen accuracy estimate from frozen experiments.

Private Gold is not redistributed. Synthetic tests establish behavior, not representative real-world accuracy. See [evaluation](evaluation.md).
