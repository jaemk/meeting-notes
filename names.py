#!/usr/bin/env python3
"""
Putting names to the diarizer's clusters, where the transcript says one.

Diarization answers "how many voices, and which segments are the same one".
It cannot answer "who". The names are in the transcript — people introduce
themselves, and they address each other all meeting — so this pulls out every
name-like mention with the cluster context around it, and Claude decides which
of them actually identify a speaker.

  ./names.py gather 2026-07-25.repaired    -> output/2026-07-25.names-candidates.json
  <claude reads that plus naming.md>       -> JSON on stdout
  ./names.py ingest 2026-07-25.repaired -  -> output/2026-07-25.names.json

Two commands for the same reason diarize.py has two: gathering is free and
mechanical, deciding is neither. See spec/speaker-naming.md — in particular
NAME-5, which measured why the obvious mechanical shortcut ("the name refers
to whoever speaks next") does not work and must not be shipped on its own.

`ingest` exists so Claude's answer is checked rather than trusted: it must be
JSON, every cluster must be one the sidecar actually produced, and every name
must carry evidence (NAME-2). A name without a checkable basis is a guess
wearing a fact's clothing.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import diarize as D
import readable
import transcribe as T

# How much conversation to hand Claude around each mention. Two turns either
# side is enough to see a hand-off without turning the candidate file into the
# whole transcript again.
CONTEXT_SEGMENTS = 3

# A cluster holding less than this much speech is not worth naming and is
# unlikely to have been addressed by name. Not a smear test — see NAME-10 and
# spec/smear-cluster-identification.md; that rule does not exist yet.
MIN_CLUSTER_SECONDS = 5.0

CONFIDENCE = ("high", "medium", "low")

# Self-introduction: the speaker says their own name. The strongest evidence
# there is, and on the recording behind SPEAKER-16, the rarest — two in 150
# minutes (NAME-3).
SELF = re.compile(
    r"\b(?:my name is|my name's|i'm|i am|this is)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")

# Someone else names a person: a vocative, a hand-off, an introduction. Wildly
# over-inclusive on purpose — about half of what this matches is a sentence
# adverb ("Thankfully,", "Secondly,"), and NAME-4 measured that no stop-list
# can fix that because real first names collide with ordinary words. Recall is
# free here; precision is Claude's job.
ADDRESSED = re.compile(
    r"(?:^|[.?!,]\s*)([A-Z][a-z]+)\s*[,?]"
    r"|\b(?:turn it over to|hand (?:it )?(?:over )?to|introduce|welcome|thanks,?|thank you,?)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")

# Roles are stated more reliably than names and commit to less (NAME-6).
ROLE = re.compile(
    r"\b(moderator|president|vice[- ]president|treasurer|secretary|clerk|"
    r"chair(?:man|woman|person)?|counsel|attorney|lawyer|"
    r"member at large|board member)\b", re.I)


def cluster_shapes(turns):
    """
    Per-cluster shape, handed to Claude alongside the evidence.

    NAME-10 wanted smears excluded here by measurement. SPEAKER-42 showed the
    rule for that does not survive contact with the data, so the shape goes to
    the prompt instead and the judgement is made there, explicitly and weakly,
    rather than by a threshold pretending to be settled.
    """
    by = defaultdict(list)
    for turn in turns:
        by[turn["speaker"]].append(turn)

    window = 300.0
    shapes = {}
    for speaker, items in by.items():
        total = sum(t["end"] - t["start"] for t in items)
        best = 0.0
        for t in items:
            lo = t["start"]
            best = max(best, sum(
                max(0.0, min(u["end"], lo + window) - max(u["start"], lo))
                for u in items if u["start"] < lo + window and u["end"] > lo))
        shapes[speaker] = {
            "label": D.one_label(speaker),
            "speech_seconds": round(total, 1),
            "turns": len(items),
            "mean_turn_seconds": round(total / len(items), 2),
            "concentration": round(best / total, 3) if total else 0.0,
            "spread_minutes": round(
                (items[-1]["end"] - items[0]["start"]) / 60.0, 1),
        }
    return shapes


def mentions(text):
    """Every name-like span in `text`, as (kind, name). Over-inclusive."""
    found = []
    for match in SELF.finditer(text):
        found.append(("self", match.group(1).strip()))
    for match in ADDRESSED.finditer(text):
        name = match.group(1) or match.group(2)
        if name:
            found.append(("addressed", name.strip()))
    return found


def gather(segments, turns, min_overlap=D.MIN_OVERLAP,
           contested_ratio=D.CONTESTED_RATIO):
    """
    Every name-like mention, with who said it and who spoke next.

    `next_speaker` is recorded because it is the evidence a reader would
    reach for, not because it is reliable — NAME-5 measured it naming 2 of 39
    clusters with one of them probably wrong. The prompt is told as much.
    """
    rows = D.assign(segments, turns, min_overlap, contested_ratio)
    shapes = cluster_shapes(turns)
    big = {s for s, shape in shapes.items()
           if shape["speech_seconds"] >= MIN_CLUSTER_SECONDS}

    out = []
    for i, row in enumerate(rows):
        text = row["text"].strip()
        if not text:
            continue
        found = mentions(text)
        if not found:
            continue

        after = None
        for j in range(i + 1, min(i + 6, len(rows))):
            nxt = rows[j]
            if (nxt["speaker"] and not nxt["contested"]
                    and nxt["speaker"] != row["speaker"]):
                after = nxt["speaker"]
                break

        context = []
        for j in range(max(0, i - CONTEXT_SEGMENTS),
                       min(len(rows), i + CONTEXT_SEGMENTS + 1)):
            if not rows[j]["text"].strip():
                continue
            context.append({
                "at": round(rows[j]["start"], 1),
                "speaker": D.label_for(rows[j]["speaker"], rows[j]["contested"],
                                       rows[j].get("mix")),
                "text": rows[j]["text"].strip(),
                "is_mention": j == i,
            })

        for kind, name in found:
            out.append({
                "name": name,
                "kind": kind,
                "at": round(row["start"], 1),
                "clock": readable.fmt_clock(row["start"]),
                "said_by": row["speaker"] if row["speaker"] in big else None,
                "said_by_label": D.label_for(row["speaker"], row["contested"],
                                             row.get("mix")),
                "next_speaker": after if after in big else None,
                "roles_in_line": sorted({m.group(1).lower()
                                         for m in ROLE.finditer(text)}),
                "context": context,
            })
    return out, shapes


def _flatten(text):
    """
    Case and whitespace folded, for comparing a quote with its source.

    A quote is copied out of segment text, but a stretch worth quoting can
    straddle two segments and arrive joined by a single space where the
    transcript had a newline. Folding both sides the same way lets a genuine
    copy match while leaving the words themselves to be compared exactly.
    """
    return " ".join(str(text).split()).lower()


def validate(payload, shapes, segments):
    """
    Check Claude's answer before it becomes a sidecar.

    Raises ValueError with something worth printing. Every rule here exists
    because the alternative is a confident wrong name, which SPEAKER-4 rules
    out and a reader cannot detect.

    `segments` is the transcript the answer is about, and it is required
    rather than optional on purpose: every quote is checked to actually occur
    in it. Without that, "evidence" only means the key is present, and an
    entry invented whole — the worked example in naming.md copied through,
    say — validates cleanly as long as it names a cluster that exists. That
    is not hypothetical; it is how a placeholder name reached a finished
    document and stayed there for 164 paragraphs.

    Being in the transcript does not make a name correct: the quote may be
    real and the cluster it is pinned to wrong, which is what the confidence
    and adjacency rules in naming.md are for. This only rules out evidence
    that was never said at all.
    """
    haystack = " ".join(_flatten(s["text"]) for s in segments)
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object mapping cluster -> entry")
    names = payload.get("names", payload)
    if not isinstance(names, dict):
        raise ValueError("'names' must be an object mapping cluster -> entry")

    clean = {}
    for cluster, entry in names.items():
        if cluster not in shapes:
            raise ValueError(
                f"{cluster!r} is not a cluster in this recording "
                f"(known: {', '.join(sorted(shapes))})")
        if not isinstance(entry, dict):
            raise ValueError(f"{cluster}: entry must be an object")
        name = entry.get("name")
        role = entry.get("role")
        if not name and not role:
            raise ValueError(f"{cluster}: an entry must carry a name or a role")
        confidence = entry.get("confidence")
        if confidence not in CONFIDENCE:
            raise ValueError(
                f"{cluster}: confidence must be one of {CONFIDENCE}, "
                f"got {confidence!r}")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(
                f"{cluster}: needs at least one piece of evidence (NAME-2) — "
                f"a name a reader cannot check is a guess")
        for item in evidence:
            if not isinstance(item, dict) or "quote" not in item:
                raise ValueError(f"{cluster}: each evidence item needs a quote")
            quote = _flatten(item["quote"])
            if not quote:
                raise ValueError(
                    f"{cluster}: an empty quote is not evidence (NAME-2)")
            if quote not in haystack:
                raise ValueError(
                    f"{cluster}: this quote is not in the transcript, so the "
                    f"name rests on nothing that was said (NAME-2):\n"
                    f"    {item['quote']!r}\n"
                    f"  Quotes must be copied from the input word for word. A "
                    f"placeholder from the prompt's example will land here.")
        clean[cluster] = {
            "name": name or None,
            "role": role or None,
            "confidence": confidence,
            "basis": entry.get("basis") or "",
            "evidence": evidence,
        }
    return clean


def load_names(path):
    """The cluster -> display-name map readable.py and diarize.py want."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"{type(e).__name__}: {e}") from e
    names = data.get("names", data)
    if not isinstance(names, dict):
        raise ValueError("no 'names' object in the file")
    out = {}
    for cluster, entry in names.items():
        if isinstance(entry, dict) and entry.get("name"):
            out[cluster] = entry["name"]
        elif isinstance(entry, dict) and entry.get("role"):
            out[cluster] = f"the {entry['role']}"
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────

