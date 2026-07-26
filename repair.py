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

Only the repetitions are re-decoded by default. A loop or a stutter is text we
know is wrong and a window a minute long; gaps are far more numerous and are
mostly pauses the audio check could not rule out, so decoding them turns a
targeted fix into a re-run of most of the recording. --include-gaps opts in.

  ./repair.py diagnose audio.m4a audio.timestamped.txt
  ./repair.py repair   audio.m4a audio.timestamped.txt
  ./repair.py repair   audio.m4a audio.timestamped.txt -w 20:47-21:09
  ./repair.py verify   audio.repaired.timestamped.txt

Audio is looked up in local/ and transcripts in output/, so the bare names
above work from anywhere.

transcribe.py runs this same cycle automatically at the end of a transcription;
the commands above are for a transcript you already have, or for overriding
which windows get re-decoded.

Gaps are classified by measuring the audio underneath them: a gap over silence
is correct behaviour and is left alone, a gap over speech is lost content. Not
every gap over sound is speech, though, and level alone cannot tell them apart
— applause is as loud as a sentence. The dynamics can, so they gate which gaps
a decode is allowed to go to: loud and flat is applause or room noise and is
not a defect, quiet throughout is off-mic speech no decode has ever recovered,
and what is left in the middle is the bucket --include-gaps targets. The
thresholds are flags, because the recording they were measured on sits on top
of them.

A third failure needs no decoding at all. Whisper does not stop where its audio
does, so a chunk ending mid-loop keeps emitting past its seam and that tail
merges in after the next chunk's opening — timestamps running backwards. The
tail is text invented past the end of the chunk's own audio, so deleting it is
the entire repair. It runs first, before any window is chosen — a hallucinated
tail that is already gone needs no decode to remove it, and deleting it later
would mean walking back across text a repair had just spliced in. Nothing is
deleted until the recording confirms the seam is a real chunk boundary.

The last chunk overruns the same way and has no successor to give it away: a
backwards jump needs a next chunk to jump back from, and there isn't one. What
it leaves instead is a transcript that outlasts its own recording, so that is
what gets checked — the final segment's end against the file's duration.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

import transcribe as T


# Whisper repeating itself: a stretch it demonstrably got wrong, and short.
REPETITION_KINDS = ("loop", "stutter", "canned")
# Every kind a decode could in principle address. Gaps are here but not in
# REPETITION_KINDS: a gap is speech we may be missing rather than text we know
# is wrong, and on a real recording they outnumber the repetitions several to
# one, so repairing them by default turns a targeted fix into a broad re-run.
REPAIRABLE_KINDS = REPETITION_KINDS + ("gap",)
# The two buckets of gap a decode cannot recover, and so is not spent on. Both
# are found by measuring, both are reported with the numbers that put them
# there, and neither is in REPAIRABLE_KINDS — so --include-gaps widens the
# repair to the gaps in between and not to these.
AMBIENT = "ambient"     # loud and flat: applause, room noise, everyone at once
OFF_MIC = "off-mic"     # quiet throughout: below where the microphone heard
# A rewind is repaired by deleting what a chunk decoded past its seam, not by
# decoding anything, so it never joins the kinds above and never costs a window.
SEAM_TRIMMED = "seam overrun trimmed"
# Nor does the same overrun at the end of the recording, where there is no next
# chunk for the timestamps to run backwards into.
TAIL_TRIMMED = "tail past the end of the audio trimmed"
# Neither of those spends a window, and neither does declining to re-decode a
# window a previous pass already exhausted without splicing anything.
NOT_RETRIED = "not retried: nothing was spliced last time"
FREE_OF_DECODE = (SEAM_TRIMMED, TAIL_TRIMMED, NOT_RETRIED)


class GapGate(NamedTuple):
    """
    Which gaps a decode could actually recover. CLAUDE.md's triage, as numbers.

    A gap over sound is not automatically dropped speech, and the level cannot
    tell you which it is — applause is as loud as a sentence. The dynamics can:
    applause and room noise sit flat second to second, speech swings 10–20 dB.
    Two of the three buckets that produces are not repairs at all:

      loud and flat     applause, room noise, the whole room talking at once.
                        Running Whisper over it is precisely how a line of
                        boilerplate ends up stamped over a round of applause.
      quiet throughout  speech off the microphone, below where the VAD engages.
                        A plain re-decode returns nothing; amplifying first and
                        decoding that was tried on the recording these numbers
                        come from, and returned the surrounding speech
                        re-transcribed into the gap. Neither is recoverable in
                        post — that fix is at record time.

    What is left, mid-level with speech's own swing, is the bucket worth a
    decode and the one --include-gaps still targets.

    The defaults are the measured numbers from CLAUDE.md, and they are flags
    rather than constants because on that recording they cut through the middle
    of the data: several gaps sat a few tenths of a dB either side of the 9 dB
    spread line, so which side of it they land on is a decision worth being
    able to move without editing this file.
    """
    ambient_peak_db: float = -28.0
    ambient_spread_db: float = 9.0
    off_mic_peak_db: float = -32.0

    def bucket(self, lvl):
        """
        AMBIENT, OFF_MIC or "gap" for a measured stretch — or None where the
        dynamics could not be measured at all.

        None means *fall back to the level*, not "assume the worst". A gap too
        short to hold two whole seconds, or an ffmpeg that cannot slice, leaves
        no spread to read; deciding a bucket on the peak alone in that case
        would let one unsupported filter silently reclassify every gap in a
        recording at once, and OFF_MIC — quiet, and otherwise decided on the
        peak alone — is exactly the bucket that would swallow them. So both
        buckets want a spread, and without one nothing here decides anything.
        """
        if lvl is None or lvl.peak is None or lvl.spread is None:
            return None
        if lvl.peak > self.ambient_peak_db and lvl.spread < self.ambient_spread_db:
            return AMBIENT
        if lvl.peak < self.off_mic_peak_db:
            return OFF_MIC
        return "gap"


