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
here, and each of them is a place where a plausible fabrication would be worse
than an admission.

Nothing about it is specific to one meeting or one group. It expects a single
audio file of people talking; everything else — who they are, what they call
their places — is either derived or supplied by the person running it.

## How it is used

`README.md` is the user guide: dependencies, setup, every command, what a run
costs. Read that first if you have not run this before.

Day to day it is driven by the **`/transcribe` skill**
(`.claude/skills/transcribe/SKILL.md`), which walks the steps in order and
stops at the two places a person has to look — gap triage and the summary.
The skill is the running order; this file is the reasoning behind its
defaults, and what has already been tried and did not work. Read
`analyze.md` before reviewing a transcript output.

The whole thing is `make` targets, so it works fine without an agent:
`make help` lists them. `make pipeline` runs everything end to end for a
recording already known to be clean.

## The shape of the code

`transcribe.py` chunks and merges; `repair.py` finds defects and fixes them;
`diarize.py` separates voices; `names.py` puts names to them where the
transcript states one; `glossary.py` corrects proper nouns the decoder cannot
know; `readable.py` assembles the deliverable. `analyze.md`, `summarize.md`
and `naming.md` are the prompts handed to Claude for the judgement calls the
rules can't make.

## Hard constraints

- **Never run a Whisper decode inside the sandbox.** Every `transcribe.py` /
  `repair.py` invocation that decodes needs `dangerouslyDisableSandbox: true`.
  Analysis that only reads transcripts or measures audio with `ffmpeg` is fine
  sandboxed.
- **Always `.venv/bin/python`**, never the system interpreter.
- **`local/` and `output/` are gitignored and must stay that way.** They hold
  real recordings and real transcripts of private meetings. Nothing from either
  goes in a commit, a test fixture, a spec, or a code comment — including a
  name, a place or a quote. Fixtures are synthetic and built by `testlib.py`,
  and every example name in a committed file is invented.
  `.gitignore` also matches by what a file *is* — audio and video extensions,
  transcript and deliverable suffixes, the four sidecars, and all three
  glossary lookup paths — because the directory rules alone do not cover a
  file written elsewhere by `--output` or dropped in by hand. **Add the
  pattern when you add a stage that writes something new.**
  The trap to know about: a *paraphrase* of a real line still leaks it.
  `summarize.md` carried "my good buddy X will take over" as an example of
  inferring a speaker from context — the name was blanked, but the sentence
  was lifted from a real meeting. Invent the example instead.
- Decodes cost minutes. Say what you're about to run and roughly what it costs
  before running it, and prefer `--dry-run` first.

## What actually goes wrong, and what it costs to fix

Whisper degrades on long audio — past ~10 minutes it conditions on its own
output and gets stuck. Hence chunking at silence boundaries. That yields four
failure modes with very different economics:

| kind | fix | cost |
|---|---|---|
| `loop` / `stutter` / `canned` | re-decode the window | ~15s each, almost always an improvement |
| `rewind` | delete the overrun | free — no decode at all |
| `gap` | re-decode, *maybe* | expensive, and can make things worse |
| `silence` | nothing | correct behaviour |

### Rewinds: which side of a seam is lying is not a guess

A chunk's segment times are offset by that chunk's own start, so a chunk's
first segment can never predate its seam. **A backwards jump is always the
earlier chunk overrunning, never the later chunk starting early.** Whisper does
not stop where its audio does — a chunk ending mid-loop kept emitting for 27
more seconds on this recording. Chunks tile exactly with no padding, so
anything past the seam is invented; deleting it *is* the repair.

Two rules that are not optional:

- **Clamp the straddler, don't drop it.** A segment crossing the seam holds
  words that exist in no other chunk (no overlap between chunks). This is the
  deliberate difference from `transcribe_window`, which *can* drop a straddler
  because its neighbour was decoded with overlap.
- **Confirm the seam against the audio first.** A chunk boundary is cut at the
  end of a silence. Without that check you would also "fix" a transcript whose
  timestamps are merely disordered — the one case where the text *after* the
  jump is the invention. The test fixture deliberately contains that inverse
  case; if a change starts trimming it, the change is wrong.

### The trim must run before any decode

