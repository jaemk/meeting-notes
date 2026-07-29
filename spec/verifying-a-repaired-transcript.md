# Verifying a repaired transcript

**Status: done** for `VERIFY-1`, which is `repair.py verify` and is covered by
`test_repair.py`. `VERIFY-2` … `VERIFY-7` are checks a person runs against a
finished transcript; nothing in the suite runs them for you, and they are here
because each one catches a defect that the automated signals call clean.

A repair pass reports what it did, not whether it helped. Those are different
claims, and the gap between them is where a bad repair survives.

## VERIFY-1

`repair.py verify` re-scans a transcript and exits nonzero on the kinds being
targeted (`AUTO-7`, `AUTO-8`). This is the automatable gate and the only part
of this document a script can run.

## VERIFY-2

**The repair summary is not evidence.** "12 windows clean" states that twelve
decodes returned text which passed the detector, which is not the same claim as
twelve stretches of the meeting now being right. Read the `partial:` rows
rather than the clean count.

## VERIFY-3

**Count backwards jumps and expect zero.** Against `T.load_timestamped`:

    sum(1 for i in range(1, len(s)) if s[i]["start"] < s[i-1]["start"] - 0.01)

A nonzero count after a repair means either a seam was not trimmed or a splice
landed at the wrong position (`REPAIR-13`).

## VERIFY-4

**Read the largest word-count changes, in both directions.** Per `REPAIR-16`
the counts cannot say which way a window went, so the check is to find the
biggest movers and read their text. This is the only check here that does not
reduce to a number.

## VERIFY-5

**Look for repeat runs below the detector's threshold.** `DETECT-2` fires at
`--min-run` identical segments, default 3. Two identical segments in a row is
invisible to it, and is often the tail of a loop that a repair shortened rather
than removed.

## VERIFY-6

**Check the final segment's end against the recording's duration**
(`T.get_duration`). The last chunk has no successor, so an overrun past the end
of the audio cannot present as a `rewind` (`DETECT-7`) — there is no later
segment for it to sort before. A hallucinated ending is invisible to every
other check here and shows up only in this one.

## VERIFY-7

**A uniform inter-segment spacing is a loop signature.** The same line arriving
every 0.84 seconds is a decoder stuck in a cycle rather than a person repeating
themselves; real repetition is irregularly spaced. Spacing is not part of
`DETECT-2`, which compares text alone, so this is a reading check and not a
detector rule.

## VERIFY-8

**Nothing on the write path may erase a backwards jump.** The jump is not a
formatting defect to be tidied up on the way to disk; it is the evidence
`VERIFY-3` counts, and the only trace an unconfirmed seam (`SEAM-4`) leaves
behind. A step that reorders segments while writing them removes the symptom and
keeps the damage, so the count comes back zero on a transcript that is worse
than it was — and `VERIFY-2` … `VERIFY-7` are all run against the written file.
This is why `SEAM-8` states the rule as a property of the write path rather than
leaving it to whoever next finds a transcript out of order.
