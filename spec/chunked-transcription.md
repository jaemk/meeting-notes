# Chunked transcription

Whisper degrades on long audio: past roughly ten minutes it begins conditioning
on its own output and repeats itself, overwriting what was said. Splitting the
recording is what prevents that, so how the split is made is load-bearing.

## CHUNK-1

Audio is cut into pieces of about `--chunk-size` minutes. The default is 5;
`make` passes `-c 1`, which is also what the repair path uses, so no decode is
ever longer than a whole-file chunk was allowed to be.

## CHUNK-2

Each cut lands on the nearest silence within `min(90s, chunk/2)` of its target.
Chasing a silence further than that rebuilds the long decode `-c` exists to
avoid. With no silence in range the cut is made hard at the target.

## CHUNK-3

Silences come from `ffmpeg silencedetect` at `-35dB` for `0.3s`.

## CHUNK-4

Chunks tile the file exactly — `[a,b]`, `[b,c]` — with no overlap and no
padding. Every downstream rule about seams depends on this: a chunk's audio
stops at its seam, so anything it emits past that point is invented.

## CHUNK-5

A trailing piece shorter than 20% of a chunk is not created; the final chunk
absorbs it rather than handing Whisper a fragment.

## CHUNK-6

Each chunk is decoded independently. Conditioning on previous text never
crosses a chunk boundary, since that feedback is the failure being avoided.
