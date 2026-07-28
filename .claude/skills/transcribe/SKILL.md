---
name: transcribe
description: Drive a recording end to end — chunked transcription, the diagnose/repair/verify loop, gap triage, speaker diarization, best-effort name resolution, proper-noun spelling correction from a glossary, and the readable deliverable with executive summary and action items. Use when the user asks to transcribe or process a meeting recording, or names an audio file and wants notes out of it.
---

# Processing a recording

Turn one audio file into `output/<name>.readable.md`: a summary with owners and
follow-ups, over a paragraphed transcript marked with who was speaking.

Read `CLAUDE.md` before starting. It carries the hard constraints and the
findings behind every default here. This file is the running order; that one is
why.

## The rules that override everything

- **Never run a decode inside the sandbox.** Every `transcribe.py` and
  `repair.py` invocation that decodes needs `dangerouslyDisableSandbox: true`.
  Reading transcripts and measuring audio with `ffmpeg` is fine sandboxed.
- **Always `.venv/bin/python`**, never the system interpreter. Prefer `make`.
- **`local/` and `output/` are gitignored and stay that way.** They hold real
  recordings of private meetings. Nothing from either goes into a commit, a
  test, a spec, or a code comment — including a name, a place or a quote. Run
  the leak scan in "Before you finish" if you touched a committed file.
- **Say what a step costs before running it.** Transcription is hours,
  diarization about a tenth of the recording's length. Announce, then run.
- **Never guess a name.** A wrong attribution a reader cannot detect is worse
  than an anonymous one. This is the constraint the whole speaker half is
  built around.

## Running order

Each step is a `make` target. Run them one at a time and read the output —
steps 2 and 3 exist because a person has to look.

### 1. Transcribe — hours

    make transcribe INPUT=local/NAME.m4a

Chunks at silence (5-minute chunks; see CHUNK-7…12 for why not 1), decodes,
merges with seam clamping, then runs diagnose → repair → verify automatically.
Rewinds cannot occur on a fresh run.

The single longest step. Tell the user roughly what it will cost before
starting — a 150-minute recording is a couple of hours — and let them decide.
If they want to see the shape first, `make transcribe NO_REPAIR=1` stops after
the raw pass.

### 2. Read what is left — free

    make check INPUT=local/NAME.m4a

Exits nonzero if anything is outstanding. Categories and what to do:

| kind | what it is | what to do |
|---|---|---|
| `LOOP` / `STUTTER` / `CANNED` | Whisper repeating itself | worth re-decoding, ~15s each, almost always better |
| `REWIND` | a chunk overran its seam | already trimmed on a fresh run |
| `GAP` | speech the decoder dropped | **triage — see below** |
| `AMBIENT` | applause, room noise, everyone at once | leave it; decoding invents "Thanks for watching" |

`make check` already buckets gaps by dynamics and lists only the recoverable
ones under `GAP`. Read the numbers on the `AMBIENT` rows before touching a
threshold — three of fifteen gaps on the reference recording sat within 0.3 dB
of the line.

Gaps that are quiet throughout (peak < −32 dB) are off-mic speech and are
**not recoverable**. Amplifying and re-decoding was tried and returns the
padded context re-transcribed into the gap — CLAUDE.md has the full account.
Do not spend compute on it.

### 3. Repair what is worth repairing — minutes

Only if step 2 found something:

    make fix INPUT=local/NAME.m4a WINDOWS="-w 20:47-21:09" \
             FIX_ARGS="--model large-v3 -c 1 -l en --pad 30 --strict"

Preview with `DRY=1` first. Expect about two thirds of bucket-B gap windows to
come back with real content.

**Then verify by measurement, not by the repair summary.** CLAUDE.md's
"Verifying your own work" lists the checks: backwards jumps, the biggest
word-count drops (read the text — 163 → 35 words is either a loop correctly
replaced or real speech destroyed), repeat runs under the detector threshold,
and the last segment's end against the recording's duration.

Unpunctuated lowercase output came from a fallback path and is reliably worse
than what it replaced. Revert it.

### 4. Who was speaking — about a tenth of the recording's length

