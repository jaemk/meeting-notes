# Chunk merge and seam clamping

Whisper does not stop where its audio does. A chunk ending mid-loop keeps
emitting the same line with timestamps running past the end — 27 seconds past,
on the recording this was written for. Merged verbatim that tail sorts after
the next chunk's opening line and the transcript's timestamps run backwards.

## MERGE-1

Each chunk's segment times are shifted by that chunk's own start before merging.

## MERGE-2

A segment starting at or after the chunk's end is dropped. It describes audio
the chunk never had.

## MERGE-3

A segment straddling the end is clamped to the end and keeps its text. With no
padding between chunks (see `CHUNK-4`) its opening words exist in no other
chunk. This is the deliberate difference from `transcribe_window`, which may
drop a straddler because its neighbouring slice was decoded with overlap.

## MERGE-4

A segment left with a non-positive duration by clamping is dropped.

## MERGE-5

The `.txt` is rebuilt from the segments that survived, so it cannot disagree
with the `.timestamped.txt` about what was said.

## MERGE-6

The merge reports how many segments it dropped and how far past the chunk's end
they ran, so an overrun is visible in the run rather than only in the output.

## MERGE-7

Clamping is prevention, not repair. A transcript produced this way cannot
contain a seam overrun; `seam-overrun-repair.md` covers transcripts that
already do.
