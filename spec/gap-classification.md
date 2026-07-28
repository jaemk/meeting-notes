# Gap classification

A gap is either a pause in the conversation or speech that went missing, and
the transcript alone cannot tell you which. The audio underneath can.

## GAP-1

The stretch is measured with a single `ffmpeg` pass combining `silencedetect`
(`-40dB`, `0.5s`) and `volumedetect`, yielding mean dB, peak dB, and how much
of the span was silent.

## GAP-2

It is classified as speech when the mean is above `-50 dB` and less than 75% of
the span was silent.

## GAP-3

Otherwise it is a `silence` and is never repaired.

## GAP-4

Without a recording, or with `--no-audio-check`, no classification is attempted
and every candidate is reported as a gap.

## GAP-5

The reported detail carries the measurements, so a judgement can be made
without re-running the analysis.

## GAP-6

**Superseded by `GAP-7` … `GAP-11`.** Retained because it records why the
split exists. It read: this classification is deliberately coarse; level alone
does not separate speech from applause or room noise — both are loud;
distinguishing them needs the *dynamics* of the span, and that judgement is
left to a reader or to `make analyze` rather than encoded as a threshold here.

The first half is still true and still describes `gap_is_speech`, which looks
at mean level and silence ratio and nothing else. What changed is the second
half: the dynamics judgement *is* now encoded, as a bucketing step that runs
after `gap_is_speech` rather than inside it.

## GAP-7

A span classified as speech is measured a second time, in 1-second slices, and
its **spread** — the difference between its loudest and quietest slice — is
recorded alongside mean and peak. Speech swings 10–20 dB from second to second;
applause and room noise sit flat.

## GAP-8

A span louder than `--ambient-peak-db` (default −28) whose spread is under
`--ambient-spread-db` (default 9) is bucketed `ambient`: applause, room noise,
or everyone talking at once. It is not a defect. It is reported with its
measurements and is **never chosen as a repair window, even under
`--include-gaps`** — decoding near-flat loud audio is how `canned` boilerplate
enters a transcript.

## GAP-9

A span whose peak is below `--off-mic-peak-db` (default −32) is bucketed
`off-mic`: someone spoke too far from the microphone for the recording to have
captured the words. Also reported with its measurements, also never repaired.
See `GAP-12` for why no decode recovers it.

## GAP-10

The three thresholds are command-line flags rather than constants, and are
accepted identically by `transcribe.py` and `repair.py`. On the recording they
were derived from, three of fifteen gaps sat within 0.3 dB of the spread line —
the thresholds run through the data rather than around it, so the value that is
right for one room is not obviously right for the next.

## GAP-11

Where the spread cannot be measured — a span under two whole seconds, or an
`ffmpeg` built without `astats` — nothing is bucketed and the `GAP-2`
level-only verdict stands unmodified. A bucket decided on peak alone would be a
guess, and both buckets it could assign suppress a repair.

## GAP-12

**Amplifying an `off-mic` span does not recover it.** Tried and measured: the
speech normalizer `speechnorm=e=25:r=0.0005:l=1` lifted five off-mic windows by
about 23 dB (mean −52…−34 dB up to −22…−16 dB, peaks near 0, no clipping)
without shifting a timestamp. Re-decoding those windows against the boosted
audio recovered no new speech. One came back still looping, one was identical
to what it replaced, and three returned their *padded context* re-transcribed
and compressed into the gap's timespan — sentences that already existed a few
seconds earlier, restamped inside the gap.

Gain does not add information the microphone never captured; it gives the
decoder more room to hallucinate from surrounding speech. Treat an `off-mic`
gap as unrecoverable from a single-channel recording — the fix belongs at
record time, in a second microphone.

A corollary worth stating because it invalidates the obvious check: gap
classification run against a boosted file reports everything as speech.
Classify against the original audio.