Optional, and needs the extra install in `requirements-diarize.txt` plus a
Hugging Face login. If it is not installed, say so and carry on without it —
everything downstream degrades cleanly.

    make diarize INPUT=local/NAME.m4a        # once per recording
    make speakers INPUT=local/NAME.m4a       # standalone view, instant

`diarize` is the expensive half and runs once. `speakers` re-renders from the
sidecar for free, so try a different `--contested-ratio` there rather than
re-running the model.

Do not sweep `--contested-ratio` looking for a better value. It was derived
twice and every band from 0.3 to 0.9 scores the same, because cluster onset
error is larger than a transcript segment (SPEAKER-39, SPEAKER-40).

Do not cap `--max-speakers` to reduce the cluster count. It merges the real
one-contribution speakers and leaves the fragments (SPEAKER-31).

### 5. Names, where the transcript states one — a few minutes

    make names INPUT=local/NAME.m4a

Gathers every name-like mention, hands them to Claude with `naming.md`, and
validates the answer before writing `output/NAME.names.json`. The validation
refuses a cluster the recording does not have, and any quote that does not
appear in the transcript word for word — so a name has to rest on something
that was actually said (NAME-22). It does not make a name *right*: a real
quote pinned to the wrong cluster still passes.

**Expect three to ten names out of thirty or forty clusters, and say so.** Most
stay anonymous; that is the designed outcome, not a failure. Report coverage as
a share of *speech*, not of clusters — the largest ten clusters hold about 80%
of what was said.

**Read the sidecar before rendering.** It is a handful of lines, and it is the
last point where a wrong name is cheap to remove. What to look for: a name that
belongs to no one in this meeting. `naming.md`'s worked example once used a
plausible full name, and it came back as the answer for a cluster — 164
paragraphs in the deliverable attributed to a person who is not on the
recording. The prompt now uses `<…>` placeholders and the quote has to be real,
so this cannot recur in the same form, but a name that arrives from anywhere
other than the audio is the failure mode to watch for.

### 6. Proper nouns the decoder got wrong — free

Whisper spells names it does not know phonetically, and does it
*consistently* — the same wrong spelling on every page, which is what makes it
read as authoritative. Nothing upstream catches this: the repair loop finds
loops, rewinds and gaps, and a misspelled name is none of those.

If the community in this recording has names the decoder keeps mangling, write
them down once:

    # local/glossary.txt — gitignored, and must stay there
    Wren Ashby: Ren Ashbee, Wren Ashbee

Left of the colon is the spelling you want, right of it what the transcript
actually says. `make readable` applies it automatically — having a glossary
*is* the request to use it — and `GLOSSARY=` turns it off for a run.

Check it before trusting it:

    .venv/bin/python glossary.py local/glossary.txt --against output/NAME.repaired.timestamped.txt

Read the **never matched** line. An entry that never fires is either a
spelling the decoder never produced or one typed slightly wrong, and those
look identical from the outside.

**Expect to find the variants in passes, not all at once.** Apply what you
know, re-render, and read what the summary still flags as uncertain — the
reference recording gave up four more spellings of an already-known name that
way, after the first pass looked complete.

Two rules, both in `spec/spelling-glossary.md`:

- **Corrections apply to the rendered document only.** Never edit
  `.timestamped.txt`, `.srt` or `.txt`; they are the audit trail back to the
  audio. The document states that a glossary was applied and names every word
  it changed, so the difference between the two is explained rather than
  mysterious.
- **Never add a spelling you are guessing at.** A glossary entry is a name, so
  "never guess a name" covers it. Ask instead. Two inconsistent spellings are
  better than one that is consistently wrong, because the reader can see the
  inconsistency and cannot see the error.

### 7. The deliverable — minutes

    make readable INPUT=local/NAME.m4a NAMES=1

Claude writes the summary from `summarize.md` into `output/NAME.summary.md`,
then `readable.py` assembles it above the paragraphed transcript. Two steps on
purpose: the summary is the only part that costs money and the only part that
can be wrong in a way the transcript is not.