# One instance, shared by the dataclass default, the CLI defaults and the help
# text, so the number a run uses and the number --help promises cannot drift.
DEFAULT_GATE = GapGate()


@dataclass
class RepairOptions:
    """Everything repair needs to decode. Shared by the CLI and transcribe.py."""
    backend: str = "auto"
    model: str = "large-v2"
    fallback_model: str = "large-v3"
    language: Optional[str] = None
    pad: float = 15.0
    # A window longer than this is decoded in slices cut at silence, the same
    # way a whole file is — one long decode is what makes Whisper loop, and a
    # repair window is by definition somewhere it already has.
    chunk_mins: int = T.DEFAULT_CHUNK_MINS
    # Which defects earn a re-decode. Repetitions only, by default: those are
    # the windows where Whisper overwrote real speech with the same line over
    # and over, and the fix is worth the decode. Gaps are reported either way
    # and joined in with --include-gaps.
    targets: tuple = REPETITION_KINDS
    join_within: float = 5.0
    strict: bool = False
    passes: int = 2
    min_run: int = 3
    min_gap: float = 5.0
    check_audio: bool = True
    # Which gaps the audio says a decode could recover. Carried here rather
    # than read at the point of use so that the scan inside a repair run and
    # the `verify` that judges it afterwards gate on the same numbers.
    gate: GapGate = DEFAULT_GATE


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
        """Could be re-decoded. Whether it *is* depends on RepairOptions.targets."""
        return self.kind in REPAIRABLE_KINDS

    def __repr__(self):
        return (f"[{self.kind}] {T.fmt_time(self.start)}–{T.fmt_time(self.end)} "
                f"({self.end - self.start:.1f}s) {self.detail}")


class Level(NamedTuple):
    """What one measurement of a stretch of audio says about it."""
    mean: Optional[float]
    peak: Optional[float]
    silence: float
    dur: float
    peaks: tuple = ()           # the peak of each one-second slice, in order

    @property
    def spread(self):
        """
        dB between the quietest second and the loudest.

        Level alone does not tell speech from applause — both are loud. What
        separates them is the dynamics: applause and room noise sit flat, and
        speech swings 10–20 dB second to second. That is the triage in
        CLAUDE.md, and GapGate above is where it is applied. None where there
        are not two whole seconds to compare, which is a fact about the
        measurement and never a verdict — see GapGate.bucket.
        """
        return max(self.peaks) - min(self.peaks) if len(self.peaks) > 1 else None


# One spawn, asked for everything at once. silencedetect and volumedetect
# summarise the whole span on stderr; astats, downstream of them and so unable
# to disturb what they see, prints a peak per slice on stdout. The resample and
# asetnsamples are what make a slice a second of audio rather than however many
# samples the container's own frames happen to hold.
LEVEL_FILTERS = "silencedetect=noise=-40dB:d=0.5,volumedetect"
SLICE_FILTERS = (",aresample=16000,asetnsamples=n=16000:p=0,"
                 "astats=metadata=1:reset=1,"
                 "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-")

# A scan measures every gap and diagnose_repair_verify scans three or four
# times a run, mostly over gaps no splice went near. Keyed on the span rather
# than on the defect, so a re-derived gap that lands in the same place is
# recognised; a gap a repair actually moved gets measured again, as it must.
_LEVEL_CACHE = {}


def parse_peak_levels(text, dur=None):
    """
    The per-slice peaks out of one ametadata print.

    A digitally silent slice reports -inf, which is not a number and would
    swamp any spread computed with it, so it is left out. So is the remainder
    slice at the end of a span that did not divide evenly: a peak measured over
    a fraction of a second is not comparable with one measured over a whole one.
    """
    peaks = [float(x) for x in re.findall(r"Peak_level=(-?\d+\.?\d*)", text)]
    if dur and len(peaks) > 1 and len(peaks) > int(dur):
        peaks = peaks[:-1]
    return tuple(peaks)


