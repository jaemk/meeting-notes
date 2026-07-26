# Review and repair a Whisper transcript

You are reviewing `@TRANSCRIPT@`, produced from `@AUDIO@` by the tools in this
repo. Your job is to find every place the transcript disagrees with the
recording, fix what is worth fixing, and say plainly what you left alone.

Work from evidence. Every claim you make about this transcript should come from
something you ran, not from what the defect detector says it found — the
detector is a set of heuristics and it is wrong at the edges in both directions.

## What you have

    @AUDIO@                     the recording
    @TRANSCRIPT@                one segment per line, `[HH:MM:SS.ss --> HH:MM:SS.ss]  text`
    .venv/bin/python            the interpreter (never the system python)
    repair.py                   diagnose / repair / verify
    transcribe.py               chunking, merging, and the segment helpers

`transcribe.py` is importable and is the fastest way to answer a question about
the transcript: `T.load_timestamped(path)` gives you a list of
`{"start", "end", "text"}` dicts, and `T.silence_ends(audio, start, dur)`,
`T.uncovered_span`, `T.seam_overruns` and `T.fmt_time` are all there. Reading
3000 segments into your context to eyeball them is the slow, unreliable way to
do this. Write a few lines of Python instead.

Never decode audio without saying so first — a repair pass is minutes of
compute. Never overwrite `@TRANSCRIPT@`; the repair writes `.repaired.*`
alongside it unless someone passes `--in-place`.

## How the transcript was made, and how that shapes what goes wrong

Whisper degrades on long audio: past roughly ten minutes it starts conditioning
on its own output and gets stuck emitting one line over and over, overwriting
whatever was actually said. So the recording is cut into chunks at silence
boundaries and each chunk is decoded on its own, then the segments are merged
with each chunk's timestamps offset by where that chunk started.

That gives you four failure modes, and they are not equally serious.

**Repetitions** — `loop` (the same line 3+ times in a row — no duration
condition, but the typical case is once a second for 20+ seconds), `stutter`
(a phrase 4+ times inside one segment), `canned` ("Thanks for watching",
"Subtitles by …"). These are text you *know* is wrong, sitting in a window a
few seconds to a minute long. Re-decoding them is cheap and almost
always an improvement. They are the default repair target.

**Gaps** — 5+ seconds that produced no text with speech-level audio underneath.
These are the ambiguous ones. Most are pauses the audio check could not
positively rule out, they outnumber the repetitions several to one, and running
Whisper over near-silence is exactly how you get "Thanks for watching" where
there was nothing. Reported by default, decoded only with `--include-gaps`.

**Silences** — a gap with nothing but silence underneath. Correct behaviour.
Never a finding.

**Rewinds** — timestamps running backwards. This one is a merge artefact and it
deserves its own section, because the fix is not a decode.

## The reasoning that isn't obvious: which side of a seam is lying

Whisper does not stop where its audio does. A chunk that ends mid-loop keeps
emitting the same line with timestamps running past the end of the audio it was
given — 27 seconds past, on the recording this repo was written for. Merged
verbatim, that tail sorts *after* the next chunk's opening line, and the
transcript's timestamps go backwards.

When you see a backwards jump, the tempting question is "which of these two
stretches is real?" You do not have to guess, because the arithmetic settles it:
a chunk's segment times are offset by that chunk's own start, so a chunk's first
segment can never predate its seam. **A backwards jump is always the earlier
chunk overrunning, never the later chunk starting early.**

And chunks tile the file exactly — `[a,b]`, `[b,c]`, no padding — so anything a
chunk emits past `b` is either the next chunk's speech, which was decoded
properly a moment later, or invented. Either way it is not evidence of anything.
Deleting it *is* the repair; it costs no decoding at all.

Two caveats that are the whole reason this isn't a one-liner:

1. **Clamp the straddler, don't drop it.** A segment that starts before the seam
   and ends after it holds words that exist in no other chunk, because there is
   no overlap between chunks. Cut its end back to the seam and keep the text.
2. **Confirm the seam before deleting anything.** A chunk boundary is cut at the
   end of a silence, so a real seam has one underneath it. Check with
   `T.silence_ends(audio, seam - 2, 4)`. Without that check you would also
   "repair" a transcript whose timestamps are merely disordered for some other
   reason — the one case where the text *after* the jump is the invention and
   the text before it is what was actually said. That is a way to delete real
   speech. If you cannot confirm a seam, report it and leave it.

