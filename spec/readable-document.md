# Readable document

The `.txt` a transcription writes is one unbroken run of words: correct, and
unusable. This is the artefact a person actually reads.

## DOC-1

A paragraph ends at a pause of 2.0s or more, or at 110 words, whichever comes
first. The word cap exists so a speaker who never pauses still arrives in
readable pieces.

## DOC-2

Each paragraph is prefixed with the `H:MM:SS` of its first segment, so a
passage can be found in the recording. Hours are unpadded; these are read, not
sorted.

## DOC-3

Blank segments are skipped rather than breaking a paragraph around nothing.

## DOC-4

The document opens with the recording's name and its counts — segments, words,
running time. A trailing `.repaired` is stripped from the title: it is a
pipeline detail, not part of the meeting's name.

## DOC-5

A summary, when supplied, is placed above the transcript and labelled as
written by Claude from a machine-generated transcript. The reader should know
which parts were transcribed and which were inferred.

## DOC-6

`make readable` is two explicit steps. Claude writes the summary from
`summarize.md` into `output/NAME.summary.md` first; `readable.py` then
assembles the document. The summary is the only part that costs anything and
the only part that can be wrong in a way the transcript is not, so it lands as
its own file where it can be re-read, hand-edited or regenerated.

## DOC-7

An empty summary file is an error, not an empty section.

## DOC-8

`NO_SUMMARY=1` produces the transcript alone, invoking nothing.

## DOC-9

Paragraph breaks are not speaker changes. Whisper does not diarize, so a pause
is the closest available approximation of a turn boundary; it lands on one
often and never reliably. See `speaker-attribution.md`.
