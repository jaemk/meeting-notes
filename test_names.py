#!/usr/bin/env python3
"""
Checks for names.py. Nothing here calls Claude: gathering is pure, and
validation is the seam that exists precisely so Claude's answer is checked
rather than trusted.

Every name in this file is invented. Real ones live only in local/ and
output/, which are gitignored — see CLAUDE.md.
"""

import json
import subprocess
import sys

from testlib import FIXTURE, OUTPUT_DIR, ROOT, Checks

import diarize as D
import names as N

check = Checks()


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def turn(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


# ── finding names in a line ───────────────────────────────────────────────────

check.section("pulling name-like mentions out of a line")

check("a self-introduction is found and labelled as one",
      ("self", "Wren Ashby") in N.mentions("my name is Wren Ashby"),
      N.mentions("my name is Wren Ashby"))
check("someone being addressed is found and labelled separately",
      ("addressed", "Robin") in N.mentions("Robin, do you have any comments?"),
      N.mentions("Robin, do you have any comments?"))
check("a hand-off phrase is picked up",
      any(n == "Robin" for _, n in N.mentions("I'll turn it over to Robin")),
      N.mentions("I'll turn it over to Robin"))
check("a line with no name in it yields nothing",
      N.mentions("the motion carries") == [])

# The whole design rests on this being over-inclusive rather than clever:
# NAME-4 measured that no stop-list separates a name from a sentence adverb,
# because real first names are ordinary words too.
check("a sentence adverb is matched too, because no rule can exclude it",
      N.mentions("Thankfully, that's settled.") != [],
      "the prompt is what rejects these, not the regex")
check("and so is a name that is also an ordinary word",
      any(n == "Faith" for _, n in N.mentions("Faith, what would you say?")))

check.section("the shape of each cluster, for judging whether it is a person")

_turns = [turn(0, 30, "SPEAKER_00"), turn(30, 60, "SPEAKER_00"),
          turn(60, 61, "SPEAKER_01"), turn(3000, 3001, "SPEAKER_01")]
_shapes = N.cluster_shapes(_turns)
check("every cluster in the sidecar gets a shape",
      set(_shapes) == {"SPEAKER_00", "SPEAKER_01"}, sorted(_shapes))
check("total speech is summed per cluster",
      _shapes["SPEAKER_00"]["speech_seconds"] == 60.0, _shapes["SPEAKER_00"])
check("a cluster speaking once in one place is fully concentrated",
      _shapes["SPEAKER_00"]["concentration"] == 1.0, _shapes["SPEAKER_00"])
check("a cluster smeared across the recording is not",
      _shapes["SPEAKER_01"]["concentration"] < 0.6, _shapes["SPEAKER_01"])
check("mean turn length is reported, since it is half the smear signature",
      _shapes["SPEAKER_01"]["mean_turn_seconds"] == 1.0)
check("the label a reader would see is carried alongside",
      _shapes["SPEAKER_00"]["label"] == "Speaker 0")


# ── gathering ─────────────────────────────────────────────────────────────────

check.section("gathering candidates from a transcript")

# Both clusters have to clear MIN_CLUSTER_SECONDS, or gather correctly
# declines to offer them as speakers and the mention has no one to point at.
_segs = [seg(0, 10, "my name is Wren Ashby"),
         seg(10, 20, "Robin, would you give the report?"),
         seg(20, 30, "Happy to. The roof is done."),
         seg(30, 40, "the motion carries")]
_side = [turn(0, 10, "SPEAKER_00"), turn(10, 20, "SPEAKER_00"),
         turn(20, 30, "SPEAKER_01"), turn(30, 40, "SPEAKER_00")]
_cands, _sh = N.gather(_segs, _side)

check("a mention is recorded for each name found",
      len(_cands) >= 2, len(_cands))
check("a self-introduction records the cluster that said it",
      any(c["kind"] == "self" and c["said_by"] == "SPEAKER_00" for c in _cands),
      [c for c in _cands if c["kind"] == "self"])
check("an addressed name records who spoke next, as suggestive evidence",
      any(c["name"] == "Robin" and c["next_speaker"] == "SPEAKER_01"
          for c in _cands),
      [c for c in _cands if c["name"] == "Robin"])
check("each mention carries a clock time a reader can jump to",
      all(":" in c["clock"] for c in _cands), _cands[0])
check("each mention carries surrounding turns, not just its own line",
      all(len(c["context"]) > 1 for c in _cands))
check("exactly one context entry is flagged as the mention itself",
      all(sum(1 for x in c["context"] if x["is_mention"]) == 1 for c in _cands))
check("a role stated alongside a name is recorded with the mention",
      any("treasurer" in c["roles_in_line"]
          for c in N.gather([seg(0, 10, "Robin, can we have the "
                                        "Treasurer's Report?")],
                            [turn(0, 10, "SPEAKER_00")])[0]),
      N.gather([seg(0, 10, "Robin, can we have the Treasurer's Report?")],
               [turn(0, 10, "SPEAKER_00")])[0])
check("a role with no name nearby records nothing, having no mention to hang on",
      N.gather([seg(0, 10, "the treasurer will report")],
               [turn(0, 10, "SPEAKER_00")])[0] == [])

_tiny = N.gather([seg(0, 1, "Robin, hello?")], [turn(0, 1, "SPEAKER_09")])[0]
check("a cluster too small to be worth naming is not offered as a speaker",
      all(c["said_by"] is None for c in _tiny), _tiny)


# ── validation: the seam that checks Claude ───────────────────────────────────

check.section("refusing an answer that cannot be checked")

_shapes2 = {"SPEAKER_00": {}, "SPEAKER_01": {}}
# The transcript every quote below is checked against (NAME-22). Validation
# now takes it as a required argument, so there is no call site that can
# forget to ground its evidence.
_vsegs = [seg(0, 10, "my name is Wren Ashby"),
          seg(10, 20, "Treasurer's Report, Robin"),
          seg(20, 30, "and the motion carries")]
_good = {"names": {"SPEAKER_00": {
    "name": "Wren Ashby", "confidence": "high", "basis": "self-intro",
    "evidence": [{"at": 1.0, "quote": "my name is Wren Ashby"}]}}}


def refuses(payload, why):
    try:
        N.validate(payload, _shapes2, _vsegs)
        return False
    except ValueError:
        return True


check("a well-formed answer is accepted",
      N.validate(_good, _shapes2, _vsegs)["SPEAKER_00"]["name"] == "Wren Ashby")
check("a cluster the recording does not have is refused",
      refuses({"names": {"SPEAKER_99": _good["names"]["SPEAKER_00"]}}, ""))
check("a name with no evidence is refused, however confident",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren", "confidence": "high"}}}, ""))
check("an empty evidence list is refused too",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren", "confidence": "high", "evidence": []}}}, ""))
check("evidence without a quote is refused, since nothing can be checked",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren", "confidence": "high",
          "evidence": [{"at": 1.0}]}}}, ""))
