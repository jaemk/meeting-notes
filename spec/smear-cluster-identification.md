# Smear cluster identification

**Status: research. Blocked on a second recording.** The work cannot be done
with the one recording in hand, and the reason it cannot is the point of this
document. Pick this up when a second meeting has been transcribed and
diarized.

Diarization on this material produces two kinds of cluster. Most are voices.
A few are **smears**: what is left over when short interjections cannot be
matched to anyone, collected into a label that looks like a person and is not.
`SPEAKER-29` … `SPEAKER-31` in [speaker-attribution.md](speaker-attribution.md)
describe them; `SPEAKER-42` records that the rule for identifying them
automatically, as first written, does not work.

## SMEAR-1

Three things are blocked on this, in ascending order of cost:

- The cluster count is inflated, so "39 speakers" overstates the meeting.
  Cosmetic.
- 26% of the segments marked as spanning a hand-off name a smear as one of the
  two voices, and **14% are contested only by a smear** — those would become
  plain attributed segments under a working exclusion, taking the marks at the
  default ratio from 140 to about 105. This is the largest single improvement
  available to speaker attribution, and `SPEAKER-39` established that no
  amount of threshold sweeping substitutes for it.
- `NAME-10` is blocked outright. A smear must never be given a name, because
  it is not a person to name, and without a test the naming feature has to
  fall back on judgement for something measurement should settle.

## SMEAR-2

A smear has a recognisable shape, and the shape is a conjunction — no single
feature identifies one. Measured on the recording behind `SPEAKER-16`, the
three clusters that read unambiguously as smears share: a **short mean turn**
(0.41 s, 0.69 s, 0.85 s), **no temporal core** (26–34% of their speech in
their densest five-minute window), and **isolation** (they essentially never
hold the floor across two consecutive turns). Real speakers can have any one
of these. It is having all three at once that is diagnostic.

## SMEAR-3 — why one recording cannot settle it

The conjunction is clear; the cut points are not. Every candidate threshold
tried lands knife-edge on the cases that matter:

- Mean turn under 2 s with concentration under 30% — the rule as originally
  written — selects three clusters, **misses the two most obvious smears in
  the file** (their concentration is 30.1% and 34.0%, against a 30% cut), and
  selects a cluster holding 272 s over 80 attributed segments that reads as a
  real recurring participant.
- Moving the concentration cut to 40% picks up the two that were missed, and
  now also picks up several one-contribution residents.

Any threshold adjusted until it selects the right five clusters on this file
is fitted to this file. That is the oracle-threshold trap `SPEAKER-11` already
names in a different context: a number chosen on the data it is scored on is
not a capability, and quoting its accuracy is quoting the fitting.

## SMEAR-4 — the counterexample any rule must survive

This is the crux, and it is why the problem is harder than it looks. Two
clusters on the same recording:

| | mean turn | isolated turns | concentration | truth |
|---|---|---|---|---|
| A | 0.93 s | 91% | 76.3% | **a real person** |
| B | 0.85 s | 87% | 27.3% | **a smear** |

A is a resident who introduced themselves once, in a single short burst near
the start; Whisper cut that burst into many short segments, so their turns are
as short and as isolated as any smear's. On mean turn duration and isolation
the two are indistinguishable. **Only concentration separates them**, and
concentration is exactly the feature whose cut point cannot be placed from one
file, because the clearest smears sit within four points of the boundary.

A rule that does not separate this pair is not a rule. Check it first.

## SMEAR-5

Isolation was tried as a third, threshold-free feature — the intuition being
that a real speaker holds the floor across consecutive turns and a smear never
does. It fails alone: one verified single real speaker never once holds the
floor twice (turns-per-run 1.00) while giving 65 seconds of report in long
7-second turns, and another real one scores 1.14 against a smear's 1.16. It
adds a genuine third dimension to the conjunction in `SMEAR-2` and it does not
rescue the problem on its own. Do not re-derive this; it has been measured.

## What to do when there is a second recording

## SMEAR-6

Transcribe and diarize the new meeting normally. Then build a feature table
over every cluster in **both** recordings: total speech, turn count, mean and
median turn duration, concentration in the densest five-minute window,
temporal spread, turns-per-run and isolated-turn fraction. All of these come
from the sidecar alone — no audio, no model, no cost. The table is not built
yet; building it is the first task, and it belongs beside `diarize.py` rather
than in a scratch script, because the whole point is that it will be run again
on a third recording.

## SMEAR-7

Hand-label every cluster in both recordings as person or smear, by reading its
attributed text and going to the audio where reading is not enough. This is
the expensive step and there is no way around it — it is the only source of
truth. Record the labels in a file, with the reason for each, so a later
disagreement is with a written judgement rather than a remembered one.
`SPEAKER-17`'s warning applies: do not "fix" a diarizer against a label that
was inferred rather than heard.

## SMEAR-8

Then fit on one recording and test on the other, **both ways round**. A rule
derived from meeting A must classify meeting B's clusters without adjustment,
and vice versa. This is the whole reason a second recording is required, and
it is the step that would have caught the original error: the failed rule was
never tested against anything it had not been written to fit.

## SMEAR-9

Accept the rule only if it holds in both directions, separates the `SMEAR-4`
pair, and errs in the safe direction. **The two errors are not symmetric.**
Calling a smear a person leaves today's behaviour exactly as it is — no worse.
Calling a real person a smear removes them from mixes and bars them from ever
being named, which is `SPEAKER-4`'s failure: a person silently erased from the
record is worse than a fragment cluster listed in it. So tune for precision on
the smear class and accept poor recall. A rule that catches three of five
smears and no real people is shippable; one that catches all five and one real
person is not.

## SMEAR-10

Ship it as a flag with a documented default, never as a constant, and say in
the flag's help that the default was derived from two meetings in one room.
Two recordings rule out the worst of the fitting; they do not make a
threshold general. Roughly eighty clusters across two meetings of the same
group in the same room is suggestive, not established — the same standard the
gap-classification thresholds are held to in `CLAUDE.md`, and for the same
reason.

## SMEAR-11 — what not to do

- **Do not constrain `max_speakers` instead.** It merges the *nearest*
  clusters, and a smear is near everything, so it takes the real
  one-contribution residents and leaves the smears. `SPEAKER-31`.
- **Do not sweep `--contested-ratio` again** hoping it absorbs the problem.
  `SPEAKER-39` and `SPEAKER-40`: every band scores the same, because cluster
  onset error is larger than a transcript segment.
- **Do not derive the rule from the second recording alone** because it is
  newer or cleaner. One file cannot validate a threshold whichever file it is.
- **Do not let a smear test suppress a cluster from the transcript.** Its
  purpose is to keep a cluster out of a *mix* and out of *naming*. The words
  attributed to it stay where they are; they were said by someone.