`trim_seams` runs first in `diagnose_repair_verify`, and the ordering is load-
bearing. Finding an overrun means walking back from the jump to the seam and
taking everything in between — which is the overrunning tail *only until* a
repair has spliced fresh text into that stretch, at which point the walk-back
deletes the repair's own output. This shipped broken once and left a 14-second
hole where the repair had just recovered real speech. `test_repair.py` has a
regression test that fails under the old ordering. Trimming first is also
cheaper: a hallucinated tail that is already gone needs no window spent on it.

## Triaging gaps: measure dynamics, not level

The detector (`gap_is_speech` in repair.py) only ever looks at mean level and
silence ratio — it deliberately does not look at peak or dynamics at all (see
`spec/gap-classification.md`, GAP-6). Everything below this point is human
judgement, not detector behaviour: peak level alone does not distinguish
speech from applause, so sample the gap in 1-second slices and look at the
**spread** between the quietest and loudest second:

- **(A) Loud and flat** (peak > −28 dB, spread < 9 dB) → applause, room noise,
  everyone talking at once. Not a defect. Decoding these is precisely how you
  get "Thanks for watching" in the transcript. Leave them.
- **(B) Mid-level with 10–20 dB of spread** → speech rhythm. Worth a decode;
  about two thirds come back with real content.
- **(C) Quiet throughout** (peak < −32 dB) → off-mic speech below where the
  VAD engages. A plain re-decode returns nothing. Amplify first (see below).

`repair.py` applies this itself: A and C are reported with their numbers and
are never chosen as repair windows, even under `--include-gaps`, so only B is
left to decode. The thresholds are `--ambient-peak-db` (−28), `--ambient-spread-db`
(9) and `--off-mic-peak-db` (−32) — flags, not constants, because three of the
fifteen gaps here sat within 0.3 dB of the spread line. Where the dynamics
cannot be measured at all (under two whole seconds, or an ffmpeg without
`astats`) the old level-only verdict stands and nothing is bucketed.

A uniform inter-segment spacing (e.g. the same line every 0.84s) is a loop
signature, not someone repeating themselves.

## Recovering off-mic speech — tried, and it does not work

The obvious idea is to amplify the quiet stretches and decode those. The
amplification part works. The recovery part does not, at least on this
recording, and the failure is worth knowing about before spending the compute
again.

Flat `volume=NdB` clips the loud parts sharing the padded window, so use the
speech normalizer, which lifts quiet passages without touching loud ones and
does not shift timestamps:

    ffmpeg -i local/NAME.m4a -af "speechnorm=e=25:r=0.0005:l=1" \
           -ac 1 -ar 16000 local/NAME.loud.wav

That bought ~23 dB on the five off-mic windows here — mean levels went from
−52…−34 dB up to −22…−16 dB with peaks near 0 and no clipping. Decoding those
windows against it recovered **nothing**. What came back instead was the
*padded context* re-transcribed and compressed into the gap's timespan — two
sentences that already existed a few seconds earlier in the transcript, run
together and restamped inside the gap. Of the five windows: one came back
`partial: still looping`, one was byte-identical to what it replaced, and the
other three duplicated their neighbours. Boosting the level does not put
information into the audio that the microphone never captured; it just gives
Whisper more room to hallucinate from surrounding speech.

Treat a bucket-C gap as unrecoverable from a single-channel recording. The fix
is at record time — a second microphone or a room mic — not in post.

If you try it anyway, **verify against the original audio**: gap classification
on a boosted file reports everything as speech.

## Things that look like good ideas and are not

- **Chasing boundary echoes with more decodes.** When a spliced window repeats
  the tail of the segment before it, that is the pad re-transcribing a sentence
  straddling the window edge. Widening the window just moves the echo to the
  new edge. This does not converge; the real fix belongs in `splice`, trimming
  the overlap. ~54 such echoes exist across a clean transcript anyway.
- **Reducing `--pad` to avoid them.** Tried; came back *worse* — unpunctuated
  and duplicating more.
- **Trusting "more words" as "better".** A window that gains words may have
  gained duplications and invented filler. Read the text.
- **Re-running the whole pipeline** to fix a handful of defects. Hours against
  minutes, and it re-rolls every part of the file that is currently fine.
- **`--include-gaps` as a default.** It roughly triples the decode and is the
  one option that can make a transcript worse.