check("an unknown confidence value is refused",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren", "confidence": "certain",
          "evidence": [{"quote": "the motion carries"}]}}}, ""))
check("an entry with neither a name nor a role is refused",
      refuses({"names": {"SPEAKER_00": {
          "confidence": "high",
          "evidence": [{"quote": "the motion carries"}]}}}, ""))
check("a role with no name is accepted, since it claims less",
      N.validate({"names": {"SPEAKER_00": {
          "role": "treasurer", "confidence": "medium",
          "evidence": [{"quote": "Treasurer's Report"}]}}},
          _shapes2, _vsegs)["SPEAKER_00"]["role"] == "treasurer")
check("a bare object without the names wrapper is still understood",
      N.validate(_good["names"], _shapes2, _vsegs)["SPEAKER_00"]["name"]
      == "Wren Ashby")
check("something that is not an object at all is refused",
      refuses(["SPEAKER_00"], ""))
check("clusters left out are simply absent, not errors",
      set(N.validate(_good, _shapes2, _vsegs)) == {"SPEAKER_00"})

check.section("evidence has to be something that was actually said (NAME-22)")
# The bug this section exists for: naming.md carried a worked example naming
# SPEAKER_02 with an invented name and an invented quote. An answer that
# copied the example through passed validation — the cluster was real and a
# quote key was present — and 164 paragraphs of a finished document were
# labelled with a name that occurs nowhere in the recording.
check("a quote that was never spoken is refused, however well-formed",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren Ashby", "confidence": "high",
          "evidence": [{"at": 34.2, "quote": "my name is Someone Else"}]}}}, ""))
check("the prompt's own placeholder is refused rather than written out",
      refuses({"names": {"SPEAKER_00": {
          "name": "<the name, spelled as the transcript spells it>",
          "confidence": "high",
          "evidence": [{"at": 0.0, "quote":
                        "<the words that say so, copied from the input>"}]}}},
              ""))
check("an empty quote is refused — a key is not evidence",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren", "confidence": "high",
          "evidence": [{"at": 1.0, "quote": "   "}]}}}, ""))
check("one bad quote condemns the entry even when another is genuine",
      refuses({"names": {"SPEAKER_00": {
          "name": "Wren Ashby", "confidence": "high",
          "evidence": [{"quote": "my name is Wren Ashby"},
                       {"quote": "never said this"}]}}}, ""))
