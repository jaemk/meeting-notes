"""
Shared bits for the test scripts: the assertion harness and the fixture paths.

Paths are resolved relative to this file rather than hardcoded, so the tests
run from any working directory and follow the repo if it moves.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# A real 140-minute transcript with three known Whisper loops in it.
SAVED_TRANSCRIPT = ROOT / "saved-transcript.timestamped.txt"
# The audio it came from. Gitignored — audio-dependent checks skip without it.
SAMPLE_AUDIO = ROOT / "local" / "beach.m4a"


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