def _run_level(audio_path, start, dur, per_slice=True):
    """One ffmpeg measuring pass. Returns (stderr, stdout)."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin",
         "-ss", str(start), "-t", str(dur), "-i", str(audio_path),
         "-af", LEVEL_FILTERS + (SLICE_FILTERS if per_slice else ""),
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return r.stderr, r.stdout


def _measure_level(audio_path, start, dur):
    err, out = _run_level(audio_path, start, dur)
    if "mean_volume:" not in err:
        # The per-slice filters are the only new thing in that chain, and an
        # ffmpeg that rejects one of them fails the whole command — which would
        # leave every gap unmeasured, and an unmeasured gap is reported as
        # speech. Classification rides on the level, so the level gets its own
        # attempt without them. Costs a second spawn only where the first
        # failed, i.e. never on a build that can do both.
        err, out = _run_level(audio_path, start, dur, per_slice=False)
    mean = re.search(r"mean_volume: ([-\d.]+) dB", err)
    peak = re.search(r"max_volume: ([-\d.]+) dB", err)
    silence = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err))
    return Level(float(mean.group(1)) if mean else None,
                 float(peak.group(1)) if peak else None,
                 silence, dur, parse_peak_levels(out, dur))


def audio_level(audio_path, start, end):
    """
    Mean/max dB, total detected silence, and a peak per second for a stretch of
    audio. Memoised on the span, so a stretch survives a scan without being
    re-measured by the next one.
    """
    dur = max(0.05, end - start)
    key = (str(audio_path), round(start, 2), round(dur, 2))
    if key not in _LEVEL_CACHE:
        _LEVEL_CACHE[key] = _measure_level(audio_path, start, dur)
    return _LEVEL_CACHE[key]


def gap_is_speech(audio_path, start, end, quiet_db=-50.0, silence_ratio=0.75):
    """
    True if there is audible content under a gap (i.e. anything at all).

    Level and silence only: this answers "is there sound here", which is the
    one question a level can answer. Which *kind* of sound it is belongs to
    GapGate, and classify_gap puts the two together. Kept apart because this
    half still has to stand on its own — where the dynamics cannot be measured
    it is the whole answer.
    """
    lvl = audio_level(audio_path, start, end)
    if lvl.mean is None:
        return True, "could not measure"
    spread = lvl.spread
    why = (f"mean {lvl.mean:.1f}dB, peak {lvl.peak:.1f}dB, "
           + (f"spread {spread:.1f}dB over {len(lvl.peaks)}×1s, "
              if spread is not None else "")
           + f"{lvl.silence:.1f}s/{lvl.dur:.0f}s silent")
    if lvl.silence / lvl.dur > silence_ratio or lvl.mean < quiet_db:
        return False, why
    return True, why


# What each verdict looks like on the diagnosis. Every one of them carries the
# measurement that produced it: these are decisions made about somebody's
# recording on three numbers, and the numbers are how you argue with them.
GAP_DETAIL = {
    "silence": "silent — ignoring ({why})",
    "gap": "speech under gap ({why})",
    AMBIENT: ("loud but flat — applause, room noise or the room at once, not "
              "dropped speech ({why})"),
    OFF_MIC: ("quiet throughout — off-mic speech the recording never captured "
              "({why})"),
}


def classify_gap(audio_path, start, end, gate=DEFAULT_GATE,
                 quiet_db=-50.0, silence_ratio=0.75):
    """
    What a gap is, from the audio underneath it. Returns (kind, why).

    Level first, because a gap over nothing is a pause and the transcript is
    right to have nothing there. Then the dynamics, which are what separate
    speech from the two kinds of loud-or-quiet sound no decode can turn into
    words. A gap the gate cannot bucket keeps the level's own verdict.
    """
    speech, why = gap_is_speech(audio_path, start, end, quiet_db, silence_ratio)
    if not speech:
        return "silence", why
    return gate.bucket(audio_level(audio_path, start, end)) or "gap", why


# A lone word this short, repeated, is how people talk rather than how Whisper
# breaks: "no no no no", "yes yes yes yes", "and and and and". Each false
# positive costs a ~15s decode that can replace correct text with worse text,
# and the segment-level loop detector still catches the same word repeated
# across segments. A repeated *phrase* is exempt — "the budget the budget the
# budget" is nobody's emphasis — and so is a short word repeated often enough
# that its pairs repeat too (eight of them match at n=2).
MIN_STUTTER_WORD = 5


def find_stutters(segments, min_reps=4):
    """A phrase repeated 4+ times inside a single segment."""
    out = []
    for i, seg in enumerate(segments):
        words = seg["text"].split()
        for n in range(1, 7):
            for st in range(max(0, len(words) - n * min_reps + 1)):
                phrase = words[st:st + n]
                if n == 1 and len(phrase[0]) < MIN_STUTTER_WORD:
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


# Whisper pads its final 30-second window with silence and rounds its
# timestamps, so the last segment can end a shade past where the file does
# without anything having been invented. A second is comfortably clear of that
# and nowhere near an overrun worth the name — the one this was written for ran
# 27 seconds past the end of its chunk's audio.
TAIL_TOLERANCE = 1.0


def tail_overrun(segments, audio_path, tolerance=TAIL_TOLERANCE):
    """
    What a decode stamped past the end of the recording. Returns
    (duration, invented) or None.

    `diagnose` only ever looks between consecutive segments, so the final chunk
    has nothing after it to give an overrun away — no next chunk means no
    backwards jump. It shows up instead as a transcript outlasting its own
    audio, and the argument for deleting it is the seam argument exactly: the
    audio stops, so anything stamped after it was never heard.

    Reading the container's duration is metadata rather than a measuring pass,
    so this is not gated on --no-audio-check the way the trim is: knowing costs
    nothing, and the flag turns off repairs, not reports.
    """
    if not segments or not audio_path:
        return None
    try:
        duration = T.get_duration(audio_path)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return None                     # unmeasurable: report nothing, guess nothing
    if max(s["end"] for s in segments) <= duration + tolerance:
        return None
    return duration, [s for s in segments if s["end"] > duration]


def diagnose(segments, audio_path=None, min_run=3, min_gap=5.0, check_audio=True,
             gate=DEFAULT_GATE):
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
            # Four verdicts, one of them repairable. The other three are each
            # reported with their measurement and cost no decode: a pause, a
            # loud flat stretch that is not speech, and speech the microphone
            # never got. Only the middle bucket is a window worth spending.
            kind, why = classify_gap(audio_path, a, b, gate)
            defects.append(Defect(kind, a, b, GAP_DETAIL[kind].format(why=why)))
        else:
            defects.append(Defect("gap", a, b, "unmeasured gap"))

    # Informational only — these do not warrant re-transcription
    for i in range(1, len(segments)):
        if segments[i]["start"] < segments[i - 1]["start"] - 0.01:
            defects.append(Defect("rewind", segments[i]["start"], segments[i]["end"],
                                  "timestamps go backwards (chunk merge artefact)"))

    # The same overrun at the end of the file, where nothing follows it to make
    # the timestamps run backwards. Deleted rather than decoded, so like a
    # rewind it is reported here and repaired elsewhere.
    found = tail_overrun(segments, audio_path)
    if found:
        duration, invented = found
        past = max(s["end"] for s in invented) - duration
        defects.append(Defect(
            "tail", duration, duration + past,
            f"{len(invented)} segment(s) run {past:.0f}s past the end of the "
            f"audio at {T.fmt_time(duration)}"))

    defects.sort(key=lambda d: d.start)
    return defects


def merge_windows(windows, join_within=5.0):
    """Coalesce windows that touch or nearly touch, so we decode each stretch once."""
    if not windows:
        return []
    # Sort once and seed from the sorted list. Seeding from windows[0] while
    # walking sorted(windows)[1:] silently dropped whichever window sorted
    # first when the caller handed them over out of order — a defect that would
    # never be decoded and never be mentioned.
    ordered = sorted(windows)
    out = [list(ordered[0])]
    for start, end in ordered[1:]:
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
        chunk_mins=opts.chunk_mins,
    )
    problems = []
    # The same threshold the diagnosis used. Judging the re-decode by the
    # default while the scan used --min-run would call a window "still looping"
    # that the final check then calls clean — two escalation decodes spent, and
    # under --strict a refusal to splice a result nothing objects to.
    if T.find_repeats(segs, opts.min_run):
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
        # An empty decode is never a candidate, however few problems it has to
        # its name: splicing nothing in place of the original deletes text that
        # was there. Whisper returning no segments is the ordinary outcome on a
        # quiet or off-mic window, so this is the common path, not the odd one.
        # Leaving `best` as None hands the window to the leaving-as-is branch.
        if segs and (best is None or len(problems) < len(best_problems)):
            best, best_problems = segs, problems
    return best, best_problems


def defect_windows(defects, join_within=5.0, kinds=REPETITION_KINDS):
    """
    The decode windows that cover the defects worth re-transcribing.

    `kinds` is the whole point of the repair pass being cheap: only the
    stretches Whisper actually got wrong are handed back to it, so the decode
    is a few minutes of a recording rather than the recording.
    """
    targets = [d for d in defects if d.kind in kinds]
    return merge_windows([(d.start, d.end) for d in targets], join_within)


def repair(audio_path, segments, windows, opts, dry_run=False, skip=()):
    """
    Re-transcribe each window and splice it into `segments`. This is the only
    place a window gets decoded and merged — automatic (windows from diagnose)
    and manual (windows from -w) repairs both come through here.

    `skip` holds windows an earlier pass already exhausted without splicing
    anything; they are reported rather than decoded a second time. The test is
    made here because it is made against the *snapped* window, which is the one
    that was really attempted.

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

        if target in skip:
            print("    ↷ every attempt was spent on this window already and "
                  "nothing was spliced — not decoding it again\n")
            report.append((target, NOT_RETRIED, False, old_words, old_words))
            continue

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
        if not new:
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
        # A partial splice is spliced all the same, so it needs a mark of its
        # own: a tick against a window that came back still looping is what
        # makes the "windows clean" count easier to read than the truth.
        print(f"    {'✓' if not problems else '⚠'} {len(removed)} segments "
              f"({old_words} words) → {len(new)} segments ({new_words} words)"
              + (f" — {'; '.join(problems)}" if problems else "") + "\n")
        report.append((target, status, True, old_words, new_words))

    return segments, report


