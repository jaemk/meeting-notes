"""
Shared bits for the test scripts: the assertion harness and the fixture.

Paths follow the same convention as the rest of the repo — inputs come from
local/, everything written goes to output/ — and are resolved relative to this
file, so the tests run from any working directory.

The transcript fixture used to be a real 140-minute recording. That is somebody's
actual conversation, so it is generated instead: build_fixture() plants exactly
the defects the tests exercise into neutral filler speech. Every number the
tests assert is therefore a property of this file rather than of a recording
nobody else has, and a fresh clone can run the suite.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

INPUT_DIR = ROOT / "local"
OUTPUT_DIR = ROOT / "output"


# ── The fixture ────────────────────────────────────────────────────────────────

# Ordinary speech to pad the timeline out. Deliberately free of repeated
# phrases and of anything in repair.CANNED, so the only defects in the fixture
# are the ones planted on purpose below.
FILLER = [
    "Okay, so where did we leave off last time?",
    "We were going through the second half of the schedule.",
    "That was the part nobody had signed off on yet.",
    "I think we agreed to push it out by a week.",
    "Which gives everyone time to review the numbers.",
    "Let me pull up the document while we talk.",
    "There is a section near the bottom about staffing.",
    "It reads a little vague to me, honestly.",
    "We can tighten the wording before it goes out.",
    "Does anyone want to take that on?",
    "I can draft something by Thursday afternoon.",
    "Great, let us move on to the next item.",
]

BIG_LOOP_TEXT = "Yeah, absolutely."
REWIND_LOOP_TEXT = "I'm not sure about that."
SHORT_LOOP_TEXT = "Right."
BEFORE_BIG_LOOP = "Anyway, back to the schedule for a moment."
AFTER_BIG_LOOP = "So that is the part I wanted to flag."


def build_fixture():
    """
    A synthetic transcript with known defects. Returns a namespace of what was
    planted where, so the tests can name a defect instead of hardcoding the
    timestamp it happens to land on.
    """
    segs, loops, gaps, duplicated = [], [], [], []
    t = 0.0

    def speech(n, seg=3.0, gap_after=0.0):
        nonlocal t
        for _ in range(n):
            segs.append({"start": t, "end": t + seg,
                         "text": FILLER[len(segs) % len(FILLER)]})
            t += seg
        if gap_after:
            # A stretch the transcript simply skips over — a dropped-speech gap.
            gaps.append((t, t + gap_after))
            t += gap_after

    def line(text, seg=3.0):
        nonlocal t
        segs.append({"start": t, "end": t + seg, "text": text})
        t += seg

    def loop(text, count, seg=1.0, rewind=0.0):
        """
        A repetition loop: the same line once a second. `rewind` restarts it
        that many seconds back on the clock, which is what Whisper does at a
        chunk seam — the timestamps go backwards and it re-covers, and so
        destroys, speech that was already transcribed correctly.
        """
        nonlocal t
        start = t - rewind
        index = len(segs)
        for i in range(count):
            segs.append({"start": start + i * seg,
                         "end": start + (i + 1) * seg, "text": text})
        loops.append(SimpleNamespace(index=index, count=count, text=text,
                                     start=start, end=start + count * seg))
        t = max(t, start + count * seg)

    speech(30, gap_after=15.0)
    speech(20, gap_after=12.0)
    speech(15)
    loop(SHORT_LOOP_TEXT, 4)              # a loop barely over the min_run threshold
    speech(20, gap_after=20.0)
    speech(25)
    line(BEFORE_BIG_LOOP)
    loop(BIG_LOOP_TEXT, 27)               # the big one, with a named line either side
    line(AFTER_BIG_LOOP)
    speech(20, gap_after=8.0)
    speech(1, gap_after=10.0)             # 3s of speech between two gaps: one window
    speech(4)
    for i in range(4):                    # the 12s the rewind loop will bury
        duplicated.append(f"This stretch gets buried by the rewind, part {i + 1}.")
        line(duplicated[-1])
    loop(REWIND_LOOP_TEXT, 22, rewind=12.0)
    speech(20, gap_after=30.0)
    speech(10, gap_after=6.0)
    speech(15)

    return SimpleNamespace(
        path=OUTPUT_DIR / "fixture.timestamped.txt",
        segments=segs,
        loops=loops,
        short_loop=loops[0],
        big_loop=loops[1],
        rewind_loop=loops[2],
        gaps=gaps,
        duplicated=duplicated,
        before_big=BEFORE_BIG_LOOP,
        after_big=AFTER_BIG_LOOP,
    )


def _fmt(t):
    h, m, s = int(t // 3600), int((t % 3600) // 60), t % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def write_fixture(fixture):
    """
    Write the fixture out in .timestamped.txt form. Formatted here rather than
    through transcribe.save_output so that load_timestamped is checked against
    an independent writer instead of against its own output.
    """
    fixture.path.parent.mkdir(parents=True, exist_ok=True)
    fixture.path.write_text("".join(
        f"[{_fmt(s['start'])} --> {_fmt(s['end'])}]  {s['text']}\n"
        for s in fixture.segments
    ))
    return fixture.path


FIXTURE = build_fixture()
write_fixture(FIXTURE)

FIXTURE_AUDIO = OUTPUT_DIR / "fixture-audio.wav"
# Where each stretch of that file falls, for the checks that measure it.
AUDIO_TONE = (0.0, 10.0)
AUDIO_SILENCE = (10.0, 20.0)
AUDIO_MIXED = (5.0, 25.0)


def build_audio_fixture():
    """
    Thirty seconds of tone / silence / tone. Telling a pause apart from
    dropped speech is the gap classifier's entire job and it does that by
    measuring sound, so those checks need real audio — but not anyone's
    recording. Returns None if ffmpeg is missing, so the checks skip instead.
    """
    if FIXTURE_AUDIO.exists():
        return FIXTURE_AUDIO
    FIXTURE_AUDIO.parent.mkdir(parents=True, exist_ok=True)
    tone = "sine=frequency=300:duration=10:sample_rate=16000"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", tone,
             "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=10",
             "-f", "lavfi", "-i", tone,
             "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1",
             "-ac", "1", str(FIXTURE_AUDIO)],
            check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return FIXTURE_AUDIO


# ── Harness ────────────────────────────────────────────────────────────────────

class Checks:
    def __init__(self):
        self.ok = self.failed = self.skipped = 0

    def section(self, title):
        print(f"— {title} —")

    def __call__(self, name, cond, extra=""):
        if cond:
            self.ok += 1
            print(f"  PASS {name}")
        else:
            self.failed += 1
            print(f"  FAIL {name} {extra}")

    def skip(self, name, why):
        self.skipped += 1
        print(f"  SKIP {name} ({why})")

    def raises(self, name, fn, *a, **kw):
        # SystemExit is a BaseException, and argparse/CLI guards raise it —
        # a bare `except Exception` would let those through as a crash.
        try:
            fn(*a, **kw)
        except (Exception, SystemExit):
            self(name, True)
        else:
            self(name, False, "no exception raised")

    def finish(self):
        tail = f", {self.skipped} skipped" if self.skipped else ""
        print(f"\n{self.ok} passed, {self.failed} failed{tail}")
        sys.exit(1 if self.failed else 0)
