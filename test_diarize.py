#!/usr/bin/env python3
"""
Checks for diarize.py. Nothing here loads pyannote or touches the network —
the assignment logic is pure and takes turns as data, which is the whole
reason `run` and `apply` are separate commands.
"""

import json
import subprocess
import sys

from testlib import FIXTURE, OUTPUT_DIR, ROOT, Checks

import diarize as D

check = Checks()


def seg(start, end, text="words here"):
    return {"start": start, "end": end, "text": text}


def turn(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


# ── overlap and spread ────────────────────────────────────────────────────────

check.section("measuring how much of a segment each voice holds")

check("two spans that do not touch share nothing",
      D.overlap(0, 5, 10, 15) == 0)
check("a span touching only at the instant it ends shares nothing",
      D.overlap(0, 5, 5, 10) == 0)
check("a span sitting entirely inside another shares its whole length",
      D.overlap(0, 10, 2, 5) == 3)
check("a partial straddle shares only the part in common",
      D.overlap(0, 10, 8, 20) == 2)

_turns = [turn(0, 4, "A"), turn(4, 10, "B")]
_spread = D.speaker_spread(_turns, 0, 10)
check("a segment spanning two voices is split between them by seconds",
      _spread == {"A": 4, "B": 6}, _spread)
check("a segment over a stretch nobody spoke in gets nothing",
      D.speaker_spread(_turns, 20, 30) == {})


# ── assignment ────────────────────────────────────────────────────────────────

check.section("attributing a segment to the voice holding most of it")

_rows = D.assign([seg(0, 10)], [turn(0, 9, "SPEAKER_01")])
check("a segment one voice covers is attributed to that voice",
      _rows[0]["speaker"] == "SPEAKER_01", _rows[0])
check("and is not marked unclear when nobody else is present",
      _rows[0]["contested"] is False)
check("its share is the whole of the diarized speech",
      _rows[0]["share"] == 1.0, _rows[0]["share"])

_rows = D.assign([seg(0, 10)], [turn(0, 8, "A"), turn(8, 10, "B")])
check("a clear majority wins outright rather than being called unclear",
      _rows[0]["speaker"] == "A" and not _rows[0]["contested"], _rows[0])

_rows = D.assign([seg(0, 10)], [turn(0, 5, "A"), turn(5, 10, "B")])
check("a segment split evenly between two voices is marked unclear",
      _rows[0]["contested"] is True, _rows[0])
check("and still names the larger side rather than discarding it",
      _rows[0]["speaker"] == "A")

check.section("saying nothing when nothing can honestly be said")

_rows = D.assign([seg(0, 10)], [])
check("a segment with no diarized speech under it is left unattributed",
      _rows[0]["speaker"] is None, _rows[0])
check("an unattributed segment is not also flagged unclear",
      _rows[0]["contested"] is False)

_rows = D.assign([seg(0, 10)], [turn(0, 1, "A")])
check("a trace of speech under a long segment is not enough to attribute it",
      _rows[0]["speaker"] is None, _rows[0])
_rows = D.assign([seg(0, 10)], [turn(0, 1, "A")], min_overlap=0.05)
check("lowering the overlap threshold does attribute that same segment",
      _rows[0]["speaker"] == "A", _rows[0])

_rows = D.assign([seg(0, 0)], [turn(0, 5, "A")])
check("a zero-length segment is left alone instead of dividing by zero",
      _rows[0]["speaker"] is None)

check.section("the thresholds are the knobs the reader turns")

_two = [turn(0, 6, "A"), turn(6, 10, "B")]
check("a stricter contested ratio marks more segments unclear",
      D.assign([seg(0, 10)], _two, contested_ratio=0.6)[0]["contested"] is True)
check("a looser one lets the same segment stand as attributed",
      D.assign([seg(0, 10)], _two, contested_ratio=0.8)[0]["contested"] is False)

check("a segment no second voice appears in is never unclear, at any ratio",
      D.assign([seg(0, 10)], [turn(0, 9, "A")], contested_ratio=0.0)[0]["contested"]
      is False,
      D.assign([seg(0, 10)], [turn(0, 9, "A")], contested_ratio=0.0)[0])
check("but a genuine second voice is unclear at a ratio of zero",
      D.assign([seg(0, 10)], [turn(0, 9, "A"), turn(9, 10, "B")],
               contested_ratio=0.0)[0]["contested"] is True)

check("the shipped default is the value the recording was read against",
      D.CONTESTED_RATIO == 0.7, D.CONTESTED_RATIO)

check("turns handed in out of order are still counted in full",
      D.assign([seg(0, 10)], [turn(6, 10, "B"), turn(0, 6, "A")])[0]["speaker"]
      == "A", D.assign([seg(0, 10)], [turn(6, 10, "B"), turn(0, 6, "A")])[0])

check("assignment keeps the segment's own text and timing untouched",
      D.assign([seg(3, 9, "hello there")], [turn(3, 9, "A")])[0]["text"]
      == "hello there")
check("every segment handed in comes back out, in order",
      [r["start"] for r in D.assign([seg(0, 2), seg(2, 4), seg(4, 6)],
                                    [turn(0, 6, "A")])] == [0, 2, 4])


# ── grouping ──────────────────────────────────────────────────────────────────

check.section("grouping consecutive segments into turns")

_rows = D.assign([seg(0, 2), seg(2, 4), seg(4, 6)], [turn(0, 6, "A")])
check("an unbroken run by one voice becomes a single turn",
      len(D.blocks(_rows)) == 1, len(D.blocks(_rows)))

_rows = D.assign([seg(0, 2), seg(2, 4)], [turn(0, 2, "A"), turn(2, 4, "B")])
check("a change of voice starts a new turn",
      len(D.blocks(_rows)) == 2)

_rows = [dict(seg(0, 2), speaker="A", share=1.0, contested=False, mix=["A"]),
         dict(seg(2, 4), speaker="A", share=0.5, contested=True, mix=["A", "B"]),
         dict(seg(4, 6), speaker="A", share=1.0, contested=False, mix=["A"])]
check("an unclear segment breaks the run instead of joining either side",
      len(D.blocks(_rows)) == 3, len(D.blocks(_rows)))

check("consecutive unattributed segments group together",
      len(D.blocks([dict(seg(0, 2), speaker=None, share=0.0, contested=False, mix=[]),
                    dict(seg(2, 4), speaker=None, share=0.0, contested=False, mix=[])])) == 1)

_hand_off = [dict(seg(0, 2), speaker="A", share=0.5, contested=True, mix=["A", "B"]),
             dict(seg(2, 4), speaker="B", share=0.5, contested=True, mix=["B", "A"]),
             dict(seg(4, 6), speaker="A", share=0.5, contested=True, mix=["A", "B"])]
check("consecutive contested segments spanning the same pair group as one turn",
      len(D.blocks(_hand_off)) == 1, len(D.blocks(_hand_off)))
_two_pairs = [dict(seg(0, 2), speaker="A", share=0.5, contested=True, mix=["A", "B"]),
              dict(seg(2, 4), speaker="C", share=0.5, contested=True, mix=["C", "D"])]
check("but a contested run spanning a different pair starts a new turn",
      len(D.blocks(_two_pairs)) == 2, len(D.blocks(_two_pairs)))


# ── labelling ─────────────────────────────────────────────────────────────────

check.section("labels are cluster numbers and never names")

check("a pyannote label reads as a plain speaker number",
      D.label_for("SPEAKER_07", False) == "Speaker 7",
      D.label_for("SPEAKER_07", False))
check("an unattributed segment says so rather than guessing a speaker",
      D.label_for(None, False) == "unattributed")
check("an unclear segment says it spans a hand-off",
      "hand-off" in D.label_for("SPEAKER_01", True))
check("with no mix recorded it still declines to name one side",
      "Speaker 1" not in D.label_for("SPEAKER_01", True))
check("a label that is not numbered is passed through as it came",
      D.label_for("MODERATOR", False) == "MODERATOR")

check.section("a contested segment names every voice in it, not none of them")

_mixed_label = D.label_for("SPEAKER_02", True, ["SPEAKER_02", "SPEAKER_24"])
check("both clusters it spans are named",
      _mixed_label == "Speakers 2 and 24 (spans a hand-off)", _mixed_label)
check("it still says it spans a hand-off, so neither is read as the speaker",
      "hand-off" in _mixed_label)
check("three voices are listed with a serial comma-free join",
      D.label_for("A", True, ["SPEAKER_02", "SPEAKER_24", "SPEAKER_38"])
      == "Speakers 2, 24 and 38 (spans a hand-off)",
      D.label_for("A", True, ["SPEAKER_02", "SPEAKER_24", "SPEAKER_38"]))
check("the word Speakers is said once, not once per cluster",
      _mixed_label.count("Speaker") == 1, _mixed_label)
check("a mix of numbered and unnumbered labels joins them whole instead",
      D.label_for("M", True, ["MODERATOR", "SPEAKER_04"])
      == "MODERATOR and Speaker 4 (spans a hand-off)",
      D.label_for("M", True, ["MODERATOR", "SPEAKER_04"]))
check("a mix of one is not a mix, so the old wording stands",
      D.label_for("SPEAKER_01", True, ["SPEAKER_01"])
      == "unclear (spans a hand-off)")
check("an uncontested segment ignores the mix entirely",
      D.label_for("SPEAKER_01", False, ["SPEAKER_01", "SPEAKER_02"])
      == "Speaker 1")

_row = D.assign([seg(0, 10)], [turn(0, 5, "A"), turn(5, 10, "B")])[0]
check("the mix comes out of assign already ordered by share",
      D.assign([seg(0, 10)], [turn(0, 4, "A"), turn(4, 10, "B")],
               contested_ratio=0.5)[0]["mix"] == ["B", "A"],
      D.assign([seg(0, 10)], [turn(0, 4, "A"), turn(4, 10, "B")],
               contested_ratio=0.5)[0]["mix"])
check("a contested segment always has at least two clusters in its mix",
      len(_row["mix"]) >= 2, _row)
check("an uncontested one has exactly the winner",
      D.assign([seg(0, 10)], [turn(0, 9, "A"), turn(9, 10, "B")],
               contested_ratio=0.7)[0]["mix"] == ["A"])
check("a cluster too small to make the segment contested is left out of the mix",
      "B" not in D.assign([seg(0, 10)], [turn(0, 9, "A"), turn(9, 10, "B")],
                          contested_ratio=0.7)[0]["mix"])
check("an unattributed segment carries an empty mix, not a stale one",
      D.assign([seg(0, 10)], [])[0]["mix"] == [])


# ── the labels readable.py consumes ───────────────────────────────────────────

check.section("the per-segment labels readable.py marks a transcript with")

_segs = [seg(0, 2), seg(2, 4), seg(4, 6)]
_lbl = D.speaker_labels(_segs, [turn(0, 4, "SPEAKER_00"), turn(4, 6, "SPEAKER_01")])
check("there is exactly one label per segment, in order",
      _lbl == ["Speaker 0", "Speaker 0", "Speaker 1"], _lbl)
check("a segment with nothing under it is labelled unattributed, not skipped",
      D.speaker_labels([seg(0, 2)], []) == ["unattributed"])
check("the labels are the same words the standalone document uses",
      D.speaker_labels([seg(0, 10)], [turn(0, 5, "A"), turn(5, 10, "B")])[0]
      == D.label_for("A", True, ["A", "B"]),
      D.speaker_labels([seg(0, 10)], [turn(0, 5, "A"), turn(5, 10, "B")])[0])
check("a contested segment reaches readable.py naming both voices, not neither",
      D.speaker_labels([seg(0, 10)], [turn(0, 5, "SPEAKER_02"),
                                      turn(5, 10, "SPEAKER_24")])[0]
      == "Speakers 2 and 24 (spans a hand-off)")
check("the thresholds reach speaker_labels too",
      D.speaker_labels([seg(0, 10)], [turn(0, 6, "A"), turn(6, 10, "B")],
                       contested_ratio=0.6)[0] == D.label_for("A", True, ["A", "B"]))

check.section("reading a sidecar")


def load_turns_fails(text):
    """True if load_turns rejects `text` as ValueError and nothing else."""
    path = OUTPUT_DIR / "load-turns-test.json"
    if text is None:
        path = OUTPUT_DIR / "load-turns-absent.json"
        path.unlink(missing_ok=True)
    else:
        path.write_text(text)
    try:
        D.load_turns(path)
        return False
    except ValueError:
        return True
    except Exception:
        return False


_unsorted = OUTPUT_DIR / "load-turns-sorted.json"
_unsorted.write_text(json.dumps({"turns": [turn(5, 9, "SPEAKER_01"),
                                           turn(0, 5, "SPEAKER_00")]}))
check("turns come back sorted even when the file lists them out of order",
      [t["speaker"] for t in D.load_turns(_unsorted)]
      == ["SPEAKER_00", "SPEAKER_01"], D.load_turns(_unsorted))

for _broken, _why in [("{not json", "malformed json"),
                      ('{"nope": []}', "no turns key"),
                      ('{"turns": 3}', "a turns value that is not a list"),
                      (None, "no file at all")]:
    check(f"a sidecar with {_why} is rejected as ValueError, not something else",
          load_turns_fails(_broken))


# ── summary ───────────────────────────────────────────────────────────────────

check.section("the counts reported back")

_mixed = [dict(seg(0, 2), speaker="A", share=1.0, contested=False),
          dict(seg(2, 4), speaker="B", share=0.5, contested=True),
          dict(seg(4, 6), speaker=None, share=0.0, contested=False),
          dict(seg(6, 8), speaker="A", share=1.0, contested=False)]
_s = D.summarise(_mixed)
check("attributed, unclear and unattributed account for every segment",
      _s["attributed"] + _s["contested"] + _s["unattributed"] == _s["segments"],
      _s)
check("an unclear segment is not also counted as attributed",
      _s["attributed"] == 2, _s)
check("distinct clusters are counted, not distinct segments",
      _s["clusters"] == 2, _s)
check("percentages are over every segment",
      abs(_s["attributed_pct"] - 50.0) < 1e-9, _s["attributed_pct"])
check("an empty transcript reports zeroes instead of dividing by zero",
      D.summarise([])["attributed_pct"] == 0.0)


# ── rendering ─────────────────────────────────────────────────────────────────

check.section("the document a person reads")

_doc = D.render(_mixed, "meeting", D.summarise(_mixed))
check("the document says the labels are clusters and not names",
      "not names" in _doc)
check("it names the model it came from, so a reader can weigh it",
      D.MODEL in _doc)
check("an unclear turn is shown as unclear in the body",
      "hand-off" in _doc)
check("an unattributed turn is shown as unattributed",
      "unattributed" in _doc)
check("a segment with no text does not produce an empty turn",
      "— \n" not in D.render(
          [dict(seg(0, 2), speaker="A", share=1.0, contested=False),
           dict(seg(2, 4), speaker="B", share=1.0, contested=False, text="  ")],
          "t", D.summarise([])))


# ── the fixture, end to end through the CLI ───────────────────────────────────

check.section("apply, run against the fixture transcript")

_side = OUTPUT_DIR / "fixture.speakers.json"
_segments = FIXTURE.segments
_half = _segments[len(_segments) // 2]["start"]
_side.write_text(json.dumps({
    "model": D.MODEL, "audio": "fixture", "duration": None, "device": "cpu",
    "seconds": 0.0, "speakers": ["SPEAKER_00", "SPEAKER_01"],
    "turns": [turn(0.0, _half, "SPEAKER_00"),
              turn(_half, _segments[-1]["end"] + 1, "SPEAKER_01")],
}))


def cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "diarize.py"), *args],
                          capture_output=True, text=True)