def seam_confirmer(audio_path):
    """
    A chunk boundary is cut at the end of a silence, so a real seam has one
    underneath it. Only two seconds either side get scanned — the transcript
    already says where to look, and this runs once per rewind.
    """
    def confirm(seam):
        near = T.silence_ends(audio_path, max(0.0, seam - 2.0), 4.0)
        return any(abs(s - seam) <= 0.25 for s in near)
    return confirm


def trim_seams(audio_path, segments, opts, dry_run=False):
    """
    Delete what each chunk decoded past its seam. Returns (segments, trims).

    This needs the audio. Confirming the seam is a real chunk boundary is what
    keeps the trim from deleting speech out of a transcript whose timestamps
    are merely disordered — the one case where the text after the seam is the
    invention and the text before it is what was actually said. Without audio
    nothing is trimmed and it says so.
    """
    found = T.seam_overruns(segments)
    if not found:
        return segments, []
    if not (audio_path and opts.check_audio):
        print(f"\n{len(found)} seam overrun(s) left alone — trimming them needs "
              f"the audio, to confirm each seam is a chunk boundary.")
        return segments, []

    trimmed, trims = T.trim_seam_overruns(segments, seam_confirmer(audio_path))
    print_trims(trims, len(found), dry_run)
    return (segments if dry_run else trimmed), trims


