#!/usr/bin/env python3
"""
Transcribe audio files using Whisper.

Backends:
  mlx    - Apple Silicon GPU (fast, recommended on M-series Macs)
  openai - CPU-based (slower, works everywhere)

Models (smallest/fastest → largest/most accurate):
  tiny, base, small, medium, large, large-v2, large-v3

Long files are automatically split at silence boundaries to prevent
Whisper's hallucination/repetition bug on extended audio.

When a bad patch slips through anyway (a repeated line looping for 20+
seconds), re-run just that stretch with --window and splice it back into
an existing transcript with --merge.
"""

import argparse
import json
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


MODELS = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]

MLX_MODEL_MAP = {
    "tiny":     "mlx-community/whisper-tiny-mlx-q4",
    "base":     "mlx-community/whisper-base-mlx-q4",
    "small":    "mlx-community/whisper-small-mlx-q4",
    "medium":   "mlx-community/whisper-medium-mlx-q4",
    "large":    "mlx-community/whisper-large-v3-mlx-4bit",
    "large-v2": "mlx-community/whisper-large-v2-mlx-4bit",
    "large-v3": "mlx-community/whisper-large-v3-mlx-4bit",
}


# ── Audio helpers ──────────────────────────────────────────────────────────────

def get_duration(audio_path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(audio_path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def find_split_points(audio_path, chunk_secs, duration):
    """
    Run silence detection and return split timestamps that fall near each
    chunk_secs boundary. Falls back to a hard cut if no silence is nearby.
    """
    print("detecting moments of silence")
    r = subprocess.run(
        ["ffmpeg", "-i", str(audio_path),
         "-af", "silencedetect=noise=-35dB:d=0.3",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silence_ends = [
        float(m.group(1))
        for m in re.finditer(r"silence_end: ([\d.]+)", r.stderr)
    ]
    print(f"found {len(silence_ends)} moments of silence")

    splits = [0.0]
    target = chunk_secs
    while target < duration - chunk_secs * 0.2:  # avoid a tiny tail chunk
        nearby = [t for t in silence_ends if t > splits[-1] and abs(t - target) < 90]
        best = min(nearby, key=lambda t: abs(t - target)) if nearby else target
        splits.append(best)
        target = best + chunk_secs
        print(f"chunk boundary at {best/60:.1f} min (next target {target/60:.1f} min)")
    splits.append(duration)
    return splits


def parse_time(s):
    """Parse SS, MM:SS or HH:MM:SS (decimals allowed) into seconds."""
    parts = s.strip().split(":")
    if len(parts) > 3 or not all(parts):
        raise ValueError(f"bad timestamp: {s!r}")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def parse_window(s):
    """
    Parse 'START-END' into (start, end) seconds. Accepts 1:49:50-1:50:25,
    6594-6621, 20:47-21:09. The separator is '-' or '..'.
    """
    text = s.strip().replace("..", "-")
    # Split on the '-' that separates the two stamps, not any inside them.
    m = re.match(r"^\s*([\d:.]+)\s*-\s*([\d:.]+)\s*$", text)
    if not m:
        raise argparse.ArgumentTypeError(
            f"bad window {s!r} — expected START-END, e.g. 1:49:50-1:50:25"
        )
    start, end = parse_time(m.group(1)), parse_time(m.group(2))
    if end <= start:
        raise argparse.ArgumentTypeError(f"window {s!r} ends before it starts")
    return (start, end)


def extract_chunk(audio_path, start, dur, out_path):
    """Extract a segment and convert to 16 kHz mono WAV (Whisper's native format)."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(audio_path),
         "-ss", str(start), "-t", str(dur),
         "-ar", "16000", "-ac", "1",
         str(out_path)],
        check=True,
    )


# ── Transcription backends ─────────────────────────────────────────────────────

def _transcribe_one_mlx(audio_path, model_name, language, condition_on_prev=True):
    import mlx_whisper
    mlx_model = MLX_MODEL_MAP.get(model_name, MLX_MODEL_MAP["base"])
    return mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=mlx_model,
        language=language,
        condition_on_previous_text=condition_on_prev,
        verbose=True,
    )


def _transcribe_one_openai(audio_path, model_name, language, _openai_model_cache,
                           condition_on_prev=True):
    import whisper
    if model_name not in _openai_model_cache:
        _openai_model_cache[model_name] = whisper.load_model(model_name)
    return _openai_model_cache[model_name].transcribe(
        str(audio_path),
        language=language,
        condition_on_previous_text=condition_on_prev,
        verbose=True,
    )


def _run_backend(audio_path, backend, model_name, language, cache, condition_on_prev=True):
    """Transcribe one prepared WAV, falling back from mlx to openai on failure."""
    if backend == "mlx":
        try:
            return _transcribe_one_mlx(audio_path, model_name, language, condition_on_prev)
        except Exception as e:
            print(f"(mlx failed: {e}, using openai fallback)", end="  ")
    return _transcribe_one_openai(audio_path, model_name, language, cache, condition_on_prev)


def transcribe(audio_path, backend, model_name, language, chunk_mins):
    """
    Transcribe audio_path, splitting into chunks to avoid Whisper hallucination.
    Returns a dict with 'text' and 'segments' (timestamps adjusted to original).
    """
    duration = get_duration(audio_path)
    chunk_secs = chunk_mins * 60

    if duration <= chunk_secs * 1.1:
        splits = [0.0, duration]
    else:
        print(f"Audio is {duration/60:.1f} min — splitting into ~{chunk_mins}-min chunks at silence points...")
        splits = find_split_points(audio_path, chunk_secs, duration)
        print(f"Split into {len(splits)-1} chunks\n")

    openai_cache = {}
    all_segments = []
    all_text = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        n = len(splits) - 1

        for i, (start, end) in enumerate(zip(splits[:-1], splits[1:])):
            chunk_path = tmp / f"chunk_{i:04d}.wav"
            print(f"[{i+1}/{n}] {start/60:.1f}–{end/60:.1f} min", end="  ", flush=True)
            extract_chunk(audio_path, start, end - start, chunk_path)

            t0 = time.time()
            result = _run_backend(chunk_path, backend, model_name, language, openai_cache)

            elapsed = time.time() - t0
            text = result["text"].strip()
            print(f"→ {len(text.split())} words in {elapsed:.0f}s")

            all_text.append(text)
            for seg in result.get("segments", []):
                seg = dict(seg)
                seg["start"] += start
                seg["end"] += start
                all_segments.append(seg)

    return {"text": " ".join(all_text), "segments": all_segments}


# ── Window re-transcription & merge ────────────────────────────────────────────

TS_LINE = re.compile(
    r"^\[(\d+):(\d\d):([\d.]+)\s*-->\s*(\d+):(\d\d):([\d.]+)\]\s*(.*)$"
)


def load_timestamped(path):
    """Read a .timestamped.txt back into segment dicts."""
    segments = []
    for lineno, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        m = TS_LINE.match(line)
        if not m:
            raise ValueError(f"{path}:{lineno}: not a timestamped line: {line[:60]!r}")
        g = m.groups()
        segments.append({
            "start": int(g[0]) * 3600 + int(g[1]) * 60 + float(g[2]),
            "end":   int(g[3]) * 3600 + int(g[4]) * 60 + float(g[5]),
            "text":  g[6].strip(),
        })
    return segments


def find_repeats(segments, min_run=3):
    """
    Find runs of consecutive segments with identical text — Whisper's
    repetition/hallucination signature. Returns [(index, count, text), ...].
    """
    runs, i = [], 0
    while i < len(segments):
        j = i
        key = segments[i]["text"].strip().lower()
        while j + 1 < len(segments) and segments[j + 1]["text"].strip().lower() == key:
            j += 1
        if key and j - i + 1 >= min_run:
            runs.append((i, j - i + 1, segments[i]["text"].strip()))
        i = j + 1
    return runs


def holes(segments, start, end, min_size=1.5):
    """Spans inside [start, end) that no segment covers, longer than min_size."""
    out, cursor = [], start
    for s in sorted(segments, key=lambda s: s["start"]):
        if s["start"] - cursor > min_size:
            out.append((cursor, s["start"]))
        cursor = max(cursor, s["end"])
    if end - cursor > min_size:
        out.append((cursor, end))
    return out


def uncovered_span(segments, start, end):
    """How many seconds of [start, end) no segment covers."""
    return sum(b - a for a, b in holes(segments, start, end, min_size=0.0))


def snap_window(segments, window):
    """
    Widen a window to whole segment boundaries so the splice never cuts a
    segment in half — a segment that merely clips the edge would otherwise
    lose the half that falls outside the window.
    """
    start, end = window
    touched = [s for s in segments if s["end"] > start and s["start"] < end]
    if not touched:
        return (start, end)
    return (min(start, min(s["start"] for s in touched)),
            max(end, max(s["end"] for s in touched)))


def transcribe_window(audio_path, window, backend, model_name, language,
                      pad, condition_on_prev=False):
    """
    Re-transcribe a single [start, end) window. `pad` seconds of extra audio
    are decoded on each side to give Whisper acoustic context, then dropped
    so the returned segments stay inside the window.
    """
    start, end = window
    duration = get_duration(audio_path)
    dec_start = max(0.0, start - pad)
    dec_end = min(duration, end + pad)

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "window.wav"
        print(f"  extracting {fmt_time(dec_start)}–{fmt_time(dec_end)} "
              f"({dec_end - dec_start:.0f}s incl. {pad:.0f}s pad)")
        extract_chunk(audio_path, dec_start, dec_end - dec_start, wav)

        t0 = time.time()
        result = _run_backend(wav, backend, model_name, language, {}, condition_on_prev)
        print(f"  decoded in {time.time() - t0:.0f}s")

    shifted = [{"start": seg["start"] + dec_start, "end": seg["end"] + dec_start,
                "text": seg["text"].strip()}
               for seg in result.get("segments", [])]

    def inside(seg):
        mid = (seg["start"] + seg["end"]) / 2
        return start <= mid < end

    kept = [dict(s) for s in shifted if inside(s)]
    # A segment straddling the window edge has its midpoint in the padding and
    # gets dropped — but the old segments there were already spliced out, so
    # that speech would vanish. Pull such a segment back in if it is the only
    # thing covering a hole. Slight overlap with a neighbour beats losing a line.
    for seg in shifted:
        if inside(seg) or seg["end"] <= start or seg["start"] >= end:
            continue
        if uncovered_span(kept, max(seg["start"], start), min(seg["end"], end)) >= 1.0:
            kept.append(dict(seg))
    kept.sort(key=lambda s: (s["start"], s["end"]))
    for seg in kept:
        seg["start"], seg["end"] = max(seg["start"], start), min(seg["end"], end)

    for hole in holes(kept, start, end, 1.5):
        print(f"  ⚠ {hole[1] - hole[0]:.1f}s of this window came back empty "
              f"({fmt_time(hole[0])}–{fmt_time(hole[1])})")

    repeats = find_repeats(kept)
    if repeats:
        print("  ⚠ new output still looks like a repetition loop:")
        for _, count, text in repeats:
            print(f"      {count}× {text[:60]!r}")
    return kept


def splice(segments, window, replacement):
    """
    Drop every segment overlapping `window` and insert `replacement` in its
    place. Only the new material is sorted — the rest keeps its original order.
    A global sort would re-interleave any pre-existing rewound block elsewhere
    in the file, shuffling a duplicated passage line-by-line into its neighbour.
    """
    start, end = window
    def hits(s):
        return s["end"] > start and s["start"] < end

    removed = [s for s in segments if hits(s)]
    kept = [s for s in segments if not hits(s)]
    first = next((i for i, s in enumerate(segments) if hits(s)), len(segments))
    insert_at = sum(1 for s in segments[:first] if not hits(s))
    ordered = sorted(replacement, key=lambda s: (s["start"], s["end"]))
    return kept[:insert_at] + ordered + kept[insert_at:], removed


def rebuild_text(segments):
    return " ".join(s["text"].strip() for s in segments if s["text"].strip())


def run_windows(audio_path, windows, args, output_path):
    """Re-transcribe each window, optionally splicing into an existing transcript."""
    base = load_timestamped(args.merge) if args.merge else []
    if base:
        print(f"Loaded {len(base)} segments from {args.merge}\n")

    result_segments = list(base)
    for n, window in enumerate(windows, 1):
        target = snap_window(result_segments, window) if (base and args.snap) else window
        label = f"{fmt_time(window[0])}–{fmt_time(window[1])}"
        if target != window:
            label += f"  (snapped to {fmt_time(target[0])}–{fmt_time(target[1])})"
        print(f"[window {n}/{len(windows)}] {label}")

        if args.dry_run:
            doomed = [s for s in result_segments
                      if s["end"] > target[0] and s["start"] < target[1]]
            print(f"  would replace {len(doomed)} existing segments:")
            for s in doomed[:6]:
                print(f"      [{fmt_time(s['start'])}] {s['text'][:60]}")
            if len(doomed) > 6:
                print(f"      … and {len(doomed) - 6} more")
            print()
            continue

        new = transcribe_window(audio_path, target, args.backend, args.model,
                                args.language, args.pad, args.condition_on_previous)
        print(f"  → {len(new)} segments, {len(rebuild_text(new).split())} words")
        for s in new:
            print(f"      [{fmt_time(s['start'])}] {s['text']}")

        if base:
            result_segments, removed = splice(result_segments, target, new)
            print(f"  replaced {len(removed)} segments with {len(new)}\n")
        else:
            result_segments.extend(new)
            print()

    if args.dry_run:
        print("Dry run — nothing transcribed, nothing written.")
        return

    if args.merge and args.in_place:
        backup = Path(args.merge).with_suffix(Path(args.merge).suffix + ".bak")
        backup.write_text(Path(args.merge).read_text())
        print(f"Backed up original: {backup}")

    result_segments.sort(key=lambda s: (s["start"], s["end"]))
    save_output({"text": rebuild_text(result_segments), "segments": result_segments},
                output_path, True)


# ── Output ─────────────────────────────────────────────────────────────────────

def fmt_time(t):
    h, m, s = int(t // 3600), int((t % 3600) // 60), t % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def fmt_srt_time(t):
    h, m, s = int(t // 3600), int((t % 3600) // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def output_stem(path):
    """Strip a known transcript extension to get the stem save_output expects."""
    s = str(path)
    for ext in (".timestamped.txt", ".srt", ".txt"):
        if s.endswith(ext):
            return Path(s[: -len(ext)])
    return Path(s)


def save_output(result, output_path, timestamps):
    # Append rather than with_suffix() — stems legitimately contain dots
    # (e.g. "saved-transcript.fixed"), and with_suffix would eat them.
    output_path = Path(output_path)

    txt_path = Path(str(output_path) + ".txt")
    with open(txt_path, "w") as f:
        f.write(result["text"].strip())
    print(f"\nSaved: {txt_path}")

    if timestamps and result.get("segments"):
        ts_path = Path(str(output_path) + ".timestamped.txt")
        with open(ts_path, "w") as f:
            for seg in result["segments"]:
                f.write(f"[{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}]  {seg['text'].strip()}\n")
        print(f"Saved: {ts_path}")

        srt_path = Path(str(output_path) + ".srt")
        with open(srt_path, "w") as f:
            for i, seg in enumerate(result["segments"], 1):
                f.write(f"{i}\n{fmt_srt_time(seg['start'])} --> {fmt_srt_time(seg['end'])}\n{seg['text'].strip()}\n\n")
        print(f"Saved: {srt_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    # Convert SIGTERM into SystemExit so the tempfile context manager cleans up
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    parser = argparse.ArgumentParser(
        description="Transcribe audio with Whisper (chunked to prevent repetition bugs)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s beach.mp3
  %(prog)s beach.mp3 --model large-v3 --timestamps
  %(prog)s beach.mp3 --backend openai --model small
  %(prog)s beach.mp3 --chunk-size 5
  %(prog)s beach.mp3 --output my_transcript --timestamps
  %(prog)s beach.mp3 --language en

repairing a bad stretch (Whisper repetition loop) in an existing transcript:
  # see what would be replaced, without transcribing anything
  %(prog)s beach.m4a --merge transcript.timestamped.txt \\
      --window 1:49:54-1:50:21 --dry-run

  # re-transcribe three windows and splice them in, writing transcript.fixed.*
  %(prog)s beach.m4a --merge transcript.timestamped.txt \\
      --window 20:47-21:09 --window 1:39:45-1:39:48 --window 1:49:54-1:50:21

  # overwrite the transcript in place (a .bak is written first)
  %(prog)s beach.m4a --merge transcript.timestamped.txt \\
      --window 1:49:54-1:50:21 --in-place

  # just transcribe a window on its own, no merge
  %(prog)s beach.m4a --window 1:49:54-1:50:21 -o dinghy_window
        """,
    )
    parser.add_argument("audio", help="Audio file to transcribe")
    parser.add_argument(
        "--model", "-m",
        default="medium",
        choices=MODELS,
        help="Model size (default: medium). Bigger = slower but more accurate.",
    )
    parser.add_argument(
        "--backend", "-b",
        default="mlx",
        choices=["mlx", "openai"],
        help="Backend (default: mlx for Apple Silicon GPU)",
    )
    parser.add_argument(
        "--chunk-size", "-c",
        type=int,
        default=5,
        metavar="MINUTES",
        help="Max chunk length in minutes; splits at silence (default: 8)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path without extension (default: <audio>_transcript)",
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="Language code e.g. 'en' (auto-detect if omitted)",
    )
    parser.add_argument(
        "--timestamps", "-t",
        action="store_true",
        default=True,
        help="Also save timestamped .txt and .srt files (default: on)",
    )

    win = parser.add_argument_group("window repair")
    win.add_argument(
        "--window", "-w",
        type=parse_window,
        action="append",
        metavar="START-END",
        help="Re-transcribe only this stretch, e.g. 1:49:54-1:50:21 or 6594-6621. "
             "Repeatable.",
    )
    win.add_argument(
        "--merge",
        metavar="TIMESTAMPED_TXT",
        help="Existing .timestamped.txt to splice the window(s) into. "
             "Segments overlapping a window are replaced.",
    )
    win.add_argument(
        "--in-place",
        action="store_true",
        help="With --merge, overwrite the source transcript (saves a .bak first)",
    )
    win.add_argument(
        "--pad",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="Extra audio decoded either side of a window for context, then "
             "discarded (default: 15)",
    )
    win.add_argument(
        "--no-snap",
        dest="snap",
        action="store_false",
        help="Don't widen windows to whole segment boundaries when merging "
             "(risks truncating a segment that straddles the edge)",
    )
    win.add_argument(
        "--condition-on-previous",
        action="store_true",
        help="Let Whisper condition on prior text inside a window. Off by "
             "default — conditioning is what causes repetition loops.",
    )
    win.add_argument(
        "--dry-run",
        action="store_true",
        help="With --window, print what would be replaced and exit",
    )

    args = parser.parse_args()

    if args.merge and not args.window:
        parser.error("--merge requires at least one --window")
    if args.in_place and not args.merge:
        parser.error("--in-place requires --merge")

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"Error: file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = output_stem(args.output)
    elif args.merge:
        merge_stem = output_stem(args.merge)
        output_path = merge_stem if args.in_place else Path(str(merge_stem) + ".fixed")
    else:
        output_path = audio_path.parent / (audio_path.stem + "_transcript")

    print(f"Audio:    {audio_path}")
    print(f"Model:    {args.model}  backend={args.backend}", end="")
    print(f"  chunk={args.chunk_size}min" if not args.window else f"  pad={args.pad:.0f}s")
    if args.merge:
        print(f"Merge:    {args.merge}{'  (in place)' if args.in_place else ''}")
    print(f"Output:   {output_path}.txt")
    print()

    t0 = time.time()
    if args.window:
        run_windows(audio_path, sorted(args.window), args, output_path)
    else:
        result = transcribe(audio_path, args.backend, args.model, args.language, args.chunk_size)
        save_output(result, output_path, args.timestamps)
    print(f"\nDone in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
