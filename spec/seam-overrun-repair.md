# Seam overrun repair

The retroactive twin of `chunk-merge-and-seam-clamping.md`, for a transcript
that was written before clamping existed. The tail is text a chunk invented
past the end of its own audio, so deleting it *is* the fix.

## SEAM-1

Which side of a seam is lying is not a guess. Chunk timestamps are offset by
the chunk's own start, so a chunk's first segment can never predate its seam. A
backwards jump is always the earlier chunk overrunning, never the later chunk
starting early.

## SEAM-2

The trim runs first in the repair cycle, before any window is chosen. Finding
an overrun means walking back from the jump to the seam and taking everything
between — which is the overrunning tail only until a repair has spliced fresh
text into that stretch, at which point the walk-back would delete the repair's
own output. Ordering is the safeguard, not a preference.

## SEAM-3

Nothing is deleted until the seam is confirmed against the recording: a chunk
boundary is cut at the end of a silence, so a real seam has one within 0.25s.
Only ±2s around the seam is scanned.

## SEAM-4

An unconfirmed seam is left alone and reported. Without that check, a
transcript whose timestamps are merely disordered for some other reason would
have its real speech deleted — the one case where the text *after* the jump is
the invention.

## SEAM-5

Without a recording, or with `--no-audio-check`, nothing is trimmed and the run
says so rather than falling back to a guess.

## SEAM-6

A segment straddling the seam is clamped to it and keeps its text, for the same
reason as `MERGE-3`.

## SEAM-7

Trims are counted apart from decode windows in the repair summary. They cost no
window and cannot come back dirty, so folding them in would flatter the decode
success rate.
