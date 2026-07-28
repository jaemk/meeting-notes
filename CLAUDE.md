# Working in this repo

## What this project is

It turns a recording of a meeting into a document someone can act on: an
executive summary with owners and follow-ups, over a timestamped transcript
marked with who was speaking. Point it at an audio file, wait, and read
`output/<name>.readable.md`.

It exists because the obvious version does not work. Whisper on a two-hour
recording conditions on its own output and gets stuck repeating itself, drops
speech it cannot hear, and invents endings for chunks whose audio has run out.
So the pipeline is built around finding and repairing its own defects rather
than trusting the first pass, and around **declining to guess** — an unnamed
speaker, a reported gap and a flagged inconsistency are all correct outputs
here, and each is a place where a plausible fabrication would be worse than an
admission.

Nothing about it is specific to one meeting or one group.

## Where the reasoning lives

**`spec/` is the source of truth for intent.** Every behaviour is a numbered,
append-only statement, and the reasoning behind a default — including the
approaches that were measured and rejected — is recorded there rather than
here. [`spec/README.md`](spec/README.md) has the feature table and the status
of each one.

Read the spec for the area you are changing before you change it. Most of what
looks like an obvious improvement has already been tried; see
[Already tried, already ruled out](#already-tried-already-ruled-out).

This file is what an agent needs that a spec does not carry: the operational
constraints, the shape of the code, and where to look.

`README.md` is the user guide, written for a person setting this up.

## How it is driven

Day to day, the **`/transcribe` skill**
(`.claude/skills/transcribe/SKILL.md`) walks the steps in order and stops at
the two places a person has to look — gap triage and the summary. The skill is
the running order; the specs are why.

It is all `make` targets underneath, so it works without an agent: `make help`
lists them, and `make pipeline` runs everything end to end for a recording
already known to be clean.

Read `analyze.md` before reviewing a transcript output.

## The shape of the code

| file | does | spec |
|---|---|---|
| `transcribe.py` | chunks and merges | `chunked-transcription.md`, `chunk-merge-and-seam-clamping.md` |
| `repair.py` | finds defects and fixes them | `defect-detection.md`, `window-repair.md`, `seam-overrun-repair.md`, `gap-classification.md` |
| `diarize.py` | separates voices | `speaker-attribution.md` |
| `names.py` | puts names to voices where the transcript states one | `speaker-naming.md` |
| `glossary.py` | corrects proper nouns the decoder cannot know | `spelling-glossary.md` |
| `readable.py` | assembles the deliverable | `readable-document.md` |

`analyze.md`, `summarize.md` and `naming.md` are the prompts handed to Claude
for the judgement calls the rules cannot make.

## Hard constraints

These are not defaults to weigh. They are the things that damage something real
when they are got wrong.

- **Never run a Whisper decode inside the sandbox.** Every `transcribe.py` /
  `repair.py` invocation that decodes needs `dangerouslyDisableSandbox: true`.
  Analysis that only reads transcripts or measures audio with `ffmpeg` is fine
  sandboxed.
- **Always `.venv/bin/python`**, never the system interpreter.
- **Nothing from a real meeting goes in a commit** — not a name, a place, a
  quote, or a paraphrase of one. `local/` and `output/` are gitignored and stay
  that way, and `.gitignore` also matches by what a file *is*, because the
  directory rules do not cover a file written elsewhere by `--output`. Add the
  pattern when you add a stage that writes something new. Fixtures are
  synthetic (`testlib.py`) and every example name in a committed file is
  invented. `FILES-7` … `FILES-10`, `TEST-1` … `TEST-8`.

  The trap: **a paraphrase leaks too.** `summarize.md` carried a real sentence
  with the name blanked as an example of inferring a speaker. A grep for names
  will not find that. Invent the example instead.
- **Say what a decode costs before running it**, and prefer `--dry-run` first.
  `COST-1` … `COST-6`.

## Already tried, already ruled out

Each of these was measured, cost real time, and is written up where it is
cited. Do not re-derive them; if you think one is wrong, read the spec first.

| idea | verdict | spec |
|---|---|---|
| Shorten `-c` to suppress loops | No trend across a tenfold range. Loops cluster by position in the *recording*, not the chunk. | `CHUNK-7` … `CHUNK-12` |
| Amplify off-mic gaps and re-decode | Recovers nothing; returns the padded context restamped inside the gap. | `GAP-12` |
| `--include-gaps` as a default | Roughly triples the decode and is the one option that can make a transcript worse. | `REPAIR-2` |
| Chase boundary echoes with wider windows | Does not converge — the echo moves to the new edge. Reducing `--pad` came back worse. | `DEDUP-1` … `DEDUP-6` |
| Treat "more words" as "better" | Word count says nothing in either direction. Read the text. | `REPAIR-16` |
| Mark speaker changes from pitch and level | ~15 false turns per real one. | `SPEAKER-5` … `SPEAKER-12` |
| Cap `--max-speakers` to trim cluster count | Merges the real one-off speakers and leaves the smears. | `SPEAKER-29` … `SPEAKER-31` |
| Sweep `--contested-ratio` for a better value | Every band 0.3–0.9 scores the same; onset error exceeds a segment. | `SPEAKER-39`, `SPEAKER-40` |
| Name a cluster from who speaks next | Names 2 of 39, one of them probably wrong. | `NAME-5` |
| Re-run the whole pipeline to fix a few defects | Hours against minutes, and it re-rolls every part that is currently fine. | — |

The one open lever is excluding smear clusters from a mix, and it is blocked on
having a second recording to validate against — a threshold fitted to one file
cannot be checked on that file. `SPEAKER-42`,
[`spec/smear-cluster-identification.md`](spec/smear-cluster-identification.md).

## Verifying your own work

The repair summary is not evidence. Before saying a transcript is fixed, check
by measurement — `verifying-a-repaired-transcript.md`, `VERIFY-2` … `VERIFY-7`.
They are a few lines each against `T.load_timestamped`, and the one that most
often finds something is `VERIFY-6`: the last chunk has no successor, so a
hallucinated ending cannot present as a rewind and shows up nowhere else.

Two orderings are load-bearing and have each shipped broken once:

- **The seam trim runs before any decode** (`AUTO-10`). Reversed, the walk-back
  deletes the repair's own output.
- **A backwards jump is always the earlier chunk overrunning**, never the later
  chunk starting early (`SEAM-1` … `SEAM-7`, `MERGE-1` … `MERGE-7`). The trim
  confirms the seam against the audio first, because the one case where the
  text *after* the jump is the invention is a transcript whose timestamps are
  merely disordered. The fixture contains that inverse case deliberately; if a
  change starts trimming it, the change is wrong.

## Tests

    make test        # 813 checks, decoding stubbed, no model or network:
                     #   test_transcribe.py  test_repair.py   test_readable.py
                     #   test_prompt.py      test_diarize.py  test_names.py
                     #   test_glossary.py
                     # The speaker suites do not need the optional
                     # diarization install either — they stub it.

All seven suites use `testlib.py`'s `Checks` harness: `check("prose describing
the property", condition, detail_on_failure)` grouped by `check.section(...)`.
Check names read as sentences about behaviour, not as function names. Every
number asserted is a property of the fixture generator, so a fresh clone runs
the whole suite.

Add a regression test whenever a bug turns out to be an ordering or interaction
problem — those are the ones that come back. `spec/README.md` lists which
statements are verified by reading rather than by a test.
