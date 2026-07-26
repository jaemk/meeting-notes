#!/usr/bin/env python3
"""
Diagnose and repair Whisper transcription defects.

Whisper fails in two ways that a plain transcription run won't tell you about:

  loops   the decoder gets stuck emitting one line once a second for 20+
          seconds, overwriting whatever was actually said
  gaps    the VAD skips a stretch of quiet or off-mic speech entirely, so the
          transcript just jumps forward in time

Both are invisible in the .txt output — you only see them by looking at the
timestamps. This finds them, re-transcribes just the affected windows, splices
the result back in, and then re-runs the check to report what is left.

  ./repair.py diagnose beach.m4a transcript.timestamped.txt
  ./repair.py repair   beach.m4a transcript.timestamped.txt
  ./repair.py repair   beach.m4a transcript.timestamped.txt -w 20:47-21:09
  ./repair.py verify   transcript.repaired.timestamped.txt

transcribe.py runs this same cycle automatically at the end of a transcription;
the commands above are for a transcript you already have, or for overriding
which windows get re-decoded.

Gaps are classified by measuring the audio underneath them: a gap over silence
is correct behaviour and is left alone, a gap over speech is lost content.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import transcribe as T


@dataclass
class RepairOptions:
    """Everything repair needs to decode. Shared by the CLI and transcribe.py."""
    backend: str = "auto"
    model: str = "large-v2"
    fallback_model: str = "large-v3"
    language: Optional[str] = None
    pad: float = 15.0
    join_within: float = 5.0
    strict: bool = False
    passes: int = 2
    min_run: int = 3
    min_gap: float = 5.0
    check_audio: bool = True


# ── Defect detection ───────────────────────────────────────────────────────────

CANNED = [
    "thanks for watching", "thank you for watching", "please subscribe",
    "subtitles by", "subtitled by", "amara.org", "transcription by",
    "www.", "http://", "https://",
]


class Defect:
    def __init__(self, kind, start, end, detail):
        self.kind, self.start, self.end, self.detail = kind, start, end, detail

    @property
    def repairable(self):
        return self.kind in ("loop", "gap", "stutter", "canned")

    def __repr__(self):
        return (f"[{self.kind}] {T.fmt_time(self.start)}–{T.fmt_time(self.end)} "
                f"({self.end - self.start:.1f}s) {self.detail}")


def audio_level(audio_path, start, end):
    """Mean/max dB and total detected silence for a stretch of audio."""
    dur = max(0.05, end - start)
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin",
         "-ss", str(start), "-t", str(dur), "-i", str(audio_path),
         "-af", "silencedetect=noise=-40dB:d=0.5,volumedetect",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    err = r.stderr
    mean = re.search(r"mean_volume: ([-\d.]+) dB", err)
    peak = re.search(r"max_volume: ([-\d.]+) dB", err)
    silence = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err))
    return (float(mean.group(1)) if mean else None,
            float(peak.group(1)) if peak else None,
            silence, dur)


def gap_is_speech(audio_path, start, end, quiet_db=-50.0, silence_ratio=0.75):
    """True if there is audible content under a gap (i.e. dropped speech)."""
    mean, peak, silence, dur = audio_level(audio_path, start, end)
    if mean is None:
        return True, "could not measure"
    why = f"mean {mean:.1f}dB, peak {peak:.1f}dB, {silence:.1f}s/{dur:.0f}s silent"
    if silence / dur > silence_ratio or mean < quiet_db:
        return False, why
    return True, why


def find_stutters(segments, min_reps=4):
    """A phrase repeated 4+ times inside a single segment."""
    out = []
    for i, seg in enumerate(segments):
        words = seg["text"].split()
        for n in range(1, 7):
            for st in range(max(0, len(words) - n * min_reps + 1)):
                phrase = words[st:st + n]
                if len(" ".join(phrase)) <= 2:
                    continue
                reps = 1
                while words[st + reps * n:st + (reps + 1) * n] == phrase:
                    reps += 1
                if reps >= min_reps:
                    out.append((i, reps, " ".join(phrase)))
                    break
            else:
                continue
            break
    return out


def diagnose(segments, audio_path=None, min_run=3, min_gap=5.0, check_audio=True):
    """Find every defect in a transcript. Returns a list of Defect."""
    defects = []

    for idx, count, text in T.find_repeats(segments, min_run=min_run):
        run = segments[idx:idx + count]
        defects.append(Defect("loop", run[0]["start"], run[-1]["end"],
                              f"{count}× {text[:50]!r}"))

    for idx, reps, phrase in find_stutters(segments):
        s = segments[idx]
        defects.append(Defect("stutter", s["start"], s["end"],
                              f"{reps}× {phrase[:40]!r} within one segment"))

    for i, s in enumerate(segments):
        low = s["text"].lower()
        for c in CANNED:
            if c in low:
                defects.append(Defect("canned", s["start"], s["end"],
                                      f"boilerplate: {s['text'][:50]!r}"))
                break

    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i - 1]["end"]
        if gap < min_gap:
            continue
        a, b = segments[i - 1]["end"], segments[i]["start"]
        if check_audio and audio_path:
            speech, why = gap_is_speech(audio_path, a, b)
            if not speech:
                defects.append(Defect("silence", a, b, f"silent — ignoring ({why})"))
                continue
            defects.append(Defect("gap", a, b, f"speech under gap ({why})"))
        else:
            defects.append(Defect("gap", a, b, "unmeasured gap"))

    # Informational only — these do not warrant re-transcription
    for i in range(1, len(segments)):
        if segments[i]["start"] < segments[i - 1]["start"] - 0.01:
            defects.append(Defect("rewind", segments[i]["start"], segments[i]["end"],
                                  "timestamps go backwards (chunk merge artefact)"))

    defects.sort(key=lambda d: d.start)
    return defects


def merge_windows(windows, join_within=5.0):
    """Coalesce windows that touch or nearly touch, so we decode each stretch once."""
    if not windows:
        return []
    out = [list(windows[0])]
    for start, end in sorted(windows)[1:]:
        if start - out[-1][1] <= join_within:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [tuple(w) for w in out]


# ── Repair ─────────────────────────────────────────────────────────────────────

def attempt_window(audio_path, window, opts, attempt):
    """One re-transcription attempt. Returns (segments, problems)."""
    segs = T.transcribe_window(
        audio_path, window, opts.backend, attempt.get("model", opts.model),
        opts.language, attempt.get("pad", opts.pad), condition_on_prev=False,
    )
    problems = []
    if T.find_repeats(segs):
        problems.append("still looping")
    if not segs:
        problems.append("came back empty")
    else:
        missing = T.uncovered_span(segs, *window)
        if missing > max(3.0, 0.5 * (window[1] - window[0])):
            problems.append(f"{missing:.0f}s still uncovered")
    return segs, problems


def repair_window(audio_path, window, opts):
    """
    Re-transcribe a window, escalating if the result is still bad. Whisper is
    stochastic enough that a wider context or a different model usually breaks
    a loop that one pass could not.
    """
    plan = [
        {},
        {"pad": opts.pad * 2},
        {"model": opts.fallback_model, "pad": opts.pad * 2},
    ]
    best, best_problems = None, ["not attempted"]
    for n, attempt in enumerate(plan, 1):
        label = ", ".join(f"{k}={v}" for k, v in attempt.items()) or "defaults"
        print(f"    attempt {n}/{len(plan)} ({label})")
        segs, problems = attempt_window(audio_path, window, opts, attempt)
        if not problems:
            return segs, []
        print(f"      → {'; '.join(problems)}")
        if best is None or len(problems) < len(best_problems):
            best, best_problems = segs, problems
    return best, best_problems


def defect_windows(defects, join_within=5.0):
    """The decode windows that cover every repairable defect."""
    targets = [d for d in defects if d.repairable]
    return merge_windows([(d.start, d.end) for d in targets], join_within)


def repair(audio_path, segments, windows, opts, dry_run=False):
    """
    Re-transcribe each window and splice it into `segments`. This is the only
    place a window gets decoded and merged — automatic (windows from diagnose)
    and manual (windows from -w) repairs both come through here.

    Returns (segments, report) where a report row is
    (window, status, spliced, old_words, new_words).
    """
    report = []
    for n, window in enumerate(windows, 1):
        target = T.snap_window(segments, window)
        label = f"{T.fmt_time(target[0])}–{T.fmt_time(target[1])}"
        if target != tuple(window):
            label += f" (snapped from {T.fmt_time(window[0])}–{T.fmt_time(window[1])})"
        print(f"[{n}/{len(windows)}] {label} ({target[1] - target[0]:.0f}s)")

        before = [s for s in segments if s["end"] > target[0] and s["start"] < target[1]]
        old_words = sum(len(s["text"].split()) for s in before)

        if dry_run:
            print(f"    would replace {len(before)} segments ({old_words} words):")
            for s in before[:6]:
                print(f"      [{T.fmt_time(s['start'])}] {s['text'][:60]}")
            if len(before) > 6:
                print(f"      … and {len(before) - 6} more")
            print()
            report.append((target, "dry-run", False, old_words, old_words))
            continue

        new, problems = repair_window(audio_path, target, opts)
        if new is None:
            print("    ✗ no usable output — leaving as is\n")
            report.append((target, "failed", False, old_words, old_words))
            continue

        new_words = sum(len(s["text"].split()) for s in new)

        if problems and opts.strict:
            print(f"    ✗ {'; '.join(problems)} — skipping (strict)\n")
            report.append((target, "skipped: " + "; ".join(problems), False,
                           old_words, old_words))
            continue

        segments, removed = T.splice(segments, target, new)
        status = "repaired" if not problems else "partial: " + "; ".join(problems)
        print(f"    ✓ {len(removed)} segments ({old_words} words) → "
              f"{len(new)} segments ({new_words} words)\n")
        report.append((target, status, True, old_words, new_words))

    return segments, report


def diagnose_repair_verify(audio_path, segments, opts, windows=None,
                           dry_run=False, title="Repair"):
    """
    The whole cycle: find the defects, re-transcribe them, then check again.

    Each pass re-diagnoses the spliced result, so a window that came back with
    a fresh loop or left a hole behind is picked up by the next pass rather
    than shipping unnoticed. Returns (segments, report, remaining_defects) —
    the remaining defects being the final check nothing else is outstanding.
    """
    def scan(segs):
        return diagnose(segs, audio_path, opts.min_run, opts.min_gap, opts.check_audio)

    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    defects = scan(segments)
    print_diagnosis(defects, segments)

    report = []
    for p in range(1, opts.passes + 1):
        todo = list(windows) if windows else defect_windows(defects, opts.join_within)
        if not todo:
            print(f"\nPass {p}: nothing left to repair.")
            break
        print(f"\n── Pass {p}/{opts.passes} " + "─" * 40)
        print(f"{len(todo)} decode window(s)\n")
        segments, rep = repair(audio_path, segments, todo, opts, dry_run)
        report += rep
        if dry_run or windows:
            break  # explicit windows are decoded once, not re-derived per pass
        defects = scan(segments)

    print_report(report)
    if not dry_run:
        print("\nFinal check:")
        defects = scan(segments)
        print_diagnosis(defects, segments)
        remaining = [d for d in defects if d.repairable]
        print("\n✓ transcript is clean — no loops or unexplained gaps left."
              if not remaining else
              f"\n⚠ {len(remaining)} defect(s) still unresolved (listed above).")
    return segments, report, defects


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_diagnosis(defects, segments):
    kinds = {}
    for d in defects:
        kinds.setdefault(d.kind, []).append(d)

    if not defects:
        print("No defects found.")
    for kind in ("loop", "gap", "stutter", "canned", "silence", "rewind"):
        found = kinds.get(kind, [])
        if not found:
            continue
        total = sum(d.end - d.start for d in found)
        print(f"\n{kind.upper()}  ({len(found)}, {total:.0f}s total)")
        for d in found:
            print(f"  {T.fmt_time(d.start)}–{T.fmt_time(d.end)}  "
                  f"({d.end - d.start:5.1f}s)  {d.detail}")

    repairable = [d for d in defects if d.repairable]
    affected = sum(d.end - d.start for d in repairable)
    span = segments[-1]["end"] - segments[0]["start"] if segments else 0
    print(f"\n{len(segments)} segments over {span/60:.0f} min")
    print(f"{len(repairable)} repairable defects affecting {affected:.0f}s "
          f"({affected/span*100:.1f}% of the recording)" if span else "")


def print_report(report):
    if not report:
        return
    print("=" * 60)
    ok = sum(1 for _, s, _, _, _ in report if s == "repaired")
    print(f"REPAIR SUMMARY — {ok}/{len(report)} windows clean")
    for (a, b), status, _, old_w, new_w in report:
        print(f"  {T.fmt_time(a)}–{T.fmt_time(b)}  {status}  "
              f"({old_w} → {new_w} words)")


# ── CLI ────────────────────────────────────────────────────────────────────────

def add_common(p):
    p.add_argument("--min-run", type=int, default=3,
                   help="Identical lines in a row before it counts as a loop (default: 3)")
    p.add_argument("--min-gap", type=float, default=5.0,
                   help="Untranscribed seconds before it counts as a gap (default: 5)")
    p.add_argument("--no-audio-check", dest="check_audio", action="store_false",
                   help="Skip measuring audio under gaps (faster, less accurate)")


def main():
    ap = argparse.ArgumentParser(
        description="Diagnose and repair Whisper loops and dropped-audio gaps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s diagnose beach.m4a transcript.timestamped.txt
  %(prog)s repair   beach.m4a transcript.timestamped.txt --model large-v2 -l en
  %(prog)s repair   beach.m4a transcript.timestamped.txt --in-place
  %(prog)s repair   beach.m4a transcript.timestamped.txt -w 20:47-21:09 --dry-run
  %(prog)s verify   transcript.repaired.timestamped.txt

With no -w the windows come from the diagnosis; with -w only those stretches
are re-decoded. Either way it is the same splice-and-recheck path.
        """,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diagnose", help="Report defects without changing anything")
    d.add_argument("audio")
    d.add_argument("transcript")
    add_common(d)

    r = sub.add_parser("repair", help="Re-transcribe and splice every repairable defect")
    r.add_argument("audio")
    r.add_argument("transcript")
    add_common(r)
    r.add_argument("--window", "-w", type=T.parse_window, action="append",
                   metavar="START-END",
                   help="Repair only this stretch, e.g. 1:49:54-1:50:21 or 6594-6621. "
                        "Repeatable. Skips defect detection for window selection.")
    r.add_argument("--model", "-m", default="large-v2", choices=T.MODELS)
    r.add_argument("--fallback-model", default="large-v3", choices=T.MODELS,
                   help="Model to retry with when the first pass still loops")
    r.add_argument("--backend", "-b", default="auto", choices=T.BACKENDS,
                   help="Backend (default: auto — mlx on Apple Silicon, else openai)")
    r.add_argument("--language", "-l", default=None)
    r.add_argument("--pad", type=float, default=15.0,
                   help="Context seconds decoded either side of a window (default: 15)")
    r.add_argument("--join-within", type=float, default=5.0,
                   help="Coalesce defects closer than this into one window (default: 5)")
    r.add_argument("--output", "-o", default=None, help="Output stem")
    r.add_argument("--in-place", action="store_true",
                   help="Overwrite the source transcript (a .bak is saved first)")
    r.add_argument("--strict", action="store_true",
                   help="Only splice a window if it comes back completely clean")
    r.add_argument("--passes", type=int, default=2,
                   help="Diagnose/repair rounds (default: 2)")
    r.add_argument("--dry-run", action="store_true",
                   help="Print what would be replaced, decode and write nothing")

    v = sub.add_parser("verify", help="Re-scan a transcript and exit nonzero if defective")
    v.add_argument("transcript")
    v.add_argument("--audio", default=None, help="Enable gap audio classification")
    add_common(v)

    args = ap.parse_args()
    segments = T.load_timestamped(args.transcript)

    if args.cmd in ("verify", "diagnose"):
        # diagnose takes audio positionally, verify as an optional flag; both
        # land on args.audio and both gate the exit status on what they find.
        defects = diagnose(segments, args.audio, args.min_run, args.min_gap,
                           args.check_audio and bool(args.audio))
        print_diagnosis(defects, segments)
        sys.exit(1 if any(d.repairable for d in defects) else 0)

    print(f"Loaded {len(segments)} segments from {args.transcript}")
    opts = RepairOptions(
        backend=T.resolve_backend(args.backend), model=args.model,
        fallback_model=args.fallback_model, language=args.language,
        pad=args.pad, join_within=args.join_within, strict=args.strict,
        passes=args.passes, min_run=args.min_run, min_gap=args.min_gap,
        check_audio=args.check_audio,
    )
    print(f"Backend:  {opts.backend}  model={opts.model} "
          f"(fallback {opts.fallback_model})")

    segments, report, defects = diagnose_repair_verify(
        args.audio, segments, opts, windows=sorted(args.window or []) or None,
        dry_run=args.dry_run, title=f"Repairing {args.transcript}",
    )

    if args.dry_run:
        print("\nDry run — nothing transcribed, nothing written.")
        sys.exit(0)

    stem = (T.output_stem(args.output) if args.output
            else T.output_stem(args.transcript) if args.in_place
            else Path(str(T.output_stem(args.transcript)) + ".repaired"))
    if args.in_place:
        print(f"\nBacked up original: {T.backup_file(args.transcript)}")

    segments.sort(key=lambda s: (s["start"], s["end"]))
    T.save_output({"text": T.rebuild_text(segments), "segments": segments}, stem, True)
    # Exit 0 — the repair itself succeeded and the output is written. Anything
    # it could not fix is reported above; `verify` is the pass/fail gate.


if __name__ == "__main__":
    main()
