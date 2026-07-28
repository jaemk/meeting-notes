#!/usr/bin/env python3
"""
Who was speaking. A separate pass over the audio, kept out of the transcript.

Whisper does not diarize, so every transcript this repo produces reads as one
continuous voice. This runs `pyannote/speaker-diarization-3.1` over the same
recording and writes the turns it finds to a sidecar file, then assigns them
onto transcript segments by overlap:

  ./diarize.py run local/2026-07-25.m4a       -> output/2026-07-25.speakers.json
  ./diarize.py apply 2026-07-25.repaired      -> output/2026-07-25.repaired.speakers.md

Two commands on purpose. `run` is the only part that costs anything (about 13
minutes for a 150-minute recording, 93% of it in the embedding stage) and the
only part that needs the audio, the model weights and a Hugging Face login.
`apply` is instant, reads only the sidecar, and can be re-run with different
thresholds as often as you like.

The sidecar is deliberately a separate file rather than a column in
.timestamped.txt: that format is parsed by transcribe.py, repair.py,
readable.py and every test, and this feature is not established enough to
reshape it. Delete the sidecar and nothing else notices.

Requires the optional install — see requirements-diarize.txt, which also
covers the Hugging Face steps pip cannot do for you.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import transcribe as T
from readable import document_title, fmt_clock

MODEL = "pyannote/speaker-diarization-3.1"

# A segment is attributed to the cluster holding most of it. These two decide
# when it is honest to say nothing instead (see spec SPEAKER-4: an
# unattributed turn is acceptable, a fabricated one is not).
#
# MIN_OVERLAP: below this share of the segment covered by any speech at all,
# the diarizer simply did not see speech here and there is nothing to assign.
MIN_OVERLAP = 0.25
# CONTESTED_RATIO: when the runner-up holds at least this much of the winner's
# share, the segment straddles a hand-off. Whisper segments are cut on silence
# and pauses, not on turns, so one segment routinely spans two people; naming
# only the louder half would be a confident wrong answer.
#
# 0.7 rather than the 0.4 this shipped with, because 0.4 was set by argument
# and 0.7 by reading the segments each value disagrees about — see spec
# SPEAKER-26. Raise it back toward 0.4 if labels ever become names: the whole
# trade below is priced on a wrong answer being an anonymous cluster number.
CONTESTED_RATIO = 0.7

UNATTRIBUTED = None


# ── The expensive pass ─────────────────────────────────────────────────────────

def load_pipeline(device=None):
    """
    The pyannote pipeline, with the two integration workarounds this version
    needs. Import is deliberately inside the function: `apply` must work in a
    venv that never installed pyannote.
    """
    try:
        import torch
        import torch.serialization as ts
        import pyannote.audio.core.task as task
        from pyannote.audio import Pipeline
    except ImportError as e:
        sys.exit(
            f"Speaker diarization is not installed ({e}).\n"
            "It is optional and costs 1-2 GB:\n"
            "    .venv/bin/pip install -r requirements-diarize.txt\n"
            "That file also covers the Hugging Face login, which pip cannot do."
        )

    # torch >= 2.6 defaults weights_only=True and pyannote's checkpoints carry
    # four non-tensor globals. Allowlisting exactly these is the narrow fix;
    # weights_only=False would permit arbitrary code execution from a
    # downloaded file, which is not a trade worth making to save four lines.
    ts.add_safe_globals([torch.torch_version.TorchVersion,
                         task.Specifications, task.Problem, task.Resolution])

    try:
        pipeline = Pipeline.from_pretrained(MODEL)
    except Exception as e:
        sys.exit(
            f"Could not load {MODEL}: {type(e).__name__}: {e}\n\n"
            "The usual causes, in order:\n"
            "  - not logged in            .venv/bin/hf auth login\n"
            "    (the command is `hf`; `huggingface-cli` no longer exists)\n"
            "  - user conditions not accepted on huggingface.co for\n"
            f"      {MODEL}\n"
            "      pyannote/segmentation-3.0\n"
            "    Gating is tied to the account, not the token, and a missed\n"
            "    one fails exactly like a bad token.\n"
            "  - huggingface_hub >= 1.0 installed. pyannote 3.4 needs < 1.0;\n"
            "    see requirements-diarize.txt."
        )
    if pipeline is None:
        sys.exit(f"{MODEL} returned no pipeline — usually an unaccepted "
                 "gated-model licence on huggingface.co.")

    if device:
        import torch
        if device == "mps" and not torch.backends.mps.is_available():
            print("mps unavailable, falling back to cpu", file=sys.stderr)
            device = "cpu"
        pipeline.to(torch.device(device))
    return pipeline


def run(audio_path, device=None, num_speakers=None, min_speakers=None,
        max_speakers=None, progress=True):
    """Diarize `audio_path`. Returns (turns, seconds, device_used)."""
    import time

    pipeline = load_pipeline(device)
    used = device or "cpu"

    constraints = {}
    if num_speakers:
        constraints["num_speakers"] = num_speakers
    else:
        if min_speakers:
            constraints["min_speakers"] = min_speakers
        if max_speakers:
            constraints["max_speakers"] = max_speakers

    started = time.perf_counter()
    if progress:
        from pyannote.audio.pipelines.utils.hook import ProgressHook
        with ProgressHook() as hook:
            annotation = pipeline(str(audio_path), hook=hook, **constraints)
    else:
        annotation = pipeline(str(audio_path), **constraints)
    elapsed = time.perf_counter() - started

    turns = [{"start": round(seg.start, 3), "end": round(seg.end, 3),
              "speaker": label}
             for seg, _, label in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda t: (t["start"], t["end"]))
    return turns, elapsed, used


# ── Assignment ─────────────────────────────────────────────────────────────────

def overlap(a_start, a_end, b_start, b_end):
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def speaker_spread(turns, start, end):
    """Seconds of each cluster inside [start, end], as {speaker: seconds}."""
    spread = defaultdict(float)
    for turn in turns:
        # turns is sorted by start, so everything past the window is done.
        if turn["start"] >= end:
            break
        shared = overlap(start, end, turn["start"], turn["end"])
        if shared > 0:
            spread[turn["speaker"]] += shared
    return spread


def assign(segments, turns, min_overlap=MIN_OVERLAP,
           contested_ratio=CONTESTED_RATIO):
    """
    Attribute each segment to a speaker by majority overlap.

    Returns a list of dicts mirroring `segments` with four keys added:
    `speaker` (None when nothing can be said), `share` (the winner's fraction
    of the segment's diarized speech), `contested` (True when the runner-up
    is close enough that the segment probably spans a hand-off) and `mix`
    (every cluster close enough to be one of the ones it spans, winner first).

    `mix` holds the winner plus everyone at or above `contested_ratio` of the
    winner's share — which is to say exactly the clusters that made the
    segment contested. Deriving it from the same threshold rather than a
    second one means the label can never disagree with the flag: contested
    implies at least two entries, and not contested implies one.

    Overlap, not onset. Cluster identity is far more reliable than cluster
    timing here — measured against verified hand-offs, the nearest cluster
    change sat a median 6.5s from the real one — so nothing in this function
    trusts a turn boundary to the second.
    """
    # speaker_spread stops walking once it is past the window, which is only
    # correct on sorted turns. Sorting once here rather than trusting the
    # caller keeps that from silently under-counting on a hand-built list.
    turns = sorted(turns, key=lambda t: (t["start"], t["end"]))
    out = []
    for seg in segments:
        duration = seg["end"] - seg["start"]
        spread = speaker_spread(turns, seg["start"], seg["end"])
        total = sum(spread.values())
        row = dict(seg, speaker=UNATTRIBUTED, share=0.0, contested=False,
                   mix=[])
        if duration > 0 and total >= min_overlap * duration and spread:
            ranked = sorted(spread.items(), key=lambda kv: -kv[1])
            winner, best = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
            row["speaker"] = winner
            row["share"] = best / total
            # `runner_up > 0` is not redundant: at contested_ratio 0 the
            # comparison alone is 0 >= 0, which would mark a segment no second
            # voice appears in at all as spanning a hand-off.
            row["contested"] = (runner_up > 0
                                and runner_up >= contested_ratio * best)
            row["mix"] = [s for s, seconds in ranked
                          if seconds > 0 and seconds >= contested_ratio * best]
        out.append(row)
    return out


def blocks(assigned):
    """
    Group consecutive segments sharing a speaker into turns.

    A contested segment breaks the run rather than joining either side: it is
    the boundary, and folding it into a neighbour would put one person's words
    under another person's name.

    Consecutive contested segments spanning the *same* clusters do group with
    each other, which a long hand-off needs — otherwise it arrives as a row of
    identical turns. They still never merge into the attributed speaker on
    either side.

    The grouping key sorts the mix, so it is the set of clusters that matters
    and not their order. Across a hand-off the two swap which of them holds
    more from one segment to the next, and keying on the ordered list would
    split a single hand-off in two at exactly that swap.
    """
    grouped = []
    for row in assigned:
        # .get, because a row may have been built by hand or by an older
        # assign(). No mix recorded groups every contested segment together
        # under the original wording, which is the pre-mix behaviour.
        key = ((tuple(sorted(row.get("mix") or [])), True) if row["contested"]
               else (row["speaker"], False))
        if grouped and grouped[-1]["key"] == key:
            grouped[-1]["rows"].append(row)
        else:
            grouped.append({"key": key, "rows": [row]})
    return grouped


def one_label(speaker, names=None):
    """
    SPEAKER_07 -> 'Speaker 7', or 'Robin (Speaker 7)' when a names sidecar
    identifies it.

    The cluster number stays visible next to the name on purpose (spec
    NAME-12): a reader who spots one wrong attribution can then see the whole
    extent of what that error covers, and the document never claims more
    identification than was performed. Diarization itself does not know who
    anyone is — a name here came from the transcript's own words, via
    names.py, and is an inference.
    """
    tail = speaker.rsplit("_", 1)[-1]
    plain = f"Speaker {int(tail)}" if tail.isdigit() else str(speaker)
    named = (names or {}).get(speaker)
    return f"{named} ({plain})" if named else plain


def join_names(parts):
    """'A', 'A and B', 'A, B and C' — read aloud, not machine-parsed."""
    if len(parts) < 2:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def mixed_label(mix, names=None):
    """
    'Speakers 2, 24 and 38' — the numbers share one 'Speakers', because
    repeating the word for each is what a machine would write.

    Falls back to joining whole labels when any of them is not a plain cluster
    number, or when a names sidecar has identified any of them: there is
    nothing to factor out of 'Robin (Speaker 2) and Speaker 24'.
    """
    numbers = [s.rsplit("_", 1)[-1] for s in mix]
    if all(n.isdigit() for n in numbers) and not any((names or {}).get(s)
                                                     for s in mix):
        return f"Speakers {join_names([str(int(n)) for n in numbers])}"
    return join_names([one_label(s, names) for s in mix])


def label_for(speaker, contested, mix=None, names=None):
    """
    How a segment is introduced in the document.

    A contested segment names every cluster it spans rather than none of them:
    which voices are in it was measured, not guessed, so withholding that is
    less accurate than reporting it (spec SPEAKER-34). This is also what keeps
    naming safe at the current threshold — a hand-off shows both people rather
    than putting one person's words under the other's name.
    """
    # Parenthetical, not an em-dash: readable.py joins the label to the text
    # with " — ", and a label carrying its own em-dash renders as
    # "Speakers 2 and 24 — spans a hand-off — the words", where the reader
    # cannot tell which dash separates the speaker from what they said.
    if contested:
        if mix and len(mix) > 1:
            return f"{mixed_label(mix, names)} (spans a hand-off)"
        # No mix to report: an older sidecar, or a hand-built row. Still says
        # the true thing, just less of it.
        return "unclear (spans a hand-off)"
    if speaker is UNATTRIBUTED:
        return "unattributed"
    return one_label(speaker, names)


def speaker_labels(segments, turns, min_overlap=MIN_OVERLAP,
                   contested_ratio=CONTESTED_RATIO, names=None):
    """
    One display label per segment, for callers that want to mark up a
    transcript without knowing how attribution works — readable.py's
    --speakers is the only one. Same assignment, same wording, so the two
    documents can never disagree about who said something.
    """
    return [label_for(row["speaker"], row["contested"], row["mix"], names)
            for row in assign(segments, turns, min_overlap, contested_ratio)]


def load_turns(path):
    """
    The turns out of a sidecar, sorted. Raises ValueError with something worth
    printing, since both CLIs turn it straight into an exit message.
    """
    try:
        data = json.loads(Path(path).read_text())
        return sorted(data["turns"], key=lambda t: (t["start"], t["end"]))
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{type(e).__name__}: {e}") from e


def render(assigned, title, stats):
    lines = [f"# Speaker-marked transcript — {title}", "",
             "*Speaker labels are acoustic clusters from "
             f"`{MODEL}`, not names — the pipeline does not know who anyone "
             "is. Two labels are two different voices; which person each one "
             "is is not established here. A turn listing more than one speaker "
             "holds words from each of them and is not a guess between them: "
             "where one turn ends and the next begins inside it is what is "
             "unknown.*", ""]
    lines += [f"{stats['segments']:,} segments · {stats['clusters']} clusters · "
              f"{stats['attributed_pct']:.1f}% attributed · "
              f"{stats['contested_pct']:.1f}% unclear · "
              f"{stats['unattributed_pct']:.1f}% unattributed", "", "---", ""]
    for group in blocks(assigned):
        rows = group["rows"]
        text = " ".join(r["text"].strip() for r in rows if r["text"].strip())
        if not text:
            continue
        first = rows[0]
        lines.append(f"**[{fmt_clock(first['start'])}] "
                     f"{label_for(first['speaker'], first['contested'], first.get('mix'))}"
                     f"** — {text}")
        lines.append("")
    return "\n".join(lines)


def summarise(assigned):
    total = len(assigned)
    contested = sum(1 for r in assigned if r["contested"])
    unattributed = sum(1 for r in assigned
                       if r["speaker"] is UNATTRIBUTED and not r["contested"])
    attributed = total - contested - unattributed
    clusters = {r["speaker"] for r in assigned if r["speaker"] is not UNATTRIBUTED}
    pct = (lambda n: 100.0 * n / total if total else 0.0)
    return {"segments": total, "clusters": len(clusters),
            "attributed": attributed, "contested": contested,
            "unattributed": unattributed, "attributed_pct": pct(attributed),
            "contested_pct": pct(contested),
            "unattributed_pct": pct(unattributed)}


# ── CLI ────────────────────────────────────────────────────────────────────────

def sidecar_path(stem, suffix=".speakers.json"):
    return Path(f"{stem}{suffix}")


def recording_stem(stem):
    """
    The stem without the pipeline's fingerprints, for naming a sidecar that
    belongs to the recording rather than to one transcript of it.
    """
    name = str(stem)
    return name[: -len(".repaired")] if name.endswith(".repaired") else name


def find_sidecar(stem, suffix=".speakers.json"):
    """
    Where a consumer looks when it was not told.

    A sidecar describes the recording, not a particular transcript of it: one
    diarization pass serves both the plain and the repaired transcript, and
    `run` names it after the audio. So a repaired transcript must fall back to
    the recording's own sidecar rather than demanding a `.repaired` one that
    nothing ever writes. Same reasoning as readable.document_title — a
    repaired transcript is still a transcript of the same meeting.

    `suffix` because names.py has exactly the same problem and there should be
    one implementation of this rule, not two that can drift apart.

    Returns (path, candidates) where path is the first that exists, or None.
    """
    candidates = [sidecar_path(stem, suffix)]
    plain = recording_stem(stem)
    if plain != str(stem):
        candidates.append(sidecar_path(plain, suffix))
    for candidate in candidates:
        if candidate.exists():
            return candidate, candidates
    return None, candidates


def cmd_run(args):
    audio = Path(args.audio)
    if not audio.exists():
        sys.exit(f"No audio at {audio}")
    if args.num_speakers and (args.min_speakers or args.max_speakers):
        sys.exit("--num-speakers fixes the count; it cannot be combined with "
                 "--min-speakers/--max-speakers.")
    if (args.min_speakers and args.max_speakers
            and args.min_speakers > args.max_speakers):
        sys.exit("--min-speakers cannot exceed --max-speakers")

    stem = args.output or str(T.resolve_output(audio.stem))
    out = sidecar_path(stem) if not str(stem).endswith(".json") else Path(stem)

    try:
        duration = T.get_duration(audio)
    except Exception:
        duration = None

    if args.dry_run:
        print(f"Would diarize {audio}"
              f"{f' ({duration/60:.0f} min)' if duration else ''} "
              f"with {MODEL}")
        print(f"  device:  {args.device}")
        print(f"  writing: {out}")
        print("  cost:    roughly a tenth of the recording's length on Metal, "
              "most of it in the embedding stage")
        return

    turns, elapsed, used = run(
        audio, device=args.device, num_speakers=args.num_speakers,
        min_speakers=args.min_speakers, max_speakers=args.max_speakers,
        progress=not args.quiet)

    speakers = sorted({t["speaker"] for t in turns})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model": MODEL, "audio": audio.name, "duration": duration,
        "device": used, "seconds": round(elapsed, 1),
        "speakers": speakers, "turns": turns,
    }, indent=1))

    speech = sum(t["end"] - t["start"] for t in turns)
    print(f"\nSaved: {out}")
    print(f"  {len(turns)} turns, {len(speakers)} clusters, "
          f"{speech/60:.1f} min of speech, {elapsed/60:.1f} min to compute")
    print(f"  Now: ./diarize.py apply <transcript>")


def cmd_apply(args):
    path = T.resolve_transcript(args.transcript)
    if not path.exists():
        sys.exit(f"No transcript at {path}")
    try:
        segments = T.load_timestamped(path)
    except ValueError as e:
        sys.exit(f"Can't read {path}: {e}")
    if not segments:
        sys.exit(f"{path} has no segments")

    stem = T.output_stem(path)
    if args.speakers:
        speakers_file = T.resolve_output(args.speakers)
        tried = [speakers_file]
    else:
        speakers_file, tried = find_sidecar(stem)
    if speakers_file is None or not speakers_file.exists():
        looked = "\n".join(f"  {c}" for c in tried)
        sys.exit(f"No speaker sidecar. Looked for:\n{looked}\n"
                 f"Run it first:  ./diarize.py run <audio>")
    try:
        turns = load_turns(speakers_file)
    except ValueError as e:
        sys.exit(f"Can't read {speakers_file}: {e}")

    assigned = assign(segments, turns, min_overlap=args.min_overlap,
                      contested_ratio=args.contested_ratio)
    stats = summarise(assigned)

    out = (T.resolve_output(args.output) if args.output
           else Path(f"{stem}.speakers.md"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(assigned, document_title(stem), stats))

    print(f"Saved: {out}")
    print(f"  {stats['segments']:,} segments over {stats['clusters']} clusters")
    print(f"    attributed   {stats['attributed']:5d}  "
          f"({stats['attributed_pct']:4.1f}%)")
    print(f"    unclear      {stats['contested']:5d}  "
          f"({stats['contested_pct']:4.1f}%)   spans a hand-off")
    print(f"    unattributed {stats['unattributed']:5d}  "
          f"({stats['unattributed_pct']:4.1f}%)   no diarized speech")


def build_parser():
    ap = argparse.ArgumentParser(
        description="Speaker diarization as a sidecar to the transcript",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s run local/2026-07-25.m4a
  %(prog)s run local/2026-07-25.m4a --max-speakers 25
  %(prog)s run local/2026-07-25.m4a --dry-run
  %(prog)s apply 2026-07-25.repaired

`run` needs the optional install and a Hugging Face login; `apply` needs
neither and only reads the sidecar `run` wrote.
""")
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="diarize the audio (the expensive pass)")
    r.add_argument("audio")
    r.add_argument("--output", "-o", default=None,
                   help="Defaults to <stem>.speakers.json in output/")
    r.add_argument("--device", default="mps", choices=("mps", "cpu"),
                   help="Metal is roughly 5x faster here (default: mps)")
    r.add_argument("--num-speakers", type=int, default=None,
                   help="Fix the speaker count exactly, if you know it")
    r.add_argument("--min-speakers", type=int, default=None)
    r.add_argument("--max-speakers", type=int, default=None,
                   help="Cap the count. Capping below the true number merges "
                        "real people, so raise it rather than guess low.")
    r.add_argument("--dry-run", action="store_true",
                   help="Say what would run, decode nothing")
    r.add_argument("--quiet", action="store_true", help="No progress bars")
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("apply", help="assign the sidecar onto a transcript")
    a.add_argument("transcript")
    a.add_argument("--speakers", default=None,
                   help="Defaults to <stem>.speakers.json beside the transcript")
    a.add_argument("--output", "-o", default=None,
                   help="Defaults to <stem>.speakers.md")
    a.add_argument("--min-overlap", type=float, default=MIN_OVERLAP,
                   help=f"Diarized speech needed to attribute at all "
                        f"(default: {MIN_OVERLAP})")
    a.add_argument("--contested-ratio", type=float, default=CONTESTED_RATIO,
                   help=f"Runner-up share that marks a segment unclear "
                        f"(default: {CONTESTED_RATIO})")
    a.set_defaults(func=cmd_apply)
    return ap


def main():
    args = build_parser().parse_args()
    # Only `apply` carries these; `run` has neither, hence the hasattr guard
    # rather than a getattr default that would have to be in range to pass.
    for flag in ("min_overlap", "contested_ratio"):
        if hasattr(args, flag) and not 0.0 <= getattr(args, flag) <= 1.0:
            sys.exit(f"--{flag.replace('_', '-')} is a fraction between 0 and 1")
    args.func(args)


if __name__ == "__main__":
    main()
