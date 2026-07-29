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

## DOC-12

Whether the document discloses "speaker names are inferred" or "speaker
labels are acoustic clusters, not names" is decided by a fact `main()` passes
into `render()` explicitly, never by inspecting a rendered label string.

Two independent reasons a rendered label cannot stand in for the fact:

- A cluster id is not guaranteed to be numeric. `diarize.one_label` renders a
  named, non-numeric id as `"Robin (SPEAKER_MAIN)"`, which does not contain
  the `"(Speaker "` substring a sniff would look for — so a named document
  would be captioned as unnamed, the caveat pointed the wrong way.
- A label reaching `render()` may already have been rewritten by the
  `--glossary` step, which corrects labels the same way it corrects bodies
  (see `GLOSS-6`). The text render sees is not guaranteed to be what
  diarization or naming actually produced.

`render()` keeps a sniffing fallback for a caller that hands it paragraphs of
its own without an opinion on the question, but it is best-effort only and
documented as such — it is the same substring check DOC-12 exists to say is
not trustworthy, kept only so an old call site does not silently misbehave
rather than because it can be relied on.

## DOC-13

**The summary's citations are checked against the document being assembled,
and the result is reported.** `main()` holds both halves at once — the
summary's text and the paragraph list the transcript is about to be rendered
from — so `cited_anchors()` extracts every `[H:MM:SS]` the summary cites and
says how many of them are paragraph headings in this document. The line
printed beside `Saved:` is the count: *"Summary anchors: 12 of 12 cited
timestamps resolve to a paragraph heading"*.

DOC-11 recorded that nothing enforced this at render time and that it was
checked by comparing the two files afterwards; this statement replaces that
closing sentence. Everything else DOC-11 says still holds — the requirement
itself, and why a timestamp resolving to nothing is worse than no timestamp.

Three details of the comparison, each of which could have been got wrong in a
way that reports a healthy document as broken or a broken one as healthy:

- The clock is compared through `fmt_clock`, the same call `transcript_lines`
  makes to write the heading. Deriving the format a second time here would let
  the two drift, and a citation would start failing for a reason that has
  nothing to do with the summary.
- Only the brackets identify a citation; whatever wraps them does not.
  `summarize.md` asks for `` `[H:MM:SS]` `` in a table cell, the anchors it is
  shown are bold, and a summary comes back with all of bare, backticked and
  bolded. Insisting on one wrapping would report good citations as misses.
- The match is exact. `[00:12:34]` with a padded hour, or `[0:12:30]` rounded
  off a paragraph that begins at `0:12:34`, is a string the reader cannot find
  in the document, so it counts as unresolved. Accepting it here would be the
  same leniency that leaves them scrolling.

Distinct citations, counted once each: the question is how many places the
summary sends the reader to, not how many sentences mention one.

A summary that cites no timestamps at all says so — *"Summary cites no
`[H:MM:SS]` anchors — nothing to check"* — rather than dividing by nothing and
reporting a perfect score. It is not an error: the count exists to be read,
and "none were cited" is the honest reading of a summary that ignored the
instruction to cite them.

## DOC-14

**It is a report, never a refusal, and it is warned about below 90%.**

Refusal was considered and rejected. The summary is the one artefact in this
pipeline that costs money, takes minutes and is worth hand-editing (DOC-6);
a timestamp in it is a navigation aid. Failing the assembly over a citation
would destroy the expensive thing to protect the cheap one and leave the
reader with no document at all, rather than a document with one link that goes
nowhere. This is the same posture as `--speakers` being silently unavailable
without a sidecar and as gap classification reporting what it measured: say
what was found and let the person decide. The exit code stays clean and the
document is written whatever the count says.

Below 90% resolving, a warning goes to stderr naming up to three of the
timestamps that resolve to nothing and how to rebuild the summary. The
threshold only has to separate the two states ever measured — ~100%, which is
what rendering both halves from the same paragraphs produces (DOC-10), and
20%, the summary written from the raw `.timestamped.txt` — and nothing
legitimate sits between them. 0.9 is far enough under 100% that one stale
anchor in a hand-edited summary does not cry wolf, and far enough over 20%
that the wiring defect trips it every time. A finer ratio would claim a
precision the measurement does not have.

stderr rather than stdout, unlike the count, so it survives a redirected
stdout and stands out in `make readable`'s output — which is where this
failure was found, and missed, the first time.

**The statistic stays on the console and out of the document.** The argument
for putting it in: it is provenance, the same kind of thing as the "corrected
from a glossary" note (`GLOSS-6`), and a reader who finds a dead link would
know it was known about. The argument against, which wins: the document
already tells the reader the summary is machine-written and to check anything
that matters against the recording, and a resolution ratio is a fact about how
the pipeline ran rather than about the meeting. The glossary note is in the
document because it discloses a change made to the words themselves, which the
reader cannot otherwise see; this discloses nothing about the content. The
person who can act on it is the one running the assembly, and they are looking
at the console. Nothing about it is printed on the `--transcript-only` path
either — that path prints the transcript and nothing else, on purpose (DOC-10:
it is piped into the summariser, and a progress line lands in the middle of
it).
