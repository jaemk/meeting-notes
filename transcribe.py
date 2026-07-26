#!/usr/bin/env python3
"""
Transcribe audio files using Whisper.

Backends:
  mlx    - Apple Silicon GPU (fast; M-series Macs only)
  openai - CPU-based (slower, works everywhere)
  auto   - mlx when this machine can run it, openai otherwise (default)

Models (smallest/fastest → largest/most accurate):
  tiny, base, small, medium, large, large-v2, large-v3

Audio is read from local/ and transcripts are written to output/ (both
gitignored). A recording's name carries over to its transcript, so
local/2026-07-25.m4a becomes output/2026-07-25.txt and friends.

Long files are automatically split at silence boundaries to prevent
Whisper's hallucination/repetition bug on extended audio. Each chunk's
segments are held inside the audio that chunk covered — Whisper does not
stop where its audio does, and a tail that runs past the seam lands after
the next chunk's opening line. Whatever slips through anyway is found and
re-transcribed by the repair pass that runs automatically at the end
(--no-repair to skip it); see repair.py to run that diagnose/repair/verify
cycle against an existing transcript.
"""

import argparse
import importlib.util
import json
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
# Source audio lives in local/, everything written lands in output/. Both are
# gitignored, so nothing anyone actually says ends up in the repo.
INPUT_DIR = ROOT / "local"
OUTPUT_DIR = ROOT / "output"

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

BACKENDS = ["auto", "mlx", "openai"]

# Longest stretch handed to Whisper in one go, whether that is a slice of a
# whole file or a slice of a repair window. Both paths chunk the same way, so
# they share the default and repair.py takes the same -c flag.
DEFAULT_CHUNK_MINS = 5

# Below this a "chunk" is a WAV header with no audio in it: a model load, a
# decode and a temp file, all to transcribe nothing.
MIN_CHUNK_SECS = 0.5


# ── Backend selection ──────────────────────────────────────────────────────────

def is_apple_silicon():
    """mlx only exists for Apple's own GPUs — Darwin on arm64."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def mlx_installed():
    return importlib.util.find_spec("mlx_whisper") is not None


def resolve_backend(requested):
    """
    Turn 'auto' into a concrete backend, and reject 'mlx' where it cannot run.
    setup.sh only installs mlx-whisper on Apple Silicon, so everywhere else
    this quietly settles on openai instead of failing per-chunk at decode time.
    """
    if requested == "openai":
        return "openai"
    if requested == "mlx":
        if not is_apple_silicon():
            raise SystemExit(
                f"Error: --backend mlx needs Apple Silicon, this is "
                f"{platform.system()}/{platform.machine()}. Use --backend openai."
            )
        if not mlx_installed():
            raise SystemExit(
                "Error: --backend mlx requested but mlx-whisper is not installed. "
                "Run ./setup.sh"
            )
        return "mlx"
    return "mlx" if (is_apple_silicon() and mlx_installed()) else "openai"


# ── Where files live ───────────────────────────────────────────────────────────

def _resolve_in(path, directory):
    """
    Look a bare filename up in the directory this repo keeps that kind of file
    in, so `transcribe.py audio.m4a` finds local/audio.m4a. Anything with a
    directory component, or that already exists, is returned untouched.
    """
    p = Path(path)
    if p.exists() or p.is_absolute() or len(p.parts) > 1:
        return p
    candidate = directory / p.name
    return candidate if candidate.exists() else p


def resolve_input(path):
    """Audio is read from local/."""
    return _resolve_in(path, INPUT_DIR)


def resolve_transcript(path):
    """Transcripts were written to output/, so that is where they are read from."""
    return _resolve_in(path, OUTPUT_DIR)


def warn_if_committable(path):
    """
    Say so, loudly, when a transcript is about to be written somewhere in this
    repo that git is not ignoring. Only output/ is gitignored, and save_output
    creates whatever directory it is given, so `-o transcripts/mtg` quietly
    stages somebody's meeting for the next commit. A path outside the repo is
    the author's own business and passes without comment.

    Returns True when it warned, so this is testable without reading stderr.
    """
    try:
        resolved = Path(path).expanduser().resolve()
        resolved.relative_to(ROOT)              # inside the repo?
    except (ValueError, OSError, RuntimeError):
        return False
    try:
        resolved.relative_to(OUTPUT_DIR)        # ...and inside output/?
        return False
    except ValueError:
        pass
    print(f"Warning: {path} is inside the repo but not under {OUTPUT_DIR.name}/. "
          f"Only {OUTPUT_DIR.name}/ is gitignored, so this transcript can end up "
          f"in a commit. Use a bare name to write it to {OUTPUT_DIR.name}/.",
          file=sys.stderr)
    return True


def resolve_output(stem):
    """
    Transcripts are written to output/ unless a directory was named explicitly.
    Returns a stem — save_output appends .txt / .timestamped.txt / .srt.
    """
    p = output_stem(stem)
    if len(p.parts) > 1 or p.is_absolute():
        warn_if_committable(p)
        return p
    return OUTPUT_DIR / p.name


def default_output(audio_path):
    """output/<audio name> — the recording's own name carries over to its transcript."""
    return OUTPUT_DIR / Path(audio_path).stem


