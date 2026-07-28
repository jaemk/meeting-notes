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
| Run cost and durability | done | [run-cost-and-durability.md](run-cost-and-durability.md) |
| Command-line surface | pending | [command-line-surface.md](command-line-surface.md) |
| Splice boundary de-duplication | pending | [splice-boundary-de-duplication.md](splice-boundary-de-duplication.md) |
| Speaker attribution | done | [speaker-attribution.md](speaker-attribution.md) |
| Speaker naming | done | [speaker-naming.md](speaker-naming.md) |
| Spelling glossary | done | [spelling-glossary.md](spelling-glossary.md) |
| Smear cluster identification | research | [smear-cluster-identification.md](smear-cluster-identification.md) |

## What `done` does and does not promise

`done` means implemented and covered by tests, and most rows earn it: the
chunking, merge, detection, repair and readable-document specs are exercised by
`test_transcribe.py`, `test_repair.py`, `test_readable.py` and
`test_prompt.py`. Some statements inside otherwise-`done` features are
**verified by reading, not by a test**, because they are Makefile recipes or
shell, and nothing in the suite runs `make` or `setup.sh`:

- `ANALYZE-1` … `ANALYZE-6` — `make analyze`'s wiring (the prompt rendering
  itself, `ANALYZE-7`, *is* tested).
- `DOC-6`, `DOC-7`, `DOC-8` — the two-step `make readable`, its empty-summary
  check and `NO_SUMMARY=1`. `DOC-1` … `DOC-5` and `DOC-9` are `readable.py` and
  are tested.
- `BACKEND-1`, `BACKEND-5` … `BACKEND-9` and `FILES-7`, `FILES-9`, `FILES-10` —
  `setup.sh`, `.gitignore` and the `clean`/`distclean` recipes.
- `COST-1` … `COST-6` — statements about what a run costs and what an
  interruption loses. `COST-4` describes current behaviour that no test
  asserts.
- `SPEAKER-19`'s `diarize.py run` half — loading pyannote and calling it.
  `test_diarize.py` stubs the pipeline so the suite needs no model, no GPU and
  no network, which means the assignment logic in `SPEAKER-21` … `SPEAKER-25`
  is tested and the model call is not. `SPEAKER-5` … `SPEAKER-18` and
  `SPEAKER-26` … `SPEAKER-31` are measured findings about one recording rather
  than assertions about code, and no test re-derives them — `SPEAKER-26`'s
  choice of 0.7 is asserted as the shipped default, but the reading that chose
  it is not reproducible from the fixture.
- `NAME-18`'s middle step — handing the candidates to Claude. `test_names.py`
  covers the gathering and the validation on either side of it, and feeds
  `ingest` answers by hand, so the two halves that can be wrong silently are
  tested and the model call is not. `NAME-3` … `NAME-7` are measured findings
  about one recording. `CHUNK-7` … `CHUNK-12` likewise: the chunk-length
  experiment is recorded, not re-run, and `make test` decodes nothing.
- `make pipeline` and `make names` as recipes, like every other `make` target
  here. The `/transcribe` skill in `.claude/skills/` is documentation of the
  running order and is verified by reading it.

Treat those as documented intent that a change can break without turning the
suite red. Reviewing them means reading the recipe.

## Conventions

- Each normative statement carries a stable ID (e.g. `FEAT-1`, `API-3`). IDs are
  append-only: retire an ID by marking it removed, never reuse the number.
- Specs are document-first: a feature is documented (status `pending`, or
  `research` if it needs design work) before implementation begins. Flip to
  `done` only once implemented and verified.
- Spec files are named `<slug>.md` and linked from the table above.