- **Shortening `-c` to suppress loops.** Measured across `-c 1`, `2`, `3`, `5`
  and `10` on the worst 30 minutes in the recording: loops came back 4, 8, 5, 3
  and 3, with no trend. Loops start a mean 46% of the way into their chunk and
  cluster by position in the *recording*, not the chunk — they are a decoder
  failure on hard audio, and a shorter chunk cannot reach them. `make` used to
  pass `-c 1` for this reason and it bought nothing. `spec/chunked-transcription.md`,
  CHUNK-7 … CHUNK-12.
- **Marking speaker changes from audio level and pitch.** Measured on a
  150-minute recording and it does not work: one voice is stable to ±12 Hz but
  eight of nine speakers collide within that, level tracks where someone stood
  rather than who they are, and both features average the two voices together
  at the hand-off itself. A threshold set at the median real boundary yields
  roughly fifteen false turn marks per real one. See `spec/speaker-attribution.md`,
  SPEAKER-5 … SPEAKER-12. Real diarization is the answer, and is affordable
  here — SPEAKER-13 … SPEAKER-15.
- **Capping `--max-speakers` to trim the cluster count.** The 39 clusters on
  this recording are two different things at once: ten are real residents who
  spoke once, and three are smears of sub-second backchannel with no core
  anywhere in the file. Capping merges the *nearest* clusters, which takes the
  real people and leaves the smears, because a smear is near everything.
  SPEAKER-29 … SPEAKER-31. Leave the count unconstrained and exclude the
  smears downstream, where they can be identified by shape.
- **Naming clusters from who speaks next.** "<Name>, do you have any comments?"
  followed by a new voice looks like a name for that voice, and mechanically it
  names 2 of 39 clusters with one of the two probably wrong. Onset is the
  unreliable half of diarization (SPEAKER-17) and "who speaks next" is a
  question about onsets. `spec/speaker-naming.md`, NAME-5.

## Signals that a decode came back worse

- **Unpunctuated, lowercase output** means it came from a retry/fallback path.
  It is reliably worse than a clean first attempt. Revert it.
- `partial:` rows in the repair summary — read them, don't just read the
  "windows clean" count.
- `--strict` refuses to splice anything that doesn't come back clean. Use it
  for gap windows, where the alternative to bad text is a hole rather than
  worse text.
- `--in-place` keeps a `.bak`, but only of the immediately previous state.
  Snapshot to `$TMPDIR` before a run you might want to unwind past.

## Running the process on a new recording

1. `make transcribe INPUT=local/NAME.m4a` — chunks, merges with clamping, then
   runs diagnose → repair → verify automatically. Rewinds cannot occur.
2. `make check INPUT=local/NAME.m4a` — what's left.
3. Triage the gaps by dynamics (above) — `make check` already does, and only
   lists bucket B under `GAP`. Read the numbers on the A and C rows before
   moving a threshold.
4. Bucket B: `make fix ... WINDOWS="-w ..." FIX_ARGS="--model large-v3 -c 1 -l en --pad 30 --strict"`
   Expect roughly two thirds to come back with real content.
5. Bucket A and C: leave them. Neither is recoverable — see above for why.
6. `make analyze INPUT=local/NAME.m4a` for anything needing judgement.
7. `make readable INPUT=local/NAME.m4a` for the deliverable — Claude writes the
   summary from `summarize.md` into `output/NAME.summary.md`, then `readable.py`
   assembles it with the paragraphed transcript underneath. Two steps on
   purpose: the summary is the only part that costs anything and the only part
   that can be wrong in a way the transcript is not, so it lands as its own
   file first.
8. Optionally, who was speaking: `make diarize INPUT=local/NAME.m4a` once per
   recording (~13 min, needs the optional install — `requirements-diarize.txt`),
   then `make readable INPUT=... SPEAKERS=1` to label the deliverable. Labels
   are cluster numbers, never names. `make speakers` renders the same
   attribution as a standalone document, which is the cheap way to try a
   different `--contested-ratio` without re-running the summary.

## Proper nouns the decoder cannot know