def trim_tail(audio_path, segments, opts, dry_run=False):
    """
    Delete what the last chunk decoded past the end of the recording. Returns
    (segments, trim), a trim being (duration, dropped, clamped).

    The seam rules, for the one seam that is the end of the file. A segment
    stamped entirely after the audio ends is invented and goes; one straddling
    the end is clamped instead, because with no chunk after it those words
    exist nowhere else — the same rule clamp_to_chunk applies at merge time,
    written out here rather than borrowed so that nothing outside the overrun
    is touched. Free: nothing is decoded, and like the seam trim it runs before
    any window is chosen.

    Needs the audio. Without it, or under --no-audio-check, the overrun is
    reported and left alone — the conservative default rewinds already take.
    """
    found = tail_overrun(segments, audio_path)
    if not found:
        return segments, None
    duration, invented = found
    dropped = [s for s in invented if s["start"] >= duration]
    clamped = [s for s in invented if s["start"] < duration]
    if not opts.check_audio:
        print(f"\n{len(invented)} segment(s) past the end of the audio left alone "
              f"— trimming them is an audio-confirmed repair and the audio check "
              f"is off.")
        return segments, None
    print_tail_trim(duration, dropped, clamped, dry_run)
    if dry_run:
        return segments, (duration, dropped, clamped)
    kept = [s if s["end"] <= duration else dict(s, end=duration)
            for s in segments if s["start"] < duration]
    return kept, (duration, dropped, clamped)


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
        return diagnose(segs, audio_path, opts.min_run, opts.min_gap,
                        opts.check_audio, opts.gate)

    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(f"Targeting: {', '.join(opts.targets)}")

    # First, and deliberately. Trimming costs no decoding, and doing it before
    # anything is spliced is what keeps it safe: the walk back from a backwards
    # jump takes everything between it and the seam, which is the overrunning
    # tail *until* a repair has put freshly decoded text in that stretch — then
    # it is the repair's own output. Ordering the two is the whole fix. It also
    # makes the decode smaller, since a hallucinated tail no longer has to be
    # diagnosed and re-transcribed to get rid of it.
    segments, trims = trim_seams(audio_path, segments, opts, dry_run)
    report = [((seam, tail[-1]["end"]), SEAM_TRIMMED, not dry_run,
               sum(len(s["text"].split()) for s in tail), 0)
              for seam, tail in trims]

    # And the same thing at the end of the file, for the same price.
    segments, tail = trim_tail(audio_path, segments, opts, dry_run)
    if tail:
        duration, dropped, clamped = tail
        report.append((
            (duration, max(s["end"] for s in dropped + clamped)), TAIL_TRIMMED,
            not dry_run, sum(len(s["text"].split()) for s in dropped), 0))

    defects = scan(segments)
    print_diagnosis(defects, segments, opts.targets)

    # Windows whose repair plan was exhausted without splicing anything: strict
    # refusing the result, or a decode that came back empty. Nothing about such
    # a window changes — only a splice can change `segments` inside this loop,
    # and there wasn't one — so the next pass would re-derive the same window,
    # hand the same audio and the same options to a decoder that is greedy at
    # temperature 0, and arrive back where it started, a decode later. A
    # partial splice is a splice: that window's content did change and it stays
    # eligible. Keyed on the snapped window actually attempted, so a window
    # re-derived from a fresh diagnosis is recognised when it lands in the same
    # place and re-decoded when it does not.
    exhausted = set()

    for p in range(1, opts.passes + 1):
        # Explicit windows are coalesced like derived ones. Two -w flags that
        # overlap would otherwise be decoded separately, and the second splice
        # — widened to whole segments — replaces the first one's output, so the
        # first decode is paid for and then thrown away.
        todo = (merge_windows(windows, opts.join_within) if windows else
                defect_windows(defects, opts.join_within, opts.targets))
        if not todo:
            print(f"\nPass {p}: nothing left to repair.")
            break
        print(f"\n── Pass {p}/{opts.passes} " + "─" * 40)
        print(f"{len(todo)} decode window(s)\n")
        segments, rep = repair(audio_path, segments, todo, opts, dry_run, exhausted)
        report += rep
        exhausted.update(w for w, status, spliced, _, _ in rep
                         if not spliced and status != "dry-run")
        if dry_run or windows:
            break  # explicit windows are decoded once, not re-derived per pass
        defects = scan(segments)

    print_report(report)
    if not dry_run:
        print("\nFinal check:")
        defects = scan(segments)
        print_diagnosis(defects, segments, opts.targets)
        # Only what was aimed at counts against the verdict. A gap left behind
        # by a repetition-only run was never going to be decoded, so calling it
        # unresolved would fail every clean transcript.
        remaining = [d for d in defects if d.kind in opts.targets]
        untargeted = [d for d in defects
                      if d.repairable and d.kind not in opts.targets]
        print(f"\n✓ transcript is clean — no {'/'.join(opts.targets)} left."
              if not remaining else
              f"\n⚠ {len(remaining)} defect(s) still unresolved (listed above).")
        if untargeted:
            print(f"  {len(untargeted)} untargeted defect(s) reported but not "
                  f"repaired — re-run with --include-gaps to decode them too.")
    return segments, report, defects


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_diagnosis(defects, segments, targets=REPETITION_KINDS):
    kinds = {}
    for d in defects:
        kinds.setdefault(d.kind, []).append(d)

    if not defects:
        print("No defects found.")
    for kind in ("loop", "gap", "stutter", "canned", "silence", AMBIENT, OFF_MIC,
                 "rewind", "tail"):
        found = kinds.get(kind, [])
        if not found:
            continue
        total = sum(d.end - d.start for d in found)
        # A rewind reaching the diagnosis is one the trim already declined: no
        # recording to check, or nothing under the seam to confirm it. Decoding
        # was never the fix for it either way.
        #
        # A silence is not a defect that went unrepaired either: the transcript
        # is right to have nothing there, and the measurement says why.
        #
        # A tail is the same bargain as a rewind: text stamped after the audio
        # ends, deleted rather than decoded, and only where the recording is
        # there to say where it ends.
        #
        # The two gated buckets get the silence treatment and for the silence
        # reason: neither is a repair anybody declined to make. Loud and flat is
        # not dropped speech at all, and off-mic speech is not in the recording
        # to be recovered — the numbers beside each row are the argument, and
        # the flags are how you disagree with it.
        note = ("  — merge artefact, only trimmed where the recording confirms "
                "the seam" if kind == "rewind"
                else "  — correct behaviour, nothing to repair" if kind == "silence"
                else "  — correct behaviour: loud but flat is applause or room "
                     "noise, and decoding it invents text" if kind == AMBIENT
                else "  — unrecoverable from this recording: below the "
                     "microphone, so the fix is at record time, not another "
                     "decode" if kind == OFF_MIC
                else "  — decoded past the end of the recording, deleted rather "
                     "than decoded" if kind == "tail"
                else "" if kind in targets else "  — reported, not repaired")
        print(f"\n{kind.upper()}  ({len(found)}, {total:.0f}s total){note}")
        for d in found:
            print(f"  {T.fmt_time(d.start)}–{T.fmt_time(d.end)}  "
                  f"({d.end - d.start:5.1f}s)  {d.detail}")

    targeted = [d for d in defects if d.kind in targets]
    affected = sum(d.end - d.start for d in targeted)
    span = segments[-1]["end"] - segments[0]["start"] if segments else 0
    print(f"\n{len(segments)} segments over {span/60:.0f} min")
    print(f"{len(targeted)} targeted defects affecting {affected:.0f}s "
          f"({affected/span*100:.1f}% of the recording)" if span else "")