# ── Audio helpers ──────────────────────────────────────────────────────────────

# A file's length cannot change while it is being transcribed, and the window
# path asks for it once per decode attempt. One ffprobe per path is enough.
_DURATION_CACHE = {}


def get_duration(audio_path):
    key = str(audio_path)
    if key not in _DURATION_CACHE:
        r = subprocess.run(
            # -i, not a bare trailing path: a filename starting with '-' is
            # otherwise parsed by ffprobe as an option.
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
             "-i", key],
            capture_output=True, text=True, check=True,
        )
        _DURATION_CACHE[key] = float(json.loads(r.stdout)["format"]["duration"])
    return _DURATION_CACHE[key]


def silence_ends(audio_path, start=None, dur=None):
    """
    Timestamps where a silence of 0.3s+ ends, in absolute file time. With
    `start`/`dur` only that stretch is scanned — ffmpeg reports times relative
    to the seek point, so they are shifted back onto the file's own clock.
    """
    cmd = ["ffmpeg"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", str(audio_path),
            "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    base = start or 0.0
    return [base + float(m.group(1))
            for m in re.finditer(r"silence_end: ([\d.]+)", r.stderr)]


def chunk_tolerance(chunk_secs):
    """
    How far a cut may drift from its target to reach a silence. Half a chunk,
    capped: a piece that runs to 1.5× what was asked for is still short enough
    to be worth the cleaner boundary, but chasing a silence further than that
    rebuilds the long decode that -c was set to avoid.
    """
    return min(90.0, chunk_secs * 0.5)


def chunk_boundaries(start, end, chunk_secs, silences, tolerance=None,
                     verbose=False):
    """
    Cut [start, end] into pieces of about chunk_secs, landing each cut on the
    nearest silence within `tolerance` seconds of the target and falling back
    to a hard cut when there is none nearby. Returns the boundaries including
    both ends, so [a, b, c] means two chunks.
    """
    if chunk_secs < MIN_CHUNK_SECS:
        # Zero or negative never terminates: the tolerance collapses, no silence
        # is ever near, and each pass sets the next target to the split it just
        # made, so the list grows until memory runs out.
        raise ValueError(
            f"chunk_secs must be at least {MIN_CHUNK_SECS}s, got {chunk_secs}"
        )
    if tolerance is None:
        tolerance = chunk_tolerance(chunk_secs)
    splits = [start]
    target = start + chunk_secs
    while target < end - chunk_secs * 0.2:  # avoid a tiny tail chunk
        # A silence at the very end is not a cut. Recordings that fade out end
        # with one, and snapping to it appends `end` twice — a final chunk of
        # no audio at all, extracted as a header-only WAV and handed to Whisper.
        nearby = [t for t in silences
                  if splits[-1] < t < end - MIN_CHUNK_SECS
                  and abs(t - target) < tolerance]
        best = min(nearby, key=lambda t: abs(t - target)) if nearby else target
        splits.append(best)
        target = best + chunk_secs
        if verbose:
            print(f"chunk boundary at {best/60:.1f} min "
                  f"(next target {target/60:.1f} min)")
    # Belt and braces for the hard-cut path: a last cut that leaves only a
    # sliver folds back into the chunk before it rather than becoming its own.
    if len(splits) > 1 and end - splits[-1] < MIN_CHUNK_SECS:
        splits.pop()
    splits.append(end)
    return splits


def find_split_points(audio_path, chunk_secs, duration):
    """Chunk boundaries for a whole file."""
    print("detecting moments of silence")
    silences = silence_ends(audio_path)
    print(f"found {len(silences)} moments of silence")
    return chunk_boundaries(0.0, duration, chunk_secs, silences, verbose=True)


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
        # -ss/-t go before -i: an input seek jumps straight to the chunk, while
        # the same flags after -i make ffmpeg decode the whole file up to that
        # point and throw it away — seconds per extraction, an hour in, and
        # every repair window pays it again.
        ["ffmpeg", "-y", "-loglevel", "error",
         "-ss", str(start), "-t", str(dur),
         "-i", str(audio_path),
         "-ar", "16000", "-ac", "1",
         str(out_path)],
        check=True,
    )