Whisper spells unfamiliar names phonetically and does it *consistently*, which
is what makes it dangerous — the same wrong spelling on every page reads as
authoritative. Nothing here can detect it: the repair loop finds loops,
rewinds and gaps, and a misspelled name is none of those. A glossary is the
only fix, and it is a person writing the spelling down once.

    # local/glossary.txt
    Wren Ashby: Ren Ashbee, Wren Ashbee
    Thornbury Cove: Thornberry Cove, Thorn Bury Cove

Left of the colon is the wanted spelling, right of it what the transcript
actually says. `make readable` picks it up automatically — having a glossary
*is* the request to use it — and `GLOSSARY=` turns it off for a run. Check one
before trusting it:

    .venv/bin/python glossary.py local/glossary.txt --against output/NAME.repaired.timestamped.txt

That prints what it would correct **and which entries never matched**, which is
the half that finds typos: an entry that never fires and an entry spelled
wrong look identical otherwise. Expect to discover variants iteratively — the
first pass here found six spellings of one name, and four more surfaced only
after applying it and reading what the summary still flagged.

Two rules, both in `spec/spelling-glossary.md`:

- **A glossary lives in `local/` and never in the repo.** It is nothing but
  proper nouns from private meetings, so the same rule that covers a
  transcript covers it.
- **It never edits the transcript.** Corrections apply when a document is
  rendered; `.timestamped.txt`, `.srt` and `.txt` keep what the decoder wrote,
  because they are the audit trail back to the audio. The document says a
  glossary was applied and names what changed, so the difference between the
  two is explained rather than mysterious.

`--contested-ratio` defaults to 0.7, chosen by reading the segments each value
disagrees about rather than by argument (SPEAKER-26), and re-derived once more
after contested segments began naming both voices (SPEAKER-39). **Don't sweep
it again.** Every band from 0.3 to 0.9 scores 33–49% suspect with no trend:
cluster onset is a median 6.5 s from the truth while a segment runs about 2 s,
so overlap at a segment edge cannot tell a real hand-off from a misplaced
boundary, and no threshold over that overlap can either (SPEAKER-40). The
lever that would actually help is excluding smear clusters from a mix, and
that is blocked on not having a smear test that survives contact with the data
(SPEAKER-42). **When a second meeting gets recorded, that is the thing to
do** — `spec/smear-cluster-identification.md` has the protocol, and the point
of waiting is that a threshold fitted to one file cannot be validated on it.

When summarising, the transcript's own self-corrections matter. A figure stated
once and then revised a minute later ("actually it's…") is common in a meeting;
take the last statement, and say when the earlier ones disagreed. Never smooth
over an inconsistency by picking one silently.

Repairing a transcript made *before* the clamp existed adds one step: the seam
trim runs automatically at the start of `repair.py repair`, but needs the audio
(the positional argument on `repair`). Without it, rewinds are reported and
left alone, which is the correct conservative default. `verify`'s `--audio`
flag is unrelated — it only enables gap audio classification and never calls
the trim, so `verify`/`diagnose` alone will never trim a seam no matter what
you pass it.

## Verifying your own work

The repair summary is not evidence. Before saying a transcript is fixed, check
by measurement — these are a few lines each against `T.load_timestamped`:

- backwards jumps: `sum(1 for i in range(1,len(s)) if s[i]["start"] < s[i-1]["start"] - 0.01)`
- **read the biggest word-count drops.** A window going 163 → 35 words is
  either a loop correctly replaced by real speech or real speech destroyed.
  Only the text tells you which.
- repeat runs below the detector's threshold (3 identical lines in a row)
- the last segment's end against `T.get_duration` — the final chunk has no
  successor to reveal an overrun, so a hallucinated ending shows up there
  rather than as a rewind

## Tests

    make test        # 812 checks, decoding stubbed, no model or network:
                     #   test_transcribe.py  test_repair.py   test_readable.py
                     #   test_prompt.py      test_diarize.py  test_names.py
                     #   test_glossary.py
                     # The speaker suites do not need the optional
                     # diarization install either — they stub it.

All seven suites use `testlib.py`'s `Checks` harness: `check("prose describing
the property", condition, detail_on_failure)` grouped by `check.section(...)`.
Check names read as sentences about behaviour, not as function names. Every
number asserted is a property of the fixture generator, so a fresh clone runs
the whole suite. Add a regression test whenever a bug turns out to be an
ordering or interaction problem — those are the ones that come back.