def _load(args):
    path = T.resolve_transcript(args.transcript)
    if not path.exists():
        sys.exit(f"No transcript at {path}")
    try:
        segments = T.load_timestamped(path)
    except ValueError as e:
        sys.exit(f"Can't read {path}: {e}")
    if not segments:
        sys.exit(f"{path} has no segments")

    # The recording's stem, not the transcript's: a names sidecar describes
    # the meeting, and the diarization it is built on is named that way too.
    stem = D.recording_stem(T.output_stem(path))
    sidecar, tried = D.find_sidecar(T.output_stem(path))
    if sidecar is None:
        looked = "\n".join(f"  {c}" for c in tried)
        sys.exit(f"No speaker sidecar. Looked for:\n{looked}\n"
                 f"Names are put to clusters, so diarization comes first:\n"
                 f"  ./diarize.py run <audio>")
    try:
        turns = D.load_turns(sidecar)
    except ValueError as e:
        sys.exit(f"Can't read {sidecar}: {e}")
    return segments, turns, stem


def cmd_gather(args):
    segments, turns, stem = _load(args)
    candidates, shapes = gather(segments, turns)
    out = (T.resolve_output(args.output) if args.output
           else Path(f"{stem}.names-candidates.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"clusters": shapes, "candidates": candidates}, indent=1))

    kinds = defaultdict(int)
    for c in candidates:
        kinds[c["kind"]] += 1
    print(f"Saved: {out}")
    print(f"  {len(candidates)} mentions over {len(shapes)} clusters "
          f"({kinds['self']} self-introduction, {kinds['addressed']} addressed)")
    print("  Deliberately over-inclusive — about half of the addressed ones "
          "are sentence adverbs, not people.")
    print(f"  Now: make names, or hand this and naming.md to Claude")


def cmd_ingest(args):
    segments, turns, stem = _load(args)
    _, shapes = gather(segments, turns)

    raw = (sys.stdin.read() if args.answer == "-"
           else Path(args.answer).read_text())
    # Claude is asked for bare JSON but a fenced block is the likeliest slip,
    # and refusing the whole run over three backticks helps nobody.
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.M).strip()
    try:
        payload = json.loads(text)
    except ValueError as e:
        sys.exit(f"Claude's answer is not JSON: {e}\n"
                 f"First 200 characters:\n{text[:200]}")
    try:
        clean = validate(payload, shapes, segments)
    except ValueError as e:
        sys.exit(f"Refusing to write the names sidecar: {e}")

    out = (T.resolve_output(args.output) if args.output
           else Path(f"{stem}.names.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"names": clean}, indent=1))

    print(f"Saved: {out}")
    named = sum(1 for e in clean.values() if e["name"])
    print(f"  {named} of {len(shapes)} clusters named, "
          f"{len(clean) - named} identified by role only")
    for cluster, entry in sorted(clean.items()):
        who = entry["name"] or f"the {entry['role']}"
        print(f"    {D.one_label(cluster):12s} {who}  ({entry['confidence']})")
    if len(shapes) - len(clean):
        print(f"  {len(shapes) - len(clean)} clusters left anonymous — "
              f"that is the expected outcome, not a shortfall (NAME-7)")


def build_parser():
    ap = argparse.ArgumentParser(
        description="Put names to diarization clusters, where the transcript "
                    "says one",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s gather 2026-07-25.repaired
  %(prog)s ingest 2026-07-25.repaired answer.json
  %(prog)s ingest 2026-07-25.repaired -      # read Claude's answer on stdin

`make names` runs both halves with Claude in between. Naming is best-effort
and most clusters stay anonymous — see spec/speaker-naming.md, NAME-7.
""")
    sub = ap.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gather", help="collect name mentions (free)")
    g.add_argument("transcript")
    g.add_argument("--output", "-o", default=None)
    g.set_defaults(func=cmd_gather)

    i = sub.add_parser("ingest", help="validate Claude's answer into a sidecar")
    i.add_argument("transcript")
    i.add_argument("answer", help="JSON file, or - for stdin")
    i.add_argument("--output", "-o", default=None)
    i.set_defaults(func=cmd_ingest)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
