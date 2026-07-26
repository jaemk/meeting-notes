# Spec

Every feature is documented here before or as it lands, with its status.

## Feature status

Status values: `done` (implemented and covered by tests), `pending` (documented,
not yet built; the default), `research` (needs investigation or design before it
can be built). Keep each row's status current with `spec.py set`.

| Feature | Status | Spec |
|---------|--------|------|
| Chunked transcription | done | [chunked-transcription.md](chunked-transcription.md) |
| Chunk merge and seam clamping | done | [chunk-merge-and-seam-clamping.md](chunk-merge-and-seam-clamping.md) |
| Defect detection | done | [defect-detection.md](defect-detection.md) |
| Gap classification | done | [gap-classification.md](gap-classification.md) |
| Window repair | done | [window-repair.md](window-repair.md) |
| Seam overrun repair | done | [seam-overrun-repair.md](seam-overrun-repair.md) |
| Automatic repair after transcription | done | [automatic-repair-after-transcription.md](automatic-repair-after-transcription.md) |
| File layout and naming | done | [file-layout-and-naming.md](file-layout-and-naming.md) |
| Backend selection and setup | done | [backend-selection-and-setup.md](backend-selection-and-setup.md) |
| Readable document | done | [readable-document.md](readable-document.md) |
| Transcript analysis with Claude | done | [transcript-analysis-with-claude.md](transcript-analysis-with-claude.md) |
| Test fixtures and harness | done | [test-fixtures-and-harness.md](test-fixtures-and-harness.md) |
| Splice boundary de-duplication | pending | [splice-boundary-de-duplication.md](splice-boundary-de-duplication.md) |
| Speaker attribution | research | [speaker-attribution.md](speaker-attribution.md) |

## Conventions

- Each normative statement carries a stable ID (e.g. `FEAT-1`, `API-3`). IDs are
  append-only: retire an ID by marking it removed, never reuse the number.
- Specs are document-first: a feature is documented (status `pending`, or
  `research` if it needs design work) before implementation begins. Flip to
  `done` only once implemented and verified.
- Spec files are named `<slug>.md` and linked from the table above.