def print_trims(trims, found, dry_run=False):
    if not trims:
        print(f"\nSeam overruns: none of the {found} candidate(s) sit on a chunk "
              f"boundary — left alone.")
        return
    total = sum(len(tail) for _, tail in trims)
    print(f"\nSEAM OVERRUNS — {'would drop' if dry_run else 'dropped'} {total} "
          f"segment(s) at {len(trims)}/{found} seam(s), decoded past the end of "
          f"their own chunk")
    for seam, tail in trims:
        print(f"  {T.fmt_time(seam)}  {len(tail)} segment(s), running "
              f"{tail[-1]['end'] - seam:.0f}s past the seam")
        for s in tail[:2]:
            print(f"      [{T.fmt_time(s['start'])}] {s['text'][:60]}")
        if len(tail) > 2:
            print(f"      … and {len(tail) - 2} more")


def print_tail_trim(duration, dropped, clamped, dry_run=False):
    past = max((s["end"] for s in dropped + clamped), default=duration) - duration
    print(f"\nTAIL PAST THE END OF THE AUDIO — "
          f"{'would drop' if dry_run else 'dropped'} {len(dropped)} segment(s) "
          f"and {'would clamp' if dry_run else 'clamped'} {len(clamped)}, running "
          f"{past:.0f}s past the recording's own end at {T.fmt_time(duration)}")
    for s in (clamped + dropped)[:3]:
        print(f"      [{T.fmt_time(s['start'])}] {s['text'][:60]}")
    if len(dropped) + len(clamped) > 3:
        print(f"      … and {len(dropped) + len(clamped) - 3} more")


