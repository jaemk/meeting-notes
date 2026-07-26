# Defect detection

What a transcript is scanned for, and what each finding means. None of it is
visible in the `.txt` — these are properties of the timestamps.

## DETECT-1

Six kinds: `loop`, `stutter`, `canned`, `gap`, `silence`, `rewind`.

## DETECT-2

`loop` — `--min-run` or more consecutive segments with identical text, compared
case-insensitively and stripped. Default 3.

## DETECT-3

`stutter` — a phrase repeated four or more times inside a single segment.

## DETECT-4

`canned` — known boilerplate ("Thanks for watching", "Subtitles by …"), which
Whisper emits over audio it cannot transcribe.

## DETECT-5

`gap` — `--min-gap` seconds or more between segments with speech underneath.
Default 5.0. See `gap-classification.md` for how speech is established.

## DETECT-6

`silence` — the same span with silence underneath. Correct behaviour, reported
for completeness, never repaired.

## DETECT-7

`rewind` — a segment starting before its predecessor. Always a merge artefact;
see `seam-overrun-repair.md`.

## DETECT-8

Findings are returned sorted by start time regardless of kind.

## DETECT-9

`loop`, `stutter`, `canned` and `gap` are re-decodable. `rewind` never is — it
is repaired by deletion and costs no window. Which of the re-decodable kinds
are actually decoded is a separate decision (`REPAIR-1`).

## DETECT-10

Without audio, detection still runs; only the gap/silence distinction is
unavailable, and every candidate is reported as a gap.