_out = OUTPUT_DIR / "fixture.speakers.md"
if _out.exists():
    _out.unlink()
_r = cli("apply", str(FIXTURE.path), "--speakers", str(_side))
check("apply exits cleanly against the fixture", _r.returncode == 0,
      _r.stderr[-400:])
check("and writes the document beside the transcript", _out.exists())
if _out.exists():
    _body = _out.read_text()
    check("both planted voices appear in the document",
          "Speaker 0" in _body and "Speaker 1" in _body)
    check("the fixture's own words survive into it",
          FIXTURE.before_big in _body)
check("it reports the counts it assigned", "attributed" in _r.stdout, _r.stdout)

_r = cli("apply", str(FIXTURE.path), "--speakers", str(OUTPUT_DIR / "nope.json"))
check("a missing sidecar is refused with a message, not a traceback",
      _r.returncode != 0 and "diarize.py run" in (_r.stdout + _r.stderr),
      _r.stderr[-300:])

check.section("finding the sidecar when it was not named")

check("a plain transcript looks beside itself",
      D.find_sidecar(OUTPUT_DIR / "nothing-here")[1]
      == [OUTPUT_DIR / "nothing-here.speakers.json"])
_tried = D.find_sidecar(OUTPUT_DIR / "meeting.repaired")[1]
check("a repaired transcript also falls back to the recording's own sidecar",
      OUTPUT_DIR / "meeting.speakers.json" in _tried, _tried)