def print_report(report):
    if not report:
        return
    print("=" * 60)
    # The rows that cost no decode are counted apart: a trim can't come back
    # dirty and a window that wasn't re-decoded didn't come back at all, so
    # folding either in would move the decode success rate on its own.
    decoded = [r for r in report if r[1] not in FREE_OF_DECODE]
    ok = sum(1 for _, s, _, _, _ in decoded if s == "repaired")
    print(f"REPAIR SUMMARY — {ok}/{len(decoded)} windows clean"
          if decoded else "REPAIR SUMMARY")
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
                   help="Skip measuring audio under gaps (faster, less accurate) "
                        "and skip confirming seams, which disables rewind "
                        "trimming and the trim of a tail past the end of the "
                        "recording — every gap is then reported as speech and "
                        "no chunk overrun is deleted")
    # On diagnose/verify this decides the exit status, on repair which windows
    # are decoded — deliberately the same flag, so the gate and the repairer
    # never disagree about what counts as a defect worth acting on.
    p.add_argument("--include-gaps", action="store_true",
                   help="Also target gaps. Off by default: only repetitions "
                        "(loops, stutters, boilerplate) are re-decoded")
    # The dynamics gate. These decide which gaps --include-gaps can even reach:
    # a gap ruled applause or ruled off-mic is reported with its numbers and
    # never becomes a window. Flags rather than constants because on the
    # recording the defaults were measured on, three of the fifteen gaps sat
    # within 0.3 dB of the spread line — the thresholds run through the data,
    # not around it, so being able to move them is part of the tool.
    p.add_argument("--ambient-peak-db", type=float,
                   default=DEFAULT_GATE.ambient_peak_db, metavar="DB",
                   help=f"A gap peaking above this and flatter than "
                        f"--ambient-spread-db is applause, room noise or the "
                        f"whole room at once — reported, never decoded "
                        f"(default: {DEFAULT_GATE.ambient_peak_db}). Raise it "
                        f"to send more loud gaps for a decode; lower it to "
                        f"leave more of them alone")
    p.add_argument("--ambient-spread-db", type=float,
                   default=DEFAULT_GATE.ambient_spread_db, metavar="DB",
                   help=f"dB between a gap's quietest and loudest second below "
                        f"which it counts as flat, i.e. not speech "
                        f"(default: {DEFAULT_GATE.ambient_spread_db}; speech "
                        f"swings 10–20). Raise it to gate out more gaps, lower "
                        f"it to decode more — real gaps sit either side of the "
                        f"default, so a small move changes verdicts")
    p.add_argument("--off-mic-peak-db", type=float,
                   default=DEFAULT_GATE.off_mic_peak_db, metavar="DB",
                   help=f"A gap peaking below this is speech off the "
                        f"microphone, below where the VAD engages — reported, "
                        f"never decoded, because a re-decode returns nothing "
                        f"and amplifying first returns the neighbours "
                        f"(default: {DEFAULT_GATE.off_mic_peak_db}). Lower it "
                        f"to send quieter gaps for a decode anyway")


def gate_from_args(args):
    """
    The gap gate this run's flags imply. One place, so that `verify`'s exit
    status and `repair`'s window selection can never gate on different numbers
    — the same reason --include-gaps is shared between them.
    """
    return GapGate(args.ambient_peak_db, args.ambient_spread_db,
                   args.off_mic_peak_db)


def fail(message):
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def require_file(path, resolver, directory, kind):
    """
    Resolve a bare name the way this repo lays files out, and insist it is
    really there. A missing recording is otherwise indistinguishable from an
    unmeasurable one: ffmpeg reports no level, so every gap reads as speech,
    every seam goes unconfirmed and nothing is trimmed, and the run says none
    of that happened. A missing transcript is a bare traceback out of the
    loader.
    """
    resolved = resolver(path)
    if not Path(resolved).exists():
        fail(f"{kind} not found: {path} (looked in {directory}/ too)")
    return resolved


