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

This classification is deliberately coarse. Level alone does not separate
speech from applause or room noise — both are loud. Distinguishing them needs
the *dynamics* of the span (a flat, loud stretch is applause; speech varies by
10–20 dB second to second), and that judgement is left to a reader or to
`make analyze` rather than encoded as a threshold here.