`repair.py` does all of this (`trim_seams`, `T.trim_seam_overruns`), and it runs
*first* in the cycle, before any repair window is chosen. That ordering matters
more than it looks. Finding the overrun means walking back from the jump to the
seam and taking everything in between — which is the tail only until a repair
has spliced freshly decoded text into that stretch, at which point the walk-back
deletes the repair's own output. Trim first and the question never arises; the
decode is also smaller, because a hallucinated tail that is already gone doesn't
need a window spent on it.

## Reviewing

Start with the cheap whole-file picture, then look at specific times.

    .venv/bin/python repair.py diagnose @AUDIO@ @TRANSCRIPT@
    .venv/bin/python repair.py diagnose @AUDIO@ @TRANSCRIPT@ --include-gaps

Then go past the detector. Things worth checking yourself, each a few lines of
Python against `T.load_timestamped`:

- **Backwards jumps**, counted directly:
  `sum(1 for i in range(1, len(s)) if s[i]["start"] < s[i-1]["start"] - 0.01)`.
  Cross-check each against `T.silence_ends` to see whether it sits on a seam.
- **Near-duplicate neighbours** that fall under the loop threshold — two
  identical lines in a row is not flagged (the detector needs three) but is
  usually still wrong.
- **Segments with implausible rates** — a 15-second segment holding four words,
  or one second holding thirty. Both mean the timestamps are not to be trusted
  there.
- **The tail of the file.** The last chunk has no successor to reveal an
  overrun, so a hallucinated ending shows up as content past the real end of
  the audio rather than as a rewind. Compare the last segment's `end` against
  `T.get_duration(audio)`.
- **Anything the detector calls a gap.** `gap_is_speech` only checks mean level
  and silence ratio (`spec/gap-classification.md`, GAP-2) — it never looks at
  peak or dynamics, so "gap" here just means "not obviously silent," not
  "obviously speech." Distinguishing dropped speech from applause or room
  noise past that point is a judgement call: sample the gap in 1-second
  slices and look at the spread between the quietest and loudest second. Loud
  and flat (peak > about −28 dB, spread < about 9 dB) reads as applause or
  everyone talking at once; mid-level with 10–20 dB of spread reads as speech
  rhythm and is worth a listen. See CLAUDE.md for the fuller triage.

When you want to know what a stretch actually sounds like, measure it rather
than speculating: `repair.audio_level(audio, start, end)` returns
`(mean_db, peak_db, silence_seconds, duration)`.

## Repairing

Cheapest first, and stop when the transcript stops improving.

1. **Seam trims** — free, no decode, and `repair.py repair` does them
   automatically first in its cycle, before any window is decoded.
2. **Targeted windows** — `-w` is repeatable and takes `SS`, `MM:SS` or
   `HH:MM:SS`:

       .venv/bin/python repair.py repair @AUDIO@ @TRANSCRIPT@ \
           -m large-v2 -c 1 -l en -w 20:47-21:09

3. **The whole detected set** — drop the `-w` and it re-decodes every
   repetition it found. On a 2½-hour meeting expect roughly a dozen windows and
   three minutes of compute.
4. **Gaps too** — add `--include-gaps`. Roughly triples the decode and is the
   one option that can make the transcript *worse*, so do it deliberately.

Always dry-run first (`--dry-run`) and show the plan before spending the
compute.

A repair can regress. A window that comes back empty or still looping is
reported as `partial:` in the summary — read that list, don't just read the
"windows clean" count. Compare word counts before and after, per window: a
window that went from 12 words to 0 has lost real speech, and the fix for that
is a targeted re-run with `--fallback-model large-v3` and a wider `--pad`, not
another pass of the same thing.

## What not to do

- **Don't re-run the whole transcription** to fix a handful of defects. It is
  hours of compute against minutes, and it re-rolls the dice on every part of
  the file that is currently fine, including the parts a repair already fixed.
- **Don't decode gaps by default.** See above.
- **Don't trim a seam you couldn't confirm.** A transcript with one line out of
  order is a much smaller problem than a transcript missing a sentence.
- **Don't trust the `.txt`.** It has no timestamps, so none of this is visible
  in it. Work from the `.timestamped.txt`.
- **Don't edit the transcript by hand** to make the checks pass. If a detection
  is wrong, the detector is what needs the fix.

## What to report

Lead with the numbers that matter: segments and words before and after,
backwards jumps before and after, windows re-decoded and how many came back
clean. Then, in order of how much they'd bother a reader of the transcript, the
things still outstanding — each with a timestamp, what the audio underneath
actually measures, and what you'd do about it. Say explicitly what you chose not
to repair and why. A finding you decided to leave is a result, not an omission,
but only if you name it.