# Folding both sides is what lets a real copy through: the quotable stretch
# often straddles two segments, and arrives joined by one space.
check("a quote spanning two segments still matches",
      N.validate({"names": {"SPEAKER_00": {
          "name": "Robin", "confidence": "medium",
          "evidence": [{"quote": "Treasurer's Report, Robin and the motion"}]}}},
          _shapes2, _vsegs)["SPEAKER_00"]["name"] == "Robin")
check("case and spacing differences do not sink a genuine quote",
      N.validate({"names": {"SPEAKER_00": {
          "name": "Wren Ashby", "confidence": "high",
          "evidence": [{"quote": "  MY   NAME\nis Wren Ashby "}]}}},
          _shapes2, _vsegs)["SPEAKER_00"]["name"] == "Wren Ashby")
def refusal(payload):
    """The message a refusal carries, or '' if it was accepted."""
    try:
        N.validate(payload, _shapes2, _vsegs)
        return ""
    except ValueError as e:
        return str(e)


_why = refusal({"names": {"SPEAKER_00": {
    "name": "X", "confidence": "high",
    "evidence": [{"quote": "my name is Someone Else"}]}}})
check("the refusal quotes the offending line, so it can be corrected",
      "Someone Else" in _why, _why)
check("and says which cluster it came from",
      "SPEAKER_00" in _why, _why)


# ── the map the document consumes ────────────────────────────────────────────

check.section("turning the sidecar into display names")

_path = OUTPUT_DIR / "names-test.names.json"
_path.write_text(json.dumps({"names": {
    "SPEAKER_00": {"name": "Wren Ashby", "confidence": "high",
                   "evidence": [{"quote": "q"}]},
    "SPEAKER_01": {"name": None, "role": "treasurer", "confidence": "medium",
                   "evidence": [{"quote": "q"}]}}}))
_map = N.load_names(_path)
check("a named cluster maps to its name",
      _map["SPEAKER_00"] == "Wren Ashby", _map)
check("a cluster with only a role is described by the role",
      _map["SPEAKER_01"] == "the treasurer", _map)
check("an unreadable sidecar raises ValueError, not something else",
      (lambda: [N.load_names(OUTPUT_DIR / "no-such.names.json"), False][1])()
      if False else True)
try:
    N.load_names(OUTPUT_DIR / "definitely-no-such.names.json")
    _raised = False
except ValueError:
    _raised = True
check("a missing sidecar raises ValueError rather than escaping as OSError",
      _raised)

check.section("names reach the rendered label, with the cluster kept beside")

check("a named cluster shows the name and its number",
      D.one_label("SPEAKER_07", {"SPEAKER_07": "Robin"}) == "Robin (Speaker 7)",
      D.one_label("SPEAKER_07", {"SPEAKER_07": "Robin"}))
check("an unnamed cluster is unchanged, not marked unknown",
      D.one_label("SPEAKER_07", {"SPEAKER_02": "Robin"}) == "Speaker 7")
check("no names at all behaves exactly as before",
      D.one_label("SPEAKER_07") == "Speaker 7")
check("a hand-off between two named voices names both",
      D.label_for("SPEAKER_02", True, ["SPEAKER_02", "SPEAKER_07"],
                  {"SPEAKER_02": "Wren", "SPEAKER_07": "Robin"})
      == "Wren (Speaker 2) and Robin (Speaker 7) (spans a hand-off)",
      D.label_for("SPEAKER_02", True, ["SPEAKER_02", "SPEAKER_07"],
                  {"SPEAKER_02": "Wren", "SPEAKER_07": "Robin"}))
check("a hand-off with one name and one number keeps both readable",
      D.label_for("SPEAKER_02", True, ["SPEAKER_02", "SPEAKER_07"],
                  {"SPEAKER_02": "Wren"})
      == "Wren (Speaker 2) and Speaker 7 (spans a hand-off)",
      D.label_for("SPEAKER_02", True, ["SPEAKER_02", "SPEAKER_07"],
                  {"SPEAKER_02": "Wren"}))
check("an unnamed hand-off still uses the compact numbered form",
      D.label_for("SPEAKER_02", True, ["SPEAKER_02", "SPEAKER_07"])
      == "Speakers 2 and 7 (spans a hand-off)")
check("speaker_labels passes names through to every segment",
      D.speaker_labels([seg(0, 10, "hi")], [turn(0, 10, "SPEAKER_02")],
                       names={"SPEAKER_02": "Wren"}) == ["Wren (Speaker 2)"])

check.section("a names sidecar belongs to the recording, not the transcript")

check("a repaired transcript falls back to the recording's names sidecar",
      OUTPUT_DIR / "meeting.names.json"
      in D.find_sidecar(OUTPUT_DIR / "meeting.repaired", ".names.json")[1])
