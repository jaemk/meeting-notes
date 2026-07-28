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

## DOC-10

**The summariser is fed the rendered document, not the raw transcript.** `make
readable` pipes `readable.py --transcript-only` — carrying the same paragraphs,
the same speaker labels (`SPEAKER-21` …) and the same glossary corrections
(`GLOSS-6`) — into Claude. `transcript_lines` is shared by both outputs so the
two cannot drift.

Piping the raw `.timestamped.txt` instead is a defect with two visible
symptoms, and it shipped that way: the summary described an unlabelled
transcript while the document below it carried speakers and names, and it cited
*segment* timestamps rather than paragraph headings, so only 20% of its own
cross-references landed on a heading that existed.

This is why the glossary and naming steps run before the summary rather than
after it. A correction applied only to the document leaves the summary spelling
the name the old way.

## DOC-11

Every `[H:MM:SS]` the summary cites must be a paragraph heading present in the
assembled document. The summariser is instructed to copy them verbatim rather
than round or infer them, because a timestamp is a navigation aid and one that
resolves to nothing is worse than none. Nothing enforces this at render time;
it is checked by comparing the two files (`VERIFY-2`'s principle applied to the
summary).
