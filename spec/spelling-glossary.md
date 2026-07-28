# Spelling glossary

**Status: done.** Built as `glossary.py`, `readable.py --glossary` and the
`GLOSSARY` variable in the Makefile, covered by `test_glossary.py` and the
`--glossary` section of `test_readable.py`.

Every spelling in this spec is invented. Real ones live only in a glossary
under `local/`, which is gitignored — see GLOSS-3.

Whisper spells proper nouns it does not know phonetically. Nothing in the
pipeline can fix that: the repair loop finds loops, rewinds and gaps
(`defect-detection.md`), and a misspelled name is none of those; the audio
does not distinguish a wrong spelling from a right one, so no measurement
settles it either. The only source of truth is a person who knows the place.
This spec is that person writing it down once.

## GLOSS-1

The failure this addresses is **consistency, not frequency**. A decoder that
mangled a name differently every time would be obviously broken and harmless;
one that renders the same wrong spelling on every page produces a document
that reads as authoritative and is quotably wrong. On the reference recording
one place name appears as six distinct spellings across two meetings, none of
them correct, and the summary written from it repeated one of them as fact.

## GLOSS-2

The format is a text file, one line per spelling, because it is written and
maintained by hand:

    # comments run to end of line
    Wren Ashby: Ren Ashbee, Wren Ashbee
    Thornbury Cove: Thornberry Cove, Thorn Bury Cove

Left of the colon is the wanted spelling; right of it are the spellings the
transcript contains. Repeating a key adds to it rather than replacing it, so a
long variant list can be split across lines.

JSON was rejected for this one file, against the precedent of the speaker and
names sidecars. Those are written by a program and read by a program; this is
the only input in the pipeline a person authors directly, and it wants
comments — which is precisely where the reasoning behind an entry lives.

## GLOSS-3

**A glossary lives in `local/` and never in the repo.** Its entire content is
proper nouns from private meetings, which CLAUDE.md's rule covers as squarely
as it covers a transcript: nothing from `local/` or `output/` goes into a
commit, a test fixture, a spec or a code comment. It is looked up as
`<stem>.glossary.txt`, then `glossary.txt`, then `local/glossary.txt` — the
shared file last in the search order but first in practice, because a glossary
belongs to a community rather than to one recording.

Having one *is* the request to use it. There is no second switch, because a
switch you can forget to set produces a document that is silently wrong in the
way this feature exists to prevent. `GLOSSARY=` disables it for a run.

## GLOSS-4

**Corrections are applied when a document is rendered, never to the transcript
files.** `.timestamped.txt`, `.srt` and `.txt` keep what the decoder produced,
because they are the audit trail back to the audio: a reader who doubts a line
plays that timestamp and hears it. Editing them would break that, and would
make the correction unfalsifiable — nobody could tell afterwards which words
came from the recording and which from a glossary.

## GLOSS-5

The corrections are applied to the **paragraph list**, which is the single
place both outputs derive from: the assembled document and the
`--transcript-only` text the summariser reads. Applying it there rather than
to each separately is what stops a name being spelled one way in the summary
and another in the transcript below it — the same class of divergence
`readable-document.md` records for speaker labels and timestamps.

It follows that the summariser sees corrected text and writes correct
spellings without being told about the glossary at all. No prompt change was
needed, and `summarize.md` never learns that this feature exists.

## GLOSS-6

Matching is case-insensitive and anchored to word boundaries, and the longest
variant is tried first. Each of the three is load-bearing:

- **Word boundaries**, because a short variant is the common case for a
  nickname, and a substring match would rewrite the inside of unrelated words.
- **Longest first**, because Python's `|` takes the leftmost alternative that
  matches rather than the longest, so with both `Ren` and `Ren Ashbee` listed
  the shorter one would match and strand ` Ashbee` behind the replacement.
- **Case-insensitive matching with a case-*sensitive* replacement**, so the
  wanted spelling is written as the glossary spells it. A variant differing
  from its own canonical only in case is therefore legal and useful: Whisper's
  retry path emits unpunctuated lowercase (CLAUDE.md), and `Wren Ashby: wren
  ashby` is how a proper noun it stopped capitalising gets fixed.

Re-applying a glossary to already-corrected text is a no-op, which is what
makes re-rendering safe. It holds because a wanted spelling is never also a
variant of itself — GLOSS-7 refuses that in the parser rather than relying on
it being true.

## GLOSS-7

A glossary is hand-written, so it is refused rather than interpreted whenever
it could mean two things. A line with no colon, a name with no variants, a
spelling listed as a variant of itself, and one variant claimed by two
different spellings are all errors that name the offending line. The last is
the important one: silently picking a winner would corrupt every document
built from that glossary, in a way no reader could detect from the output.

## GLOSS-8

`glossary.py <file> --against <transcript>` reports what a glossary would
correct **and which entries never matched**. The idle half is the useful half:
an entry that never fires is either a spelling the decoder never produced or
one written down slightly wrong, and those are indistinguishable until
something goes looking. Discovering the variant list is iterative — the
reference recording gave up four more spellings of an already-known name only
after the first pass was applied and its summary flagged what was left.

## GLOSS-9

The rendered document states that a glossary was applied and names every word
changed with its count. A correction the reader cannot see is a claim about
the recording they have no way to check, and the transcript files beside the
document still carry the decoder's spelling — anyone comparing the two is owed
an explanation of why they differ.