# ── Transcription backends ─────────────────────────────────────────────────────

# whisper.load_model reads a multi-hundred-MB checkpoint off disk, so the loaded
# model is kept for the life of the process. One cache, shared by the whole-file
# path and the window path: a repair decodes slice after slice, and handing each
# one a fresh dict would reload the model for every slice of every attempt.
_OPENAI_CACHE = {}


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
    """
    Transcribe one prepared WAV. `backend` should already be through
    resolve_backend(); the fallback here only covers an mlx runtime failure
    (out of memory, a model repo that won't fetch) on a machine that does
    otherwise support it.
    """
    if backend == "mlx":
        try:
            return _transcribe_one_mlx(audio_path, model_name, language, condition_on_prev)
        except Exception as e:
            print(f"(mlx failed: {e}, using openai fallback)", end="  ")
    return _transcribe_one_openai(audio_path, model_name, language, cache, condition_on_prev)


def clamp_to_chunk(segments, start, end):
    """
    Hold a chunk's segments inside the audio that chunk actually covered.

    Whisper does not stop where its audio does. A chunk that ends mid-loop keeps
    emitting the same line with timestamps running past the end — 27 seconds
    past, on the recording this was written for. Chunks tile the file exactly,
    so anything beyond `end` is either the next chunk's speech, which is about
    to be decoded properly, or invented. Left alone it lands after the next
    chunk's opening line and the transcript's timestamps go backwards.

    A segment merely straddling the seam is clamped, not dropped: with no
    padding between chunks, the words before the seam exist in no other chunk.
    That is the difference from transcribe_window, which can drop a straddler
    because its neighbouring slice was decoded with the overlap.
    """
    kept = []
    for seg in segments:
        if seg["start"] >= end:
            continue
        seg = dict(seg)
        seg["end"] = min(seg["end"], end)
        if seg["end"] > seg["start"]:
            kept.append(seg)
    return kept