check("and tries its own name first, so an explicit one still wins",
      _tried[0] == OUTPUT_DIR / "meeting.repaired.speakers.json", _tried)
check("nothing is returned when neither candidate exists",
      D.find_sidecar(OUTPUT_DIR / "meeting.repaired")[0] is None)

_recording_side = OUTPUT_DIR / "fixture-recording.speakers.json"
_recording_side.write_text(_side.read_text())
check("the recording's sidecar is found for its repaired transcript",
      D.find_sidecar(OUTPUT_DIR / "fixture-recording.repaired")[0]
      == _recording_side)
_recording_side.unlink()

_bad = OUTPUT_DIR / "fixture.badspeakers.json"
_bad.write_text("{not json")
_r = cli("apply", str(FIXTURE.path), "--speakers", str(_bad))
check("an unreadable sidecar is refused rather than half-applied",
      _r.returncode != 0 and "Can't read" in (_r.stdout + _r.stderr))

check.section("run, refusing bad arguments before it costs anything")

_r = cli("run", str(ROOT / "does-not-exist.m4a"), "--dry-run")
check("a missing recording is refused", _r.returncode != 0)

_r = cli("run", str(FIXTURE.path), "--dry-run", "--num-speakers", "4",
         "--max-speakers", "9")
check("fixing the speaker count and capping it at once is refused",
      _r.returncode != 0 and "cannot be combined" in (_r.stdout + _r.stderr))

_r = cli("run", str(FIXTURE.path), "--dry-run", "--min-speakers", "9",
         "--max-speakers", "4")
check("a minimum above the maximum is refused",
      _r.returncode != 0 and "cannot exceed" in (_r.stdout + _r.stderr))

_r = cli("run", str(FIXTURE.path), "--dry-run")
check("a dry run says what it would do and diarizes nothing",
      _r.returncode == 0 and "Would diarize" in _r.stdout, _r.stdout + _r.stderr)
check("the dry run names the model it would load", D.MODEL in _r.stdout)

_r = cli("run", str(FIXTURE.path), "--dry-run", "-o", "notes")
check("a bare -o stem resolves into output/, not the cwd",
      f"writing: {OUTPUT_DIR / 'notes.speakers.json'}" in _r.stdout, _r.stdout)

_r = cli("run", str(FIXTURE.path), "--dry-run", "-o", "notes.json")
check("an -o already ending .json keeps its extension",
      f"writing: {OUTPUT_DIR / 'notes.json'}" in _r.stdout, _r.stdout)

check.finish()
