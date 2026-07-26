# Automatic repair after transcription

A defect the user has to notice and then go fix is a defect that ships. Every
transcription cleans up after itself before anyone sees the output.

## AUTO-1

Every `transcribe.py` run ends with the same diagnose → repair → verify cycle
`repair.py` exposes: the fresh transcript is scanned, targeted defects are
re-decoded and spliced, then it is scanned again and whatever is left is
reported.

## AUTO-2

`--no-repair` stops after the raw transcription.

## AUTO-3

`--chunk-size` governs both halves. The repair pass can never hand Whisper a
longer stretch than the transcription itself was allowed.

## AUTO-4

`--repair-model` re-decodes defective windows with a different (usually larger)
model than the main run; `--repair-passes` sets how many rounds.

## AUTO-5

Output files are rewritten only when something was actually spliced or trimmed.

## AUTO-6

`--include-gaps` means the same thing to transcription, `check` and `fix`
alike, so `verify` fails on exactly what a `fix` would have re-decoded. Without
that agreement a clean transcript would keep reporting gaps nothing was ever
going to touch, and `fix` then `check` would never converge.

## AUTO-7

`verify`'s exit status is the pass/fail gate, so the cycle is usable from a
script or a Makefile without parsing its output.