- `NAMES=1` needs step 5, and implies `SPEAKERS=1`.
- `SPEAKERS=1` alone marks turns with cluster numbers.
- Neither flag gives the plain document.
- `NO_SUMMARY=1` assembles the transcript only — no Claude, no cost.

**The summariser is fed `readable.py --transcript-only`, not the raw
transcript** — the same paragraphs, labels and glossary corrections the reader
will see. That is why steps 5 and 6 come before this one, and it is not
cosmetic: piping the bare `.timestamped.txt` in meant Claude summarised an
unlabelled transcript while the document beneath it carried speakers and names.
It announced "this transcript is not diarized" directly above a diarized one,
and cited *segment* times, so four of five of its own cross-references pointed
at a heading that did not exist.

Nothing else notices that, so check it — the summary's citations must be
headings that are actually in the document:

    .venv/bin/python - <<'PY'
    import re, pathlib
    doc  = pathlib.Path("output/NAME.readable.md").read_text()
    summ = pathlib.Path("output/NAME.summary.md").read_text()
    anchors = set(re.findall(r"\*\*\[(\d+:\d\d:\d\d)\]\*\*", doc))
    cited   = re.findall(r"\[(\d+:\d\d:\d\d)\]", summ)
    print(sum(c in anchors for c in cited), "of", len(cited), "resolve")
    PY

Expect all of them. Anything short of that means the summariser read something
other than the document.

The summary is the piece most likely to be quietly wrong. When reviewing it:
a figure stated once and revised a minute later means take the last one **and
say the earlier ones disagreed**. Never smooth over an inconsistency by
silently picking a number.

### 8. Anything needing judgement

    make analyze INPUT=local/NAME.m4a

For questions the rules cannot answer. Read `analyze.md` before reviewing a
transcript.

## Shortcut

`make pipeline INPUT=local/NAME.m4a` runs every step in order without stopping.
It skips the two places a person is supposed to look, so use it only when the
recording is already known to be clean. `NO_DIARIZE=1` drops speakers entirely.

## What not to try

Each of these was measured and cost real time. CLAUDE.md has the numbers.

- **Re-running the whole pipeline to fix a few defects.** Hours against
  minutes, and it re-rolls every part that is currently fine.
- **`--include-gaps` by default.** Roughly triples the decode and is the one
  option that can make a transcript worse.
- **Shortening `-c` to suppress loops.** Measured across a tenfold range with
  no effect. Loops are a decoder failure on hard audio, not a context-length
  failure.
- **Chasing boundary echoes with more decodes.** Widening the window moves the
  echo to the new edge; it does not converge.
- **Marking speaker changes from pitch and level.** About fifteen false turns
  per real one.
- **Naming a cluster from who speaks next.** Names 2 of 39, one of them wrong.
- **Amplifying off-mic gaps.** Recovers nothing and duplicates neighbours.
- **Hand-correcting a spelling in the summary.** It is a glossary entry —
  write it there, or the next re-render silently loses it.
- **Summarising the raw transcript.** The summariser must read the rendered
  document or it describes a different one — see step 7.

## Before you finish

- `make test` — 813 checks across seven suites, decoding stubbed, no model
  or network needed.
- If you changed a committed file, scan it for anything from the recording:
  `grep -ril "<name>" --exclude-dir=.git --exclude-dir=.venv \
   --exclude-dir=local --exclude-dir=output .`
- **The grep is necessary and not sufficient.** It finds names; it cannot find
  a paraphrase. A sentence lifted from a real meeting and reworded, with the
  name blanked, still discloses what was said — `summarize.md` carried one for
  months as an example of inferring a speaker. Re-read every example you wrote
  and confirm you invented it rather than softened it.
- Confirm `output/` and `local/` are still ignored: `git check-ignore -v output/x local/y`
- A glossary is nothing but real names, so it counts as recording content:
  `git check-ignore -v local/glossary.txt`. Every glossary example in a
  committed file must be invented.
- Report what is genuinely outstanding — unrecoverable gaps, clusters left
  anonymous, anything the summary flagged as uncertain. Do not describe a
  transcript as finished when bucket-C gaps remain; say they are unrecoverable
  and why.