def seam_overruns(segments, tolerance=0.01):
    """
    Where a chunk's tail was merged past its seam. Each entry is (a, b, seam):
    segments[a:b] are the overrunning ones and `seam` is where the next chunk
    picks the file back up.

    Which side is which is not a guess. Chunk timestamps are offset by the
    chunk's own start, so a chunk's first segment can never predate its seam —
    when time runs backwards in a merged transcript it is the chunk before
    overrunning, never the chunk after starting early.
    """
    out = []
    for i in range(1, len(segments)):
        seam = segments[i]["start"]
        if seam >= segments[i - 1]["start"] - tolerance:
            continue
        j = i - 1
        while j >= 0 and segments[j]["start"] >= seam:
            j -= 1
        out.append((j + 1, i, seam))
    return out


def trim_seam_overruns(segments, confirm=None):
    """
    The retroactive twin of clamp_to_chunk, for a transcript already written.

    Drops what a chunk decoded past its seam and clamps whatever straddles it,
    leaving exactly what clamping during the merge would have. `confirm(seam)`
    vets each one — repair.py passes a check that the seam really is a chunk
    boundary, so a stretch of merely out-of-order timestamps is left alone.

    Returns (segments, trims) with a trim being (seam, dropped_segments).
    """
    drop, clamp_at, trims = set(), {}, []
    for a, b, seam in seam_overruns(segments):
        tail = segments[a:b]
        # Nothing is lost that was ever heard: a chunk's audio stops at its seam,
        # so a segment starting past it is invented, whether or not the next
        # chunk had much to say for that stretch. Confirming the seam is a real
        # boundary is the whole safeguard, which is why confirm() comes first.
        if confirm and not confirm(seam):
            continue
        drop.update(range(a, b))
        if a:
            clamp_at[a - 1] = seam
        trims.append((seam, tail))

    if not trims:
        return segments, []

    kept = []
    for i, seg in enumerate(segments):
        if i in drop:
            continue
        seam = clamp_at.get(i)
        if seam is not None and seg["start"] < seam < seg["end"]:
            seg = dict(seg, end=seam)   # keeps its words, ends at the seam
        kept.append(seg)
    return kept, trims


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
            result = _run_backend(chunk_path, backend, model_name, language, _OPENAI_CACHE)

            elapsed = time.time() - t0
            shifted = [dict(seg, start=seg["start"] + start, end=seg["end"] + start)
                       for seg in result.get("segments", [])]
            kept = clamp_to_chunk(shifted, start, end)
            # The .txt is rebuilt from the segments that survived, so it cannot
            # disagree with the .timestamped.txt about what was said.
            text = rebuild_text(kept) if shifted else result["text"].strip()
            print(f"→ {len(text.split())} words in {elapsed:.0f}s")
            if len(kept) < len(shifted):
                over = max(s["end"] for s in shifted) - end
                print(f"    dropped {len(shifted) - len(kept)} segment(s) running "
                      f"up to {over:.0f}s past the end of this chunk")

            all_text.append(text)
            all_segments += kept

    return {"text": " ".join(all_text), "segments": all_segments}


# ── Window re-transcription & merge ────────────────────────────────────────────

TS_LINE = re.compile(
    r"^\[(\d+):(\d\d):([\d.]+)\s*-->\s*(\d+):(\d\d):([\d.]+)\]\s*(.*)$"
)


def load_timestamped(path):
    """Read a .timestamped.txt back into segment dicts."""
    segments = []
    text = Path(path).read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
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


def window_slices(audio_path, start, end, chunk_secs):
    """
    Split a repair window the same way a whole file is split: pieces of about
    chunk_secs, cut at silence. A long single decode is exactly the condition
    that makes Whisper loop, and a repair window is somewhere it already has.
    Windows at or under one chunk are left alone — most are — so the common
    case costs no extra silence detection.
    """
    if end - start <= chunk_secs * 1.1:
        return [start, end]
    return chunk_boundaries(start, end, chunk_secs,
                            silence_ends(audio_path, start, end - start))


