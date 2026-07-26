# Window repair

Re-transcribing just the stretches Whisper got wrong, and splicing the result
back in. This is the only path that decodes anything during a repair.

## REPAIR-1

Only the repetitions — `loop`, `stutter`, `canned` — earn a window by default.
They are text known to be wrong, in windows seconds to a minute long.

## REPAIR-2

`--include-gaps` adds gaps to the targets. It roughly triples the decode and is
the one option that can make a transcript worse, because decoding near-silence
is how boilerplate gets invented.

## REPAIR-3

A window is widened to whole segment boundaries, so a segment straddling the
edge is never cut in half.

## REPAIR-4

Windows within `--join-within` seconds (default 5) are merged into one decode.

## REPAIR-5

`--pad` seconds of surrounding audio (default 15) are decoded for context and
then discarded, so the splice stays inside the window.

## REPAIR-6

Conditioning on previous text is off inside a window. That feedback loop is
what produces the repetitions in the first place.

## REPAIR-7

A window longer than `--chunk-size` is decoded in slices cut at silence, the
same way a whole file is chunked. Slices are cut hard at the seam and padded
only at the window's outer edges, so neither slice re-transcribes the other's
speech.

## REPAIR-8

Three attempts, escalating: defaults, then double pad, then `--fallback-model`
with double pad. The first clean result wins; otherwise the attempt with the
fewest problems is kept.

## REPAIR-9

An attempt has a problem if it still loops, comes back empty, or leaves more
than `max(3s, half the window)` uncovered.

## REPAIR-10

The best attempt is spliced even when imperfect, and labelled `partial:` in the
report — except an empty one, see `REPAIR-14`. `--strict` refuses to splice
anything that did not come back clean — appropriate for gap windows, where the
alternative to bad text is a hole rather than worse text.

## REPAIR-11

Splicing removes every segment overlapping the window and inserts the
replacement at that position. Only the new material is sorted; the rest keeps
its original order, because a global sort would re-interleave a pre-existing
rewound block elsewhere in the file.

## REPAIR-12

Each pass re-diagnoses the spliced result, so a window that came back with a
fresh loop is caught by the next pass. Default two passes. Explicit `-w`
windows are decoded once and not re-derived.

## REPAIR-13

A window that no existing segment overlaps — which is what a `gap` window is —
still splices in time order. The insert position is found from the window's
place on the clock, not from the segments it displaced, because there are none
to displace. Appending it to the end instead produces a transcript whose last
line is from the middle of the meeting, and every reader and every rewind check
downstream believes the timestamps.

## REPAIR-14

A decode that comes back with nothing leaves the original text in place. Empty
is not a repair: splicing it removes real segments and puts nothing where they
were, turning a window Whisper merely mishandled into a hole. It is reported
as a failed window and the transcript is left as it was.
