# Chunked transcription

Whisper degrades on long audio: past roughly ten minutes it begins conditioning
on its own output and repeats itself, overwriting what was said. Splitting the
recording is what prevents that, so how the split is made is load-bearing.

## CHUNK-1

Audio is cut into pieces of about `--chunk-size` minutes. The default is 5 and
`make` passes 5. It passed `-c 1` until CHUNK-7 measured what that was buying,
which was nothing. The repair path still uses `-c 1`, where it means "do not
sub-chunk this window" rather than "keep the decode short" — a repair window is
about a minute already.

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

## How the chunk length was chosen

Shorter chunks were assumed to suppress looping. Measured, they do not, and
the assumption cost a five-fold increase in chunk count for no return.

## CHUNK-7

**Chunk length does not change how often Whisper loops.** A 30-minute stretch
chosen for being the worst in the recording — six of the file's twelve loops,
the meeting breaking up, heavy cross-talk — was decoded at `-c 1`, `2`, `3`,
`5` and `10` with repair disabled. Loops came back 4, 8, 5, 3 and 3, and
looped seconds 48, 64, 110, 41 and 29. There is no trend, and the worst result
of the five was `-c 3`, in the middle. A clean 30-minute control decoded at
`-c 1` and `-c 10` returned one loop either way.

## CHUNK-8

The mechanism is why. Across the whole recording at `-c 1`, loops start a mean
46% of the way into their chunk, six of twelve in the first half, one of them
0.5 s in. Conditioning-driven degradation would make loops start *late*, after
context accumulates. These start anywhere, and they cluster by position in the
*recording* — none between 60 and 90 minutes, six in the last thirty. They
track how hard the audio is, not how long the chunk is. Loops inside a chunk
this short are a decoder failure, and shortening the chunk cannot reach them.

## CHUNK-9

Two measurements that look like arguments for short chunks are artefacts.
Seam damage is not detectable: text at a `-c 1` seam matches text away from
one (74% against 71% ending in punctuation, 69% against 73% starting
capitalised), and 3% of 148 seams show a boundary echo. And longer chunks
appear to lose audio — uncovered time rises from 178 s to 249 s per 30
minutes — but reading the stretches concerned, four of the ten gaps `-c 10`
has that `-c 1` does not are places where `-c 1` emitted loop garbage, not
speech. **Coverage counts hallucination as coverage.** Word counts settle it:
4296–4421 across every configuration, flat within 3%, so no chunk length in
this range captures meaningfully more of what was said.

## CHUNK-10

What longer chunks do buy is small and real: about 15% less wall clock at
`-c 10` against `-c 1`, and fewer hard cuts — a cut lands on silence 93–100%
of the time at every length, but the absolute number of mid-word cuts over the
full recording falls from 11 to 0–2, because the 90-second tolerance in
CHUNK-2 offers a longer chunk far more silences to choose from. Punctuation
improved from 73% to 81% on the hard window, but moved the other way on the
clean one, so treat that as unmeasured rather than as a gain.

## CHUNK-11

`-c 5` is the choice, not `-c 10`. On the evidence 10 is equally good and
slightly faster, but it sits exactly on the ten-minute threshold in this
document's opening line with no margin, and the whole point of that threshold
is that conditioning takes over past it. 5 keeps a factor of two in hand for a
recording that behaves worse than this one, and gives up almost nothing.

## CHUNK-12

Weigh CHUNK-7 as one 30-minute window per setting. Loop counts of 3 to 8 are
small numbers and the differences between adjacent settings are inside the
noise — `-c 3`'s 110 looped seconds is the clearest evidence of that. What the
experiment supports is the *absence* of a trend across a ten-fold range, which
is a weaker and more robust claim than any ranking of the five. Do not quote
`-c 10`'s 29 seconds as better than `-c 5`'s 41.