def _decode_span(audio_path, span, duration, backend, model_name, language,
                 pad_before, pad_after, condition_on_prev):
    """Decode [a, b] with context either side, on file time."""
    a, b = span
    dec_start = max(0.0, a - pad_before)
    dec_end = min(duration, b + pad_after)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "window.wav"
        padded = dec_end - dec_start - (b - a)
        pad_note = f" incl. {padded:.0f}s pad" if padded >= 0.5 else ""
        print(f"  extracting {fmt_time(dec_start)}–{fmt_time(dec_end)} "
              f"({dec_end - dec_start:.0f}s{pad_note})")
        extract_chunk(audio_path, dec_start, dec_end - dec_start, wav)

        t0 = time.time()
        result = _run_backend(wav, backend, model_name, language, _OPENAI_CACHE,
                              condition_on_prev)
        print(f"  decoded in {time.time() - t0:.0f}s")

    return [{"start": seg["start"] + dec_start, "end": seg["end"] + dec_start,
             "text": seg["text"].strip()}
            for seg in result.get("segments", [])]


def transcribe_window(audio_path, window, backend, model_name, language,
                      pad, condition_on_prev=False,
                      chunk_mins=DEFAULT_CHUNK_MINS):
    """
    Re-transcribe a single [start, end) window. `pad` seconds of extra audio
    are decoded on each side to give Whisper acoustic context, then dropped
    so the returned segments stay inside the window. Anything longer than
    chunk_mins is decoded in slices, cut at silence, exactly as a whole file is.
    """
    start, end = window
    duration = get_duration(audio_path)
    points = window_slices(audio_path, start, end, chunk_mins * 60)
    if len(points) > 2:
        print(f"  {end - start:.0f}s window — decoding in {len(points) - 1} "
              f"slices of ~{chunk_mins} min")

    # Each slice keeps the segments whose midpoint falls in it, so the union is
    # the same set a single decode would have kept — just assembled piecewise.
    # Padding goes on the outer edges only: an internal seam is a hard cut at
    # silence, as a chunk boundary is for a whole file. Padding across a seam
    # would let one slice transcribe the next one's opening words too, and both
    # copies would be spliced in.
    last = len(points) - 2
    shifted, kept = [], []
    for i, span in enumerate(zip(points[:-1], points[1:])):
        segs = _decode_span(audio_path, span, duration, backend, model_name,
                            language, pad if i == 0 else 0.0,
                            pad if i == last else 0.0, condition_on_prev)
        shifted += segs
        kept += [dict(s) for s in segs
                 if span[0] <= (s["start"] + s["end"]) / 2 < span[1]]

    def inside(seg):
        mid = (seg["start"] + seg["end"]) / 2
        return start <= mid < end

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

    removed, kept, insert_at = [], [], None
    for seg in segments:
        if hits(seg):
            removed.append(seg)
            # Every segment before the first overlap is a keeper, so the number
            # of keepers so far is exactly where the new material belongs.
            if insert_at is None:
                insert_at = len(kept)
        else:
            kept.append(seg)

    ordered = sorted(replacement, key=lambda s: (s["start"], s["end"]))
    if insert_at is None:
        # Nothing overlapped, which is what a gap window looks like — there is
        # no old segment for the new one to take the place of. Position it by
        # the clock instead. Appending would leave the transcript out of order,
        # and the next diagnose pass reads that as a rewind and re-decodes a
        # window that was never wrong.
        at = ordered[0]["start"] if ordered else start
        insert_at = next((i for i, s in enumerate(kept) if s["start"] > at),
                         len(kept))
    return kept[:insert_at] + ordered + kept[insert_at:], removed


def rebuild_text(segments):
    return " ".join(s["text"].strip() for s in segments if s["text"].strip())


def backup_file(path):
    """Copy path to path + '.bak' before it is overwritten in place."""
    src = Path(path)
    dest = src.with_suffix(src.suffix + ".bak")
    # Explicitly UTF-8 both ways. This round-trips the transcript through a
    # decode and an encode, so under a locale that is not UTF-8 it would mangle
    # the very copy that exists to undo an in-place repair.
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


