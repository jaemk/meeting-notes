#!/usr/bin/env python3
"""
Proper spellings for the words a decoder cannot know.

Whisper spells unfamiliar proper nouns phonetically, and it does so
*consistently*, which is what makes the error dangerous: a place name wrong
the same way on every page reads as authoritative. It is also the one defect
class the repair loop cannot reach — `repair.py` finds loops, rewinds and
gaps, and a confidently misspelled name is none of those. Nothing in the audio
distinguishes it from a correct one either, so no measurement can fix it. The
only source of truth is a person who knows the place.

A glossary is that person writing it down once:

    # local/glossary.txt — one line per name, comments allowed
    Wren Ashby:  Ren Ashbee, Wren Ashbee
    Thornbury Cove: Thornberry Cove, Thorn Bury Cove

Left of the colon is the spelling you want. Right of it are the spellings the
transcript actually contains. Matching is case-insensitive and anchored to
word boundaries, so `Al` in a glossary never turns `Also` into `Alsoso`.

## What this deliberately does not do

**It never edits the transcript.** `.timestamped.txt`, `.srt` and `.txt` are
what the decoder produced, and they are the audit trail back to the audio: a
reader who doubts a line plays that timestamp and hears it. Rewriting them by
hand breaks that, and worse, it makes the correction unfalsifiable — nobody
can tell afterwards which words came from the recording. Corrections are
applied when a document is *rendered*, so the deliverable reads correctly
while the decoder's own output stays exactly as it came.

That is also why the rendered document says a glossary was applied. A silent
correction is a claim about the recording that the reader cannot check.
"""

import re
import sys
from pathlib import Path

# Where a glossary is looked for when none is named. local/ because it holds
# real names from private meetings and is gitignored — see CLAUDE.md. A
# glossary belongs to a community rather than to one recording, so the shared
# file is the common case and the per-recording one is the exception.
DEFAULT_NAMES = ("glossary.txt", "local/glossary.txt")


class GlossaryError(ValueError):
    """A glossary that cannot be trusted to mean one thing."""


def parse(text):
    """
    Read the source into {correct spelling: [variants]}.

    Refuses rather than guesses. A glossary is hand-written, so a typo in one
    is likely; and a glossary that silently means something other than what
    it says would corrupt every document built from it, in a way no reader
    could detect from the output.
    """
    mapping, seen, out = {}, {}, []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise GlossaryError(
                f"line {lineno}: expected '<correct spelling>: <variant>, "
                f"<variant>', found:\n    {raw.strip()}")
        correct, _, rest = line.partition(":")
        correct = correct.strip()
        if not correct:
            raise GlossaryError(f"line {lineno}: no spelling before the colon")

        variants = []
        for v in rest.split(","):
            v = v.strip()
            if not v:
                continue
            if v == correct:
                # Harmless, and always a mistake worth pointing at: someone
                # meant to list what the transcript says, and listed what they
                # want it to say instead.
                #
                # Compared exactly, not case-insensitively, because a variant
                # differing only in case is a real correction rather than a
                # typo: Whisper's retry path emits unpunctuated lowercase (see
                # CLAUDE.md), so "Wren Ashby: wren ashby" is how you fix a
                # proper noun it stopped capitalising.
                raise GlossaryError(
                    f"line {lineno}: {v!r} is listed as a variant of itself — "
                    f"variants are the spellings the transcript contains, not "
                    f"the one you want")
            key = _fold(v)
            if key in seen and seen[key] != correct:
                raise GlossaryError(
                    f"line {lineno}: {v!r} is already a variant of "
                    f"{seen[key]!r}, so it cannot also mean {correct!r} — "
                    f"one spelling cannot correct to two different words")
            seen[key] = correct
            variants.append(v)
        if not variants:
            raise GlossaryError(
                f"line {lineno}: {correct!r} lists no variants, so it would "
                f"never match anything")
        mapping.setdefault(correct, [])
        mapping[correct].extend(variants)
        out.append(correct)
    return mapping