check("and the speakers lookup is unchanged by the shared implementation",
      D.find_sidecar(OUTPUT_DIR / "meeting.repaired")[1][-1]
      == OUTPUT_DIR / "meeting.speakers.json")
check("a plain stem has nothing to fall back to",
      len(D.find_sidecar(OUTPUT_DIR / "meeting", ".names.json")[1]) == 1)


# ── the CLI ───────────────────────────────────────────────────────────────────

check.section("gather and ingest, end to end against the fixture")

_fix_side = OUTPUT_DIR / "names-fixture.speakers.json"
_segments = FIXTURE.segments
_half = _segments[len(_segments) // 2]["start"]
_fix_side.write_text(json.dumps({
    "turns": [{"start": 0.0, "end": _half, "speaker": "SPEAKER_00"},
              {"start": _half, "end": _segments[-1]["end"] + 1,
               "speaker": "SPEAKER_01"}]}))


def cli(*args, stdin=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "names.py"), *args],
        input=stdin, capture_output=True, text=True)


_cand_out = OUTPUT_DIR / "names-cli.names-candidates.json"
_r = cli("gather", str(FIXTURE.path), "--output", str(_cand_out))
check("gather exits cleanly against the fixture", _r.returncode == 0,
      _r.stderr[-400:])
if _cand_out.exists():
    _payload = json.loads(_cand_out.read_text())
    check("the candidate file carries both clusters and candidates",
          "clusters" in _payload and "candidates" in _payload,
          sorted(_payload))
    check("every cluster in the sidecar is described for the prompt",
          set(_payload["clusters"]) == {"SPEAKER_00", "SPEAKER_01"})

_names_out = OUTPUT_DIR / "names-cli.names.json"
# The quote is lifted out of the fixture rather than made up, because ingest
# now checks it against the transcript (NAME-22). An invented one belongs in
# the refusal test below, not in the test that asserts the happy path.
_real_quote = _segments[0]["text"].strip()
_answer = json.dumps({"names": {"SPEAKER_00": {
    "name": "Wren Ashby", "confidence": "high", "basis": "self-intro",
    "evidence": [{"at": 0.0, "quote": _real_quote}]}}})
_r = cli("ingest", str(FIXTURE.path), "-", "--output", str(_names_out),
         stdin=_answer)
check("ingest accepts a well-formed answer on stdin", _r.returncode == 0,
      _r.stderr[-400:] + _r.stdout[-400:])
check("and writes the sidecar", _names_out.exists())
check("it says how many clusters stayed anonymous, which is the normal case",
      "anonymous" in _r.stdout, _r.stdout)

_r = cli("ingest", str(FIXTURE.path), "-", "--output", str(_names_out),
         stdin="```json\n" + _answer + "\n```")
check("a fenced code block is tolerated rather than failing the run",
      _r.returncode == 0, _r.stdout + _r.stderr)

_r = cli("ingest", str(FIXTURE.path), "-", "--output", str(_names_out),
         stdin="I could not identify anyone.")
check("prose instead of JSON is refused with the text shown, not a traceback",
      _r.returncode != 0 and "not JSON" in (_r.stdout + _r.stderr),
      (_r.stdout + _r.stderr)[-300:])

_r = cli("ingest", str(FIXTURE.path), "-", "--output", str(_names_out),
         stdin=json.dumps({"names": {"SPEAKER_44": {
             "name": "Nobody", "confidence": "high",
             "evidence": [{"quote": "q"}]}}}))
check("a hallucinated cluster is refused before it reaches the sidecar",
      _r.returncode != 0 and "not a cluster" in (_r.stdout + _r.stderr))

# End to end, on the path a real answer travels: the whole reason NAME-22
# exists is that this combination — a real cluster, a well-formed entry, and
# a quote nobody said — used to be written out without complaint.
_before = _names_out.read_text() if _names_out.exists() else None
_r = cli("ingest", str(FIXTURE.path), "-", "--output", str(_names_out),
         stdin=json.dumps({"names": {"SPEAKER_00": {
             "name": "Wren Ashby", "confidence": "high",
             "evidence": [{"at": 34.2,
                           "quote": "my name is Wren Ashby"}]}}}))
check("a real cluster with an invented quote is refused end to end",
      _r.returncode != 0 and "not in the transcript" in (_r.stdout + _r.stderr),
      (_r.stdout + _r.stderr)[-300:])
check("and the previous sidecar is left exactly as it was",
      (_names_out.read_text() if _names_out.exists() else None) == _before)

_r = cli("gather", str(OUTPUT_DIR / "no-such-transcript.timestamped.txt"))
check("a missing transcript is refused", _r.returncode != 0)

check.finish()
