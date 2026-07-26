# Splice boundary de-duplication

**Status: pending.** Documented because it is a known defect with a known
shape, not because work has started.

## DEDUP-1

When a repaired window is spliced in, its first segment frequently repeats the
tail of the segment before it. The cause is the pad: a sentence straddling the
window's edge is decoded a second time as context and kept, because its
midpoint falls inside the window.

## DEDUP-2

Proposed behaviour: at splice time, if the leading new segment contains the
trailing words of the preceding kept segment, trim the overlap from one side.
The same check applies at the trailing edge.

## DEDUP-3

The check must not remove genuine repetition. People do repeat themselves, and
a meeting transcript legitimately contains "it's in the charter" twice in a
row. Whatever heuristic is chosen needs to survive that case, which means it
probably has to be anchored to a splice boundary rather than run over the whole
transcript.

## DEDUP-4

Widening the window does not fix this and should not be attempted as a
workaround: the echo simply moves to the new edge. Reducing `--pad` was also
tried and made results worse — the decode came back unpunctuated and duplicated
more.

## DEDUP-5

For scale: a clean 2½-hour transcript carried roughly 54 boundary echoes before
any repair work, so this is endemic to segmentation rather than introduced by
splicing. Splicing adds a small number on top.

## DEDUP-6

This is not `REPAIR-13`. That one is about *where* a replacement is inserted —
a gap window has no segments to displace, so its position comes from the clock.
This one is about text repeated at the *edges* of a replacement that landed in
the right place. Fixing either leaves the other exactly as it was.