def check_settings(min_run, min_gap, passes, gate=DEFAULT_GATE):
    """
    Reject thresholds that ask for something incoherent. Each of these looks
    like a tuning knob and is really an instruction to do the wrong thing to
    the whole recording.
    """
    # Peaks are dBFS: 0 is full scale and nothing measures above it. A gate
    # placed there or beyond is not a strict setting, it is a bucket that
    # either everything or nothing falls into, and both are silent.
    if gate.ambient_peak_db >= 0:
        fail("--ambient-peak-db must be below 0 — peaks are dBFS and never "
             "reach it, so no gap is ever loud enough and the applause bucket "
             "is switched off while looking like it was merely tightened")
    if gate.off_mic_peak_db >= 0:
        fail("--off-mic-peak-db must be below 0 — every gap peaks below 0 dBFS, "
             "so all of them read as off-mic and no gap is ever repairable")
    if gate.ambient_spread_db <= 0:
        fail("--ambient-spread-db must be greater than 0 — a spread is the "
             "distance between two measurements and is never negative, so this "
             "silently empties the applause bucket rather than narrowing it")
    if gate.ambient_peak_db < gate.off_mic_peak_db:
        fail("--ambient-peak-db must be at or above --off-mic-peak-db — below "
             "it the two buckets overlap, and a gap would be both too loud to "
             "be dropped speech and too quiet to have been heard at all")
    if min_run < 2:
        fail("--min-run must be at least 2 — a run of one identical line is "
             "every segment, i.e. a request to re-decode the whole recording")
    if min_gap <= 0:
        fail("--min-gap must be greater than 0 — every pair of segments is at "
             "least 0 seconds apart, so every one of them becomes a gap")
    if passes < 1:
        fail("--passes must be at least 1 — fewer repairs nothing at all and "
             "still writes an output file")


def main():
    ap = argparse.ArgumentParser(
        description="Diagnose and repair Whisper loops and dropped-audio gaps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s diagnose audio.m4a audio.timestamped.txt
  %(prog)s repair   audio.m4a audio.timestamped.txt --model large-v2 -l en
  %(prog)s repair   audio.m4a audio.timestamped.txt --in-place
  %(prog)s repair   audio.m4a audio.timestamped.txt -w 20:47-21:09 --dry-run
  %(prog)s verify   audio.repaired.timestamped.txt

Audio is looked up in local/ and transcripts in output/, so bare names work.
With no -w the windows come from the diagnosis — the repetitions it found,
plus gaps if you pass --include-gaps; with -w only those stretches are
re-decoded. Either way it is the same splice-and-recheck path.
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
    r.add_argument("--chunk-size", "-c", type=int, default=T.DEFAULT_CHUNK_MINS,
                   metavar="MINUTES",
                   help=f"Slice windows longer than this and decode them a piece "
                        f"at a time, cut at silence, as transcribe.py does with a "
                        f"whole file (default: {T.DEFAULT_CHUNK_MINS})")
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
    gate = gate_from_args(args)
    check_settings(args.min_run, args.min_gap, getattr(args, "passes", 1), gate)
    # Audio comes from local/, transcripts from output/ — a bare name on the
    # command line is looked up there rather than only in the cwd.
    args.transcript = require_file(args.transcript, T.resolve_transcript,
                                   T.OUTPUT_DIR, "transcript")
    if getattr(args, "audio", None):
        args.audio = require_file(args.audio, T.resolve_input,
                                  T.INPUT_DIR, "audio file")
    segments = T.load_timestamped(args.transcript)
    targets = REPAIRABLE_KINDS if args.include_gaps else REPETITION_KINDS

    if args.cmd in ("verify", "diagnose"):
        # diagnose takes audio positionally, verify as an optional flag; both
        # land on args.audio and both gate the exit status on what they find.
        defects = diagnose(segments, args.audio, args.min_run, args.min_gap,
                           args.check_audio and bool(args.audio), gate)
        print_diagnosis(defects, segments, targets)
        sys.exit(1 if any(d.kind in targets for d in defects) else 0)

    print(f"Loaded {len(segments)} segments from {args.transcript}")
    opts = RepairOptions(
        backend=T.resolve_backend(args.backend), model=args.model,
        fallback_model=args.fallback_model, language=args.language,
        pad=args.pad, chunk_mins=args.chunk_size, targets=targets,
        join_within=args.join_within,
        strict=args.strict, passes=args.passes, min_run=args.min_run,
        min_gap=args.min_gap, check_audio=args.check_audio, gate=gate,
    )
    print(f"Backend:  {opts.backend}  model={opts.model} "
          f"(fallback {opts.fallback_model})  chunk={opts.chunk_mins}min")

    segments, report, defects = diagnose_repair_verify(
        args.audio, segments, opts, windows=sorted(args.window or []) or None,
        dry_run=args.dry_run, title=f"Repairing {args.transcript}",
    )

    if args.dry_run:
        print("\nDry run — nothing transcribed, nothing written.")
        sys.exit(0)

    stem = (T.resolve_output(args.output) if args.output
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
