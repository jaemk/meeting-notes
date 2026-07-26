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
model than the main run; `--repair-passes` sets how many rounds;
`--fallback-model` sets the model a window escalates to when it comes back
still broken (`REPAIR-8`). All three are settings of the repair pass, reachable
from the transcription that runs it, so a long run does not have to be repeated
by hand to change one of them.

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

## AUTO-8

That gate counts only the kinds being targeted. `diagnose` and `verify` exit
nonzero when they find something they would have repaired, not when they find
anything at all: without `--include-gaps` a transcript whose only findings are
gaps, silences or rewinds is a pass. This is `AUTO-6` seen from the exit status
— a gate that failed on defects no repair would ever touch could never be
satisfied, and would be switched off.

## AUTO-9

`transcribe.py --repair-passes` and `repair.py --passes` are the same setting
under two names, with the same default: one is a transcription configuring the
repair pass it runs, the other is that pass being invoked directly. Neither
name may drift from the other's meaning.