def _fold(text):
    """Case and whitespace folded, for comparing two spellings."""
    return " ".join(text.split()).lower()


def compile_rules(mapping):
    """
    One regex over every variant, longest first.

    Longest first is load-bearing rather than an optimisation: with "Ren" and
    "Ren Ashbee" both listed, the shorter alternative would match first and
    leave " Ashbee" stranded on the end of the corrected word. Python's `|`
    takes the leftmost alternative that matches, not the longest, so the
    ordering here is the only thing preventing that.
    """
    pairs = sorted(((v, c) for c, vs in mapping.items() for v in vs),
                   key=lambda p: (-len(p[0]), p[0].lower()))
    if not pairs:
        return None, {}
    lookup = {_fold(v): c for v, c in pairs}
    # \s+ between words, because a variant that spans a line break in the
    # transcript arrives joined by whatever whitespace was there.
    alts = r"|".join(r"\s+".join(re.escape(w) for w in v.split())
                     for v, _ in pairs)
    return re.compile(rf"\b(?:{alts})\b", re.IGNORECASE), lookup


def apply(text, rules):
    """
    Correct `text`, returning (corrected, {correct spelling: times replaced}).

    The canonical spelling is used as written in the glossary, whatever case
    the transcript had. A decoder that shouts a name it does not recognise
    should not make the document shout it back.
    """
    pattern, lookup = rules
    if pattern is None or not text:
        return text, {}
    counts = {}

    def swap(m):
        correct = lookup[_fold(m.group(0))]
        counts[correct] = counts.get(correct, 0) + 1
        return correct

    return pattern.sub(swap, text), counts


def load(path):
    """Parse a glossary file into compiled rules."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise GlossaryError(f"can't read {p}: {e}") from e
    return compile_rules(parse(text))


def find(stem=None):
    """
    The glossary to use when none was named, or None.

    Checked in order: this recording's own, then the shared one. A community
    keeps one glossary across its meetings; a single recording only needs its
    own when it has names the others do not.
    """
    candidates = []
    if stem:
        candidates.append(Path(f"{stem}.glossary.txt"))
    candidates += [Path(n) for n in DEFAULT_NAMES]
    for c in candidates:
        if c.exists():
            return c
    return None


def summarise(counts):
    """One line naming what was corrected, for a run that should say so."""
    if not counts:
        return "no spellings corrected"
    parts = ", ".join(f"{k} ×{n}" for k, n in
                      sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return f"corrected {sum(counts.values())} spelling(s): {parts}"


def main():
    """Check a glossary and show what it would do to a transcript."""
    import argparse

    ap = argparse.ArgumentParser(
        description="Check a spelling glossary, or preview it on a transcript",
        epilog="examples:\n"
               "  %(prog)s local/glossary.txt\n"
               "  %(prog)s local/glossary.txt --against output/x.timestamped.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glossary")
    ap.add_argument("--against", default=None, metavar="TRANSCRIPT",
                    help="Report what it would correct in this transcript, "
                         "and what it never matches")
    args = ap.parse_args()

    try:
        rules = load(args.glossary)
    except GlossaryError as e:
        sys.exit(f"Refusing this glossary: {e}")
    mapping = parse(Path(args.glossary).read_text(encoding="utf-8"))
    total = sum(len(v) for v in mapping.values())
    print(f"{args.glossary}: {len(mapping)} spellings, {total} variants")

    if not args.against:
        return
    import transcribe as T
    try:
        segments = T.load_timestamped(args.against)
    except (OSError, ValueError) as e:
        sys.exit(f"Can't read {args.against}: {e}")
    _, counts = apply(" ".join(s["text"] for s in segments), rules)
    print(f"  {summarise(counts)}")
    # A variant that never fires is the useful half of this report: it is
    # either a spelling the decoder never produced, or one written down
    # slightly wrong, and those look identical until you go looking.
    idle = [c for c in mapping if c not in counts]
    if idle:
        print(f"  {len(idle)} never matched: {', '.join(sorted(idle))}")


if __name__ == "__main__":
    main()