# ── Output ─────────────────────────────────────────────────────────────────────

def fmt_time(t):
    # Truncated, not rounded, exactly as fmt_srt_time is: rounding 59.999 up
    # gives "00:00:60.00", a stamp that reads a whole minute early and does not
    # round-trip through load_timestamped as the same time. The epsilon keeps
    # binary float noise (0.29 held as 0.28999…) from truncating a real
    # hundredth away.
    h, m = int(t // 3600), int((t % 3600) // 60)
    cs = int((t - h * 3600 - m * 60) * 100 + 1e-6)
    return f"{h:02d}:{m:02d}:{cs // 100:02d}.{cs % 100:02d}"


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
    # (e.g. a recording named "2026-07-25"), and with_suffix would eat them.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Whisper output routinely contains non-ASCII; the encoding is pinned rather
    # than left to whatever locale the run happens to have.
    txt_path = Path(str(output_path) + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(result["text"].strip())
    print(f"\nSaved: {txt_path}")

    if timestamps and result.get("segments"):
        ts_path = Path(str(output_path) + ".timestamped.txt")
        with open(ts_path, "w", encoding="utf-8") as f:
            for seg in result["segments"]:
                f.write(f"[{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}]  {seg['text'].strip()}\n")
        print(f"Saved: {ts_path}")

        srt_path = Path(str(output_path) + ".srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(result["segments"], 1):
                f.write(f"{i}\n{fmt_srt_time(seg['start'])} --> {fmt_srt_time(seg['end'])}\n{seg['text'].strip()}\n\n")
        print(f"Saved: {srt_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

# The retry model when a window still loops after the first attempt. Stated
# here and in --help rather than left to repair.py's dataclass default, where a
# `--model tiny` draft run would silently fetch a multi-GB checkpoint.
DEFAULT_FALLBACK_MODEL = "large-v3"


def chunk_minutes(value):
    """
    argparse type for --chunk-size. Zero or negative never reaches chunking's
    guard — it hangs allocating boundaries — so it is refused at the CLI, where
    the user can still be told what was wrong with what they typed.
    """
    try:
        minutes = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"chunk size must be a whole number of minutes, got {value!r}")
    if minutes < 1:
        raise argparse.ArgumentTypeError(
            f"chunk size must be at least 1 minute, got {minutes}")
    return minutes


def repair_kwargs(args, backend, repair):
    """
    The RepairOptions this run's flags imply, as plain kwargs. `repair` is the
    module, passed in rather than imported, so which flag lands on which option
    is checkable on its own — and so this file keeps its deferred import (repair
    imports this module).
    """
    return dict(
        backend=backend,
        model=args.repair_model or args.model,
        # Passed explicitly: left unset it takes repair's own default, so a
        # small --model could still pull down the largest checkpoint there is.
        fallback_model=args.fallback_model,
        language=args.language,
        # Repair windows are sliced the same way this run's chunks were, so
        # the pass that cleans up a loop cannot re-create one by decoding a
        # longer stretch than the transcription itself was allowed.
        chunk_mins=args.chunk_size,
        # Repetitions only unless asked otherwise: those are the windows
        # this run demonstrably got wrong, and re-decoding them is minutes
        # of work rather than a second pass over most of the recording.
        targets=(repair.REPAIRABLE_KINDS if args.include_gaps
                 else repair.REPETITION_KINDS),
        passes=args.repair_passes,
        strict=args.strict,
        # Which gaps the audio says a decode could recover, read off this run's
        # flags by repair's own reader. Assembled there rather than here so the
        # three thresholds mean the same thing whether they arrived through
        # this CLI or repair.py's.
        gate=repair.gate_from_args(args),
    )


# The gap-dynamics thresholds the repair pass gates its decodes on. Named here
# only so this file can ask repair.py for those three flags by name; the
# numbers, the help text and the validation all stay over there. They sit
# within tenths of a dB of real measurements, which is exactly the kind of
# constant a second copy of gets edited on one side and not the other.
GATE_FLAGS = ("--ambient-peak-db", "--ambient-spread-db", "--off-mic-peak-db")


class FlagRecorder:
    """
    Stands in for an argparse parser long enough to record what would have been
    added to one. add_common's whole contract is that it calls .add_argument,
    so this needs nothing else — and asking repair.py for its flags this way
    keeps both files off argparse's internals.
    """

    def __init__(self):
        self.calls = []

    def add_argument(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def add_gate_flags(group, repair):
    """
    Lift repair.py's three dynamics thresholds onto this parser verbatim — same
    names, same defaults, same help. `repair` is the module, passed in for the
    same reason it is passed to repair_kwargs.

    Lifted rather than restated so that --help here promises exactly what the
    repair pass will do and moving a threshold stays one edit in one file. Only
    these three: the rest of add_common is repair.py's own surface, and
    --include-gaps already exists on this parser under the same name.
    """
    recorder = FlagRecorder()
    repair.add_common(recorder)
    lifted = [(a, kw) for a, kw in recorder.calls if a and a[0] in GATE_FLAGS]
    missing = set(GATE_FLAGS) - {a[0] for a, _ in lifted}
    if missing:
        # Loudly, rather than quietly dropping a flag the user is told exists:
        # a silently absent threshold is one that cannot be moved on this path,
        # which is the whole reason it is here.
        raise RuntimeError(
            f"repair.py no longer offers {sorted(missing)} — the automatic "
            f"repair pass and repair.py's CLI have to gate on the same flags")
    for a, kw in lifted:
        group.add_argument(*a, **kw)


def build_parser(repair=None):
    """
    `repair` is the module, supplying the gate thresholds' defaults and help
    text. Passed in where the caller already has it, imported on demand where
    it does not, because this file cannot import it at the top: repair.py
    imports this one.
    """
    if repair is None:
        import repair

    parser = argparse.ArgumentParser(
        description="Transcribe audio with Whisper (chunked to prevent repetition bugs)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s 2026-07-25.m4a                     # local/2026-07-25.m4a -> output/2026-07-25.*
  %(prog)s local/audio.m4a --model large-v3
  %(prog)s audio.m4a --backend openai --model small
  %(prog)s audio.m4a --chunk-size 5
  %(prog)s audio.m4a --output my_transcript   # -> output/my_transcript.*
  %(prog)s audio.m4a --language en

Audio is read from local/ and transcripts are written to output/, both of
which are gitignored. The transcript keeps the recording's name.

Every run ends with a diagnose → repair → verify pass that re-transcribes the
windows Whisper repeated itself in. Gaps are reported but left alone unless
you pass --include-gaps. Pass --no-repair to skip the whole thing, or use
repair.py to run that cycle against a transcript you already have.
        """,
    )
    parser.add_argument("audio", help="Audio file to transcribe (a bare name is looked up in local/)")
    parser.add_argument(
        "--model", "-m",
        default="medium",
        choices=MODELS,
        help="Model size (default: medium). Bigger = slower but more accurate.",
    )
    parser.add_argument(
        "--backend", "-b",
        default="auto",
        choices=BACKENDS,
        help="Backend (default: auto — mlx on Apple Silicon, else openai)",
    )
    parser.add_argument(
        "--chunk-size", "-c",
        type=chunk_minutes,
        default=DEFAULT_CHUNK_MINS,
        metavar="MINUTES",
        help=f"Max chunk length in minutes; splits at silence "
             f"(default: {DEFAULT_CHUNK_MINS}). Also used to slice any window "
             f"the repair pass re-decodes.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output stem, without extension (default: output/<audio name>)",
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="Language code e.g. 'en' (auto-detect if omitted)",
    )
    parser.add_argument(
        "--timestamps", "-t",
        dest="timestamps",
        action="store_true",
        default=True,
        help="Also save timestamped .txt and .srt files (default: on)",
    )
    parser.add_argument(
        "--no-timestamps",
        dest="timestamps",
        action="store_false",
        help="Write only the plain .txt, no .timestamped.txt and no .srt",
    )

    rep = parser.add_argument_group("automatic repair (runs after transcription)")
    rep.add_argument(
        "--no-repair",
        dest="repair",
        action="store_false",
        help="Skip the diagnose/repair/verify pass and keep the raw transcript",
    )
    rep.add_argument(
        "--repair-model",
        default=None,
        choices=MODELS,
        help="Model used to re-transcribe defective windows (default: same as --model)",
    )
    rep.add_argument(
        "--fallback-model",
        default=DEFAULT_FALLBACK_MODEL,
        choices=MODELS,
        help=f"Model a window is retried with when the first pass still loops "
             f"(default: {DEFAULT_FALLBACK_MODEL} — a large checkpoint, and "
             f"fetched on first use even when --model is a small one)",
    )
    rep.add_argument(
        "--repair-passes",
        type=int,
        default=2,
        metavar="N",
        help="Diagnose/repair rounds before the final check (default: 2)",
    )
    rep.add_argument(
        "--strict",
        action="store_true",
        help="Only splice a repaired window back in if it comes back completely clean",
    )
    rep.add_argument(
        "--include-gaps",
        action="store_true",
        help="Also re-decode gaps. Off by default: only repetitions (loops, "
             "stutters, boilerplate) are repaired, gaps are reported",
    )
    add_gate_flags(rep, repair)

    return parser


def main():
    # Convert SIGTERM into SystemExit so the tempfile context manager cleans up
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    import repair  # deferred: repair imports this module

    args = build_parser(repair).parse_args()

    # Before the recording is even looked for, let alone decoded: an incoherent
    # gate is a transcription that runs for hours and then declines to repair
    # anything, or repairs the wrong things. repair.py's own checker, so both
    # entry points refuse the same combinations for the same stated reasons.
    # min_run and min_gap are not flags here, so they are whatever the repair
    # options default to — which is what this run will actually use.
    repair_defaults = repair.RepairOptions()
    repair.check_settings(repair_defaults.min_run, repair_defaults.min_gap,
                          args.repair_passes, repair.gate_from_args(args))

    audio_path = resolve_input(args.audio)
    if not audio_path.exists():
        print(f"Error: file not found: {args.audio} (looked in {INPUT_DIR}/ too)",
              file=sys.stderr)
        sys.exit(1)

    backend = resolve_backend(args.backend)
    output_path = (resolve_output(args.output) if args.output
                   else default_output(audio_path))

    print(f"Audio:    {audio_path}")
    print(f"Model:    {args.model}  backend={backend}", end="")
    print(f"  ({args.backend})" if backend != args.backend else "", end="")
    print(f"  chunk={args.chunk_size}min")
    print(f"Output:   {output_path}.txt")
    print(f"Repair:   {'on' if args.repair else 'off'}")
    print()

    t0 = time.time()
    result = transcribe(audio_path, backend, args.model, args.language, args.chunk_size)
    save_output(result, output_path, args.timestamps)

    if args.repair:
        opts = repair.RepairOptions(**repair_kwargs(args, backend, repair))
        segments, report, _ = repair.diagnose_repair_verify(
            audio_path, result["segments"], opts, title="Automatic repair pass"
        )
        # Only rewrite the files if a window was actually spliced — a clean
        # transcript should not have its output touched a second time.
        if any(spliced for _, _, spliced, _, _ in report):
            segments.sort(key=lambda s: (s["start"], s["end"]))
            save_output({"text": rebuild_text(segments), "segments": segments},
                        output_path, args.timestamps)

    print(f"\nDone in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
