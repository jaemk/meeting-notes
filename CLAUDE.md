# Working in this repo

Whisper transcription with an automatic diagnose → repair → verify cycle.
`transcribe.py` chunks and merges; `repair.py` finds defects and fixes them;
`analyze.md` is the prompt `make analyze` hands to Claude for the judgement
calls the rules can't make. Read `analyze.md` before reviewing a transcript —
this file is about working on the code and running the process, that one is
about reading the output.

## Hard constraints

- **Never run a Whisper decode inside the sandbox.** Every `transcribe.py` /
  `repair.py` invocation that decodes needs `dangerouslyDisableSandbox: true`.
  Analysis that only reads transcripts or measures audio with `ffmpeg` is fine
  sandboxed.
- **Always `.venv/bin/python`**, never the system interpreter.
- **`local/` and `output/` are gitignored and must stay that way.** They hold
  real recordings and real transcripts of private meetings. Nothing from either
  goes in a commit, a test fixture, or a code comment. Fixtures are synthetic
  and built by `testlib.py`.
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

Peak level alone does not distinguish speech from applause. Sample the gap in
1-second slices and look at the **spread** between the quietest and loudest
second:

- **Loud and flat** (peak > −28 dB, spread < 9 dB) → applause, room noise,
  everyone talking at once. Not a defect. Decoding these is precisely how you
  get "Thanks for watching" in the transcript. Leave them.
- **Mid-level with 10–20 dB of spread** → speech rhythm. Worth a decode; about
  two thirds come back with real content.
- **Quiet throughout** (peak < −32 dB) → off-mic speech below where the VAD
  engages. A plain re-decode returns nothing. Amplify first (see below).

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

Treat a bucket-B gap as unrecoverable from a single-channel recording. The fix
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
3. Triage the gaps by dynamics (above). Only bucket C earns a decode.
4. Bucket C: `make fix ... WINDOWS="-w ..." FIX_ARGS="--model large-v3 -c 1 -l en --pad 30 --strict"`
   Expect roughly two thirds to come back with real content.
5. Bucket A and B: leave them. Neither is recoverable — see above for why.
6. `make analyze` for anything needing judgement.

Repairing a transcript made *before* the clamp existed adds one step: the seam
trim runs automatically at the start of `repair.py repair`, but needs the audio
(`--audio` on `verify`, or the positional argument on `repair`). Without it,
rewinds are reported and left alone, which is the correct conservative default.

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

    make test        # test_transcribe.py + test_repair.py, decoding stubbed

Both suites use `testlib.py`'s `Checks` harness: `check("prose describing the
property", condition, detail_on_failure)` grouped by `check.section(...)`.
Check names read as sentences about behaviour, not as function names. Every
number asserted is a property of the fixture generator, so a fresh clone runs
the whole suite. Add a regression test whenever a bug turns out to be an
ordering or interaction problem — those are the ones that come back.
