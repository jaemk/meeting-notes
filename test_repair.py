import argparse
import contextlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from testlib import (Checks, FIXTURE, AUDIO_MIXED, AUDIO_SILENCE, AUDIO_TONE,
                     build_audio_fixture)
import transcribe as T
import repair as R

check = Checks()

# Captured before anything stubs it, so a section that swaps the decoder out
# can put the real one back rather than handing the next section a stub.
_real_window = T.transcribe_window

segs = T.load_timestamped(FIXTURE.path)
big, rw, short = FIXTURE.big_loop, FIXTURE.rewind_loop, FIXTURE.short_loop

check.section("diagnose (no audio check) on the fixture")
d = R.diagnose(segs, None, check_audio=False)
loops = [x for x in d if x.kind == "loop"]
gaps  = [x for x in d if x.kind == "gap"]
rew   = [x for x in d if x.kind == "rewind"]
check("finds all 3 loops", len(loops) == 3, [x.detail for x in loops])
check("loop windows match what was planted",
      [(l.start, l.end) for l in loops] ==
      [(short.start, short.end), (big.start, big.end), (rw.start, rw.end)],
      [(l.start, l.end) for l in loops])
check("finds 7 gaps", len(gaps) == 7, len(gaps))
check("finds the 1 rewind", len(rew) == 1, len(rew))
check("the rewind is the loop that restarts on the clock",
      abs(rew[0].start - rw.start) < 0.01, rew[0].start)
check("loops+gaps repairable", all(x.repairable for x in loops + gaps))
check("rewind not repairable", not rew[0].repairable)
check("sorted by time", all(d[i].start <= d[i + 1].start for i in range(len(d) - 1)))
check("filler speech produces no defects of its own", len(d) == 11, [str(x) for x in d])

check.section("stutter / canned detection")
synth = [
    {"start": 0, "end": 3, "text": "the budget the budget the budget the budget"},
    {"start": 3, "end": 6, "text": "Thanks for watching!"},
    {"start": 6, "end": 9, "text": "a normal line of speech here"},
    {"start": 9, "end": 12, "text": "Subtitles by the Amara.org community"},
]
ds = R.diagnose(synth, None, check_audio=False)
check("finds stutter", any(x.kind == "stutter" for x in ds), [x.kind for x in ds])
check("short repeated words are NOT stutters (people say 'no no no no')",
      R.find_stutters([{"start": 0, "end": 3, "text": "no no no no no no"}]) == [])
check("nor is ordinary emphasis of a longer short word ('yes yes yes yes')",
      R.find_stutters([{"start": 0, "end": 3, "text": "yes yes yes yes"}]) == [],
      R.find_stutters([{"start": 0, "end": 3, "text": "yes yes yes yes"}]))
below = " ".join(["a" * (R.MIN_STUTTER_WORD - 1)] * 4)
at = " ".join(["a" * R.MIN_STUTTER_WORD] * 4)
check("a lone word one character under the threshold is left to the speaker",
      R.find_stutters([{"start": 0, "end": 3, "text": below}]) == [],
      R.find_stutters([{"start": 0, "end": 3, "text": below}]))
check("a lone word at the threshold, repeated four times, is a stutter",
      [x[1:] for x in R.find_stutters([{"start": 0, "end": 3, "text": at}])]
      == [(4, "a" * R.MIN_STUTTER_WORD)],
      R.find_stutters([{"start": 0, "end": 3, "text": at}]))
check("a short word repeated far past emphasis is still caught, as a pair",
      R.find_stutters([{"start": 0, "end": 3, "text": " ".join(["and"] * 8)}]) != [],
      R.find_stutters([{"start": 0, "end": 3, "text": " ".join(["and"] * 8)}]))
check("finds 2 canned", sum(1 for x in ds if x.kind == "canned") == 2,
      [x.detail for x in ds if x.kind == "canned"])
check("normal line untouched",
      not any(x.kind in ("stutter", "canned") and x.start == 6 for x in ds))
check("the fixture's filler trips neither detector",
      not any(x.kind in ("stutter", "canned") for x in d), [str(x) for x in d])

check.section("merge_windows / defect_windows")
check("coalesces adjacent", R.merge_windows([(0, 10), (12, 20), (100, 110)], 5) == [(0, 20), (100, 110)])
check("leaves distant alone", R.merge_windows([(0, 10), (100, 110)], 5) == [(0, 10), (100, 110)])
check("handles empty", R.merge_windows([]) == [])
check("handles nested", R.merge_windows([(0, 50), (10, 20)], 5) == [(0, 50)])
check("an unsorted list keeps the window that sorts first instead of dropping it",
      R.merge_windows([(100, 110), (0, 10)], 5) == [(0, 10), (100, 110)],
      R.merge_windows([(100, 110), (0, 10)], 5))
check("and unsorted windows that touch still coalesce into one",
      R.merge_windows([(12, 20), (0, 10), (5, 14)], 5) == [(0, 20)],
      R.merge_windows([(12, 20), (0, 10), (5, 14)], 5))
w = R.defect_windows(d, 5)
check("only the 3 repetitions are targeted, not the 7 gaps",
      (sum(1 for x in d if x.repairable), len(w)) == (10, 3), (len(d), len(w)))
check("the targeted windows are exactly the planted loops",
      w == [(short.start, short.end), (big.start, big.end), (rw.start, rw.end)], w)
wg = R.defect_windows(d, 5, R.REPAIRABLE_KINDS)
check("--include-gaps widens it to all 10 repairable defects, 9 windows",
      len(wg) == 9, len(wg))
check("the two gaps 3s apart became one window", (474.0, 495.0) in wg, wg)
check("defect_windows ignores non-repairable kinds",
      R.defect_windows([x for x in d if x.kind == "rewind"], 5,
                       R.REPAIRABLE_KINDS) == [])
check("repetitions are loops, stutters and boilerplate",
      R.REPETITION_KINDS == ("loop", "stutter", "canned"), R.REPETITION_KINDS)
check("gaps are repairable but not a repetition",
      "gap" in R.REPAIRABLE_KINDS and "gap" not in R.REPETITION_KINDS)

check.section("RepairOptions defaults")
opts = R.RepairOptions()
check("defaults to auto backend", opts.backend == "auto", opts.backend)
check("windows are sliced with the same chunk size as a whole file",
      opts.chunk_mins == T.DEFAULT_CHUNK_MINS, opts.chunk_mins)
check("targets repetitions only, so a fix decodes the defects and not the file",
      opts.targets == R.REPETITION_KINDS, opts.targets)
check("large-v2 with a large-v3 fallback",
      (opts.model, opts.fallback_model) == ("large-v2", "large-v3"))
check("two passes by default", opts.passes == 2)
check("overrides apply", R.RepairOptions(model="small", passes=5).model == "small")

check.section("repair with stubbed backend (loop first, then clean)")
opts = R.RepairOptions(backend="mlx", language="en", chunk_mins=1)
attempts = []
def stub_window(audio, window, backend, model, lang, pad, condition_on_prev=False,
                chunk_mins=None):
    attempts.append({"window": window, "model": model, "pad": pad,
                     "cond": condition_on_prev, "chunk": chunk_mins})
    a, b = window
    if len(attempts) == 1:                      # first try still loops
        return [{"start": a + i, "end": a + i + 1, "text": "loop"} for i in range(int(b - a))]
    return [{"start": a, "end": b, "text": "recovered speech"}]
T.transcribe_window = stub_window
one_loop = [x for x in d if x.kind == "loop" and x.start == big.start]
windows = R.defect_windows(one_loop, opts.join_within)
out, report = R.repair("fixture.wav", segs, windows, opts)
check("escalated past the looping attempt", len(attempts) == 2, len(attempts))
check("conditioning off on every attempt", all(a["cond"] is False for a in attempts))
check("the chunk size reaches the decoder on every attempt",
      all(a["chunk"] == 1 for a in attempts), [a["chunk"] for a in attempts])
check("second attempt widened pad", attempts[1]["pad"] == 30.0, attempts[1]["pad"])
check("loop text gone", not any(s["text"] == big.text for s in out))
check("stub text spliced in", any(s["text"] == "recovered speech" for s in out))
in_window = [s for s in out if s["end"] > big.start and s["start"] < big.end]
check("no loop survives in the repaired window", not T.find_repeats(in_window), in_window)
check("untouched loops elsewhere still present (only 1 defect was repaired)",
      len(T.find_repeats(out)) == 2, [c for _, c, _ in T.find_repeats(out)])
check("report marks repaired", report[0][1] == "repaired", report)
check("report marks it spliced", report[0][2] is True, report)
check("neighbours preserved", any(s["text"] == FIXTURE.after_big for s in out))

check.section("dry run decodes nothing and changes nothing")
attempts.clear()
out_dry, report_dry = R.repair("fixture.wav", segs, windows, opts, dry_run=True)
check("no decode attempted", attempts == [], attempts)
check("segments untouched", out_dry is segs)
check("loop still there", any(s["text"] == big.text for s in out_dry))
check("report marks dry-run, not spliced",
      (report_dry[0][1], report_dry[0][2]) == ("dry-run", False), report_dry)

check.section("strict mode refuses a bad window")
attempts.clear()
def always_loops(audio, window, backend, model, lang, pad, condition_on_prev=False,
                 chunk_mins=None):
    attempts.append(1)
    a, b = window
    return [{"start": a + i, "end": a + i + 1, "text": "loop"} for i in range(int(b - a))]
T.transcribe_window = always_loops
strict = R.RepairOptions(backend="mlx", language="en", strict=True)
out2, report2 = R.repair("fixture.wav", segs, windows, strict)
check("exhausted all 3 attempts", len(attempts) == 3, len(attempts))
check("strict skipped the splice", report2[0][1].startswith("skipped"), report2)
check("strict report marks it not spliced", report2[0][2] is False, report2)
check("original left untouched", any(s["text"] == big.text for s in out2))
check("segment count unchanged", len(out2) == len(segs))

check.section("diagnose_repair_verify: repair, then re-check")
# One synthetic loop; the stub returns clean speech, so pass 2 has nothing left.
synth2 = [{"start": float(i), "end": float(i + 1), "text": "stuck line"} for i in range(30)]
synth2 += [{"start": 30.0, "end": 33.0, "text": "and then some real speech follows"}]
decoded = []
def clean_window(audio, window, backend, model, lang, pad, condition_on_prev=False,
                 chunk_mins=None):
    decoded.append(window)
    a, b = window
    return [{"start": a, "end": b, "text": "clean replacement text"}]
T.transcribe_window = clean_window
o = R.RepairOptions(backend="mlx", check_audio=False, passes=3)
fixed, rep, remaining = R.diagnose_repair_verify(None, synth2, o, title="test")
check("the loop was decoded once", len(decoded) == 1, decoded)
check("loop removed", not T.find_repeats(fixed), T.find_repeats(fixed))
check("replacement present", any(s["text"] == "clean replacement text" for s in fixed))
check("real speech after the loop survived",
      any(s["text"].startswith("and then some real") for s in fixed))
check("final re-check found nothing repairable",
      not any(x.repairable for x in remaining), [str(x) for x in remaining])
check("stopped early instead of burning all 3 passes", len(rep) == 1, rep)

check.section("diagnose_repair_verify: honours explicit windows")
decoded.clear()
fixed2, rep2, _ = R.diagnose_repair_verify(None, synth2, o, windows=[(100.0, 110.0)],
                                           title="test")
check("decoded only the window asked for", decoded == [(100.0, 110.0)], decoded)
check("ran one pass, not repeated per pass", len(rep2) == 1, rep2)
check("the untouched loop is still reported as a defect",
      any(x.kind == "loop" for x in R.diagnose(fixed2, None, check_audio=False)))

check.section("diagnose_repair_verify: a still-broken window is re-reported")
T.transcribe_window = always_loops
fixed3, rep3, remaining3 = R.diagnose_repair_verify(
    None, synth2, R.RepairOptions(backend="mlx", check_audio=False, passes=1), title="test")
check("splice happened but stayed defective",
      any(x.kind == "loop" for x in remaining3), [str(x) for x in remaining3])
check("verify does not silently report success", any(x.repairable for x in remaining3))

check.section("a repair targets the repetitions, not the whole transcript")
# The fixture has 3 loops and 7 gaps. A default run should hand the decoder the
# 3 stretches Whisper got wrong and nothing else — the gaps are reported so you
# can see them, but decoding all 10 is the broad re-run this default avoids.
decoded.clear()
T.transcribe_window = clean_window
one_pass = R.RepairOptions(backend="mlx", check_audio=False, passes=1)
_, rep4, rest4 = R.diagnose_repair_verify(None, segs, one_pass, title="test")
check("decoded the 3 loops only", len(decoded) == 3, decoded)
check("and those windows were the planted loops",
      decoded == [(short.start, short.end), (big.start, big.end),
                  (rw.start, rw.end)], decoded)
check("gaps survive untouched and are still reported",
      any(x.kind == "gap" for x in rest4), [str(x) for x in rest4])

decoded.clear()
with_gaps = R.RepairOptions(backend="mlx", check_audio=False, passes=1,
                            targets=R.REPAIRABLE_KINDS)
R.diagnose_repair_verify(None, segs, with_gaps, title="test")
check("--include-gaps opts back in to all 9 windows", len(decoded) == 9, len(decoded))

check.section("diagnose_repair_verify: a filled gap does not manufacture a phantom rewind")
# A gap window overlaps no existing segment, so `splice` cannot derive an
# insertion index from an overlap the way a loop or stutter window can. Before
# the fix it fell back to appending the new material at the end of the list,
# which left the newly filled gap sorting after a segment that starts long
# after it — the next scan read that as a rewind on top of the gap it had just
# filled, so the same window got re-decoded every remaining pass. `main` used to
# sort before writing, so the file on disk looked fine even while this was
# broken; that sort is gone (SEAM-8), which makes this the only thing standing
# between a mis-positioned splice and a scrambled transcript.
gap_synth = [
    {"start": 0.0, "end": 5.0, "text": "some ordinary speech to open things"},
    {"start": 25.0, "end": 30.0, "text": "speech that resumes well after the gap"},
]
gap_decoded = []
def fills_gap(audio, window, backend, model, lang, pad, condition_on_prev=False,
             chunk_mins=None):
    gap_decoded.append(window)
    a, b = window
    return [{"start": a, "end": b, "text": "recovered gap speech"}]
T.transcribe_window = fills_gap
gap_opts = R.RepairOptions(backend="mlx", check_audio=False, targets=R.REPAIRABLE_KINDS)
gap_fixed, gap_report, gap_remaining = R.diagnose_repair_verify(
    None, gap_synth, gap_opts, title="test")
check("the spliced result comes out in time order on its own, with nothing "
      "downstream to re-sort it",
      all(gap_fixed[i]["start"] <= gap_fixed[i + 1]["start"]
          for i in range(len(gap_fixed) - 1)), gap_fixed)
check("filling the gap does not manufacture a phantom rewind there",
      not any(x.kind == "rewind" for x in gap_remaining), [str(x) for x in gap_remaining])
check("the same stretch is not reported as a gap once it has been filled",
      not any(x.kind == "gap" for x in gap_remaining), [str(x) for x in gap_remaining])
check("the window is decoded once, not re-attempted every remaining pass",
      len(gap_decoded) == 1, gap_decoded)
T.transcribe_window = _real_window

check.section("seam overruns are trimmed, never decoded")
# A chunk that kept decoding past its own seam: 'invented' is the tail, and the
# next chunk resumes at 300 with what was actually said there.
_real_silence = T.silence_ends
seam_tx = [
    {"start": 290.0, "end": 296.0, "text": "the sentence that was really there"},
    {"start": 296.0, "end": 303.0, "text": "and this one straddles the seam"},
    {"start": 303.0, "end": 315.0, "text": "invented past the end of the chunk"},
    {"start": 300.0, "end": 306.0, "text": "what the next chunk actually heard"},
    {"start": 306.0, "end": 312.0, "text": "carrying on from there"},
]
seam_opts = R.RepairOptions(backend="mlx", check_audio=True, passes=1)
try:
    T.silence_ends = lambda audio, start=None, dur=None: []
    check("a seam with no silence under it is no chunk boundary, so nothing goes",
          R.trim_seams("fake.m4a", seam_tx, seam_opts) == (seam_tx, []))
    # The hazard this guard exists for: in the fixture the loop rewinds over
    # speech that was transcribed correctly, so there the text *after* the seam
    # is the invention. Trimming it would delete the real lines.
    kept_fix, trims_fix = R.trim_seams("fake.m4a", segs, seam_opts)
    check("the fixture's rewind loop is left alone and the speech it buried survives",
          trims_fix == [] and all(any(s["text"] == d for s in kept_fix)
                                  for d in FIXTURE.duplicated), trims_fix)

    T.silence_ends = lambda audio, start=None, dur=None: [300.0]
    kept, trims = R.trim_seams("fake.m4a", seam_tx, seam_opts)
    check("a seam sitting on a silence boundary is trimmed",
          [s["text"] for s in kept] == [seam_tx[0]["text"], seam_tx[1]["text"],
                                        seam_tx[3]["text"], seam_tx[4]["text"]],
          [s["text"] for s in kept])
    check("the straddling segment is clamped back to the seam",
          (kept[1]["start"], kept[1]["end"]) == (296.0, 300.0), kept[1])
    check("a dry run reports the trim and changes nothing",
          R.trim_seams("fake.m4a", seam_tx, seam_opts, dry_run=True)[0] is seam_tx)
    check("without audio it declines to trim rather than guess",
          R.trim_seams(None, seam_tx, seam_opts) == (seam_tx, []))
    check("--no-audio-check declines for the same reason",
          R.trim_seams("fake.m4a", seam_tx,
                       R.RepairOptions(check_audio=False)) == (seam_tx, []))

    decoded.clear()
    fixed5, rep5, rest5 = R.diagnose_repair_verify("fake.m4a", seam_tx, seam_opts,
                                                   title="test")
    check("the cycle fixed it without decoding anything", decoded == [], decoded)
    check("no rewind survives the run",
          not any(x.kind == "rewind" for x in rest5), [str(x) for x in rest5])
    check("the trim reaches the report, so the caller knows to rewrite the file",
          [(r[1], r[2]) for r in rep5] == [(R.SEAM_TRIMMED, True)], rep5)

    # Ordering is the whole safeguard, and this is the shape that proves it: a
    # repair window covering only part of the overrun, so the rest of the tail
    # survives the splice and the backwards jump with it. Walking back from that
    # jump then reaches past the leftover tail into the freshly decoded text and
    # deletes it — the repair eating its own output. Trimming first is what
    # makes the walk-back safe, because there is no splice for it to reach.
    order = []
    def ordered_silence(audio, start=None, dur=None):
        order.append("trim")
        return [300.0]
    def ordered_window(audio, window, *a, **kw):
        order.append("decode")
        return [{"start": window[0], "end": window[1], "text": "freshly decoded"}]
    T.silence_ends, T.transcribe_window = ordered_silence, ordered_window
    partial_tx = [
        {"start": 290.0, "end": 296.0, "text": "the sentence that was really there"},
        {"start": 296.0, "end": 300.0, "text": "and the one before the seam"},
        {"start": 303.0, "end": 308.0, "text": "invented, and inside the window"},
        {"start": 308.0, "end": 315.0, "text": "invented, and outside it"},
        {"start": 300.0, "end": 303.0, "text": "what the next chunk actually heard"},
    ]
    fixed6, _, rest6 = R.diagnose_repair_verify("fake.m4a", partial_tx, seam_opts,
                                                windows=[(303.0, 308.0)], title="test")
    check("the trim runs before anything is decoded", order[:1] == ["trim"], order)
    check("so a repair spliced into the overrun's stretch survives it",
          "freshly decoded" in [s["text"] for s in fixed6],
          [s["text"] for s in fixed6])
    check("both halves of the tail go, not just the one the window covered",
          not [s for s in fixed6 if s["text"].startswith("invented")],
          [s["text"] for s in fixed6])
    check("and the transcript still comes out in order",
          not any(x.kind == "rewind" for x in rest6), [str(x) for x in rest6])
finally:
    T.silence_ends, T.transcribe_window = _real_silence, _real_window

check.section("gap classification measures the audio underneath")
audio = build_audio_fixture()
if audio is None:
    check.skip("audio-backed gap classification", "ffmpeg unavailable")
else:
    speech, why = R.gap_is_speech(audio, *AUDIO_TONE)
    check("a gap over sound is dropped speech", speech is True, why)
    quiet, why = R.gap_is_speech(audio, *AUDIO_SILENCE)
    check("a gap over silence is left alone", quiet is False, why)
    mixed, why = R.gap_is_speech(audio, *AUDIO_MIXED)
    check("half silence is still speech, not a pause", mixed is True, why)
    lvl = R.audio_level(audio, *AUDIO_TONE)
    check("audio_level reads dB", lvl.mean is not None and -60 < lvl.mean < 0, lvl.mean)
    check("audio_level reports the silence it found", lvl.silence == 0.0, lvl.silence)
    check("audio_level reports duration", abs(lvl.dur - 10) < 0.1, lvl.dur)
    quiet_lvl = R.audio_level(audio, *AUDIO_SILENCE)
    check("silence reads far quieter than tone", quiet_lvl.mean < lvl.mean - 30,
          (quiet_lvl.mean, lvl.mean))
    check("and is reported as silent for its whole length",
          quiet_lvl.silence > 9.0, quiet_lvl.silence)

check.section("a window that comes back empty leaves the original text alone")
# Whisper returning no segments is the ordinary outcome on a quiet or off-mic
# window. Splicing that in replaces real speech with nothing, and every count
# on the console says the repair went fine.
empty_calls = []
def empty_window(audio, window, backend, model, lang, pad, condition_on_prev=False,
                 chunk_mins=None):
    empty_calls.append(window)
    return []
T.transcribe_window = empty_window
before_empty = [s["text"] for s in segs]
out_empty, rep_empty = R.repair("fixture.wav", segs, windows,
                                R.RepairOptions(backend="mlx"))
check("every attempt was spent before giving up", len(empty_calls) == 3, empty_calls)
check("not one segment was dropped",
      [s["text"] for s in out_empty] == before_empty,
      (len(out_empty), len(before_empty)))
check("the loop's own lines are still there to be repaired another way",
      sum(1 for s in out_empty if s["text"] == big.text) == big.count,
      sum(1 for s in out_empty if s["text"] == big.text))
check("the report calls it failed rather than repaired",
      (rep_empty[0][1], rep_empty[0][2]) == ("failed", False), rep_empty)
check("and reports the word count held, not a drop to zero",
      rep_empty[0][3] == rep_empty[0][4] == big.count * len(big.text.split()),
      rep_empty[0][3:])

check.section("the re-decode is judged by the same --min-run the scan used")
def three_alike(audio, window, backend, model, lang, pad, condition_on_prev=False,
                chunk_mins=None):
    a, b = window
    return [{"start": a + i, "end": a + i + 1, "text": "same line"} for i in range(3)]
T.transcribe_window = three_alike
_, lenient = R.attempt_window("fixture.wav", (0.0, 3.0),
                              R.RepairOptions(backend="mlx", min_run=5), {})
check("three identical lines are not a loop when --min-run is 5",
      lenient == [], lenient)
_, strict_run = R.attempt_window("fixture.wav", (0.0, 3.0),
                                 R.RepairOptions(backend="mlx", min_run=3), {})
check("and the same result is a loop at the default threshold of 3",
      strict_run == ["still looping"], strict_run)
check("the default the check now reads is the one RepairOptions carries",
      R.RepairOptions().min_run == 3, R.RepairOptions().min_run)

check.section("overlapping -w windows are decoded once, not twice over")
decoded.clear()
T.transcribe_window = clean_window
R.diagnose_repair_verify(None, synth2, o, windows=[(10.0, 20.0), (15.0, 25.0)],
                         title="test")
check("the two overlapping windows became a single decode", len(decoded) == 1, decoded)
check("and that decode spans both of them",
      decoded[0] == (10.0, 25.0), decoded)
decoded.clear()
R.diagnose_repair_verify(None, synth2, o, windows=[(10.0, 12.0), (60.0, 62.0)],
                         title="test")
check("windows far apart are still decoded separately", len(decoded) == 2, decoded)

check.section("the console tells a partial splice from a clean one")
def splice_lines(decoder):
    """The 'N segments → M segments' line each splice prints."""
    T.transcribe_window = decoder
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        R.repair("fixture.wav", segs, windows, R.RepairOptions(backend="mlx"))
    return [l.strip() for l in buf.getvalue().splitlines() if "words) →" in l]
partial = splice_lines(always_loops)
check("a spliced-but-still-defective window is marked with a warning",
      len(partial) == 1 and partial[0].startswith("⚠"), partial)
check("and the same line says what is still wrong with it",
      len(partial) == 1 and "still looping" in partial[0], partial)
clean = splice_lines(clean_window)
check("a window that came back clean still gets its tick",
      len(clean) == 1 and clean[0].startswith("✓"), clean)
T.transcribe_window = _real_window

check.section("a silence reads as correct behaviour, not as a refusal to fix")
def diagnosis_line(defects, kind):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        R.print_diagnosis(defects, segs)
    return [l for l in buf.getvalue().splitlines() if l.startswith(kind.upper())][0]
sil_line = diagnosis_line([R.Defect("silence", 10.0, 20.0, "silent — ignoring")],
                          "silence")
check("a silence is not filed under reported-but-not-repaired",
      "not repaired" not in sil_line, sil_line)
check("it says the transcript is right to have nothing there",
      "correct behaviour" in sil_line, sil_line)
gap_line = diagnosis_line([R.Defect("gap", 10.0, 20.0, "speech under gap")], "gap")
check("an untargeted gap does still say it was reported and not repaired",
      "reported, not repaired" in gap_line, gap_line)

check.section("--no-audio-check admits everything it switches off")
# The flag gates trim_seams as well as the gap measurement — deliberately, and
# pinned above — so the help has to say so: rewind trimming is the one repair
# that costs nothing, and losing it silently is how you ship a transcript with
# a chunk's invented tail still in it.
flags = argparse.ArgumentParser()
R.add_common(flags)
audio_help = [a.help for a in flags._actions if a.dest == "check_audio"][0]
check("the help mentions the seams it stops confirming",
      "seam" in audio_help, audio_help)
check("and names the rewind trimming that goes with them",
      "rewind" in audio_help, audio_help)
check("the behaviour itself is unchanged: no audio check, no trim",
      R.trim_seams("fake.m4a", seam_tx,
                   R.RepairOptions(check_audio=False)) == (seam_tx, []))

check.section("a window that spliced nothing is not decoded all over again")
# Under --strict a window that never comes back clean is never spliced, so the
# transcript enters the next pass byte-identical, the same diagnosis derives the
# same window, and repair_window restarts its plan at attempt 1 — greedy at
# temperature 0, i.e. the same audio and the same options producing the same
# result. The second pass is a decode whose answer is already on the console.
retried = []
def dirty_window(audio_path, window, backend, model, lang, pad,
                 condition_on_prev=False, chunk_mins=None):
    retried.append(window)
    a, b = window
    return [{"start": a + i, "end": a + i + 1, "text": "stuck line"}
            for i in range(int(b - a))]
T.transcribe_window = dirty_window
strict_three = R.RepairOptions(backend="mlx", check_audio=False, passes=3, strict=True)
_, rep_s, rest_s = R.diagnose_repair_verify(None, synth2, strict_three, title="test")
plan_length = 3
check("the plan is spent once over, not once per pass",
      len(retried) == plan_length, len(retried))
check("and every one of those attempts was on the same window",
      len(set(retried)) == 1, retried)
check("the strict refusal is still on the report from the pass that earned it",
      sum(1 for r in rep_s if r[1].startswith("skipped")) == 1, rep_s)
check("every later pass says it skipped it rather than passing over it in silence",
      sum(1 for r in rep_s if r[1] == R.NOT_RETRIED) == strict_three.passes - 1,
      rep_s)
check("nothing was spliced, so the transcript is the one that went in",
      not any(spliced for _, _, spliced, _, _ in rep_s), rep_s)
check("and the run still calls the defect unresolved",
      any(x.kind == "loop" for x in rest_s), [str(x) for x in rest_s])
summary = io.StringIO()
with contextlib.redirect_stdout(summary):
    R.print_report(rep_s)
check("the decode that was never spent does not count against the clean rate",
      "0/1 windows clean" in summary.getvalue(), summary.getvalue())

retried.clear()
lenient_two = R.RepairOptions(backend="mlx", check_audio=False, passes=2)
_, rep_l, _ = R.diagnose_repair_verify(None, synth2, lenient_two, title="test")
check("without --strict the partial is spliced, so that window's content changed",
      any(spliced for _, _, spliced, _, _ in rep_l), rep_l)
check("and a changed window is decoded again on the next pass",
      len(retried) == 2 * plan_length, len(retried))
check("nothing was skipped as already attempted",
      not any(r[1] == R.NOT_RETRIED for r in rep_l), rep_l)
T.transcribe_window = _real_window

check.section("a transcript that outlasts its own audio is trimmed, not decoded")
# diagnose only ever looks between consecutive segments, so the final chunk has
# nothing after it to reveal an overrun — no next chunk means no backwards jump.
# What it leaves is a transcript running past the end of its own recording, and
# the argument for deleting that is the seam argument exactly.
if audio is None:
    check.skip("a tail past the end of the audio", "ffmpeg unavailable")
else:
    length = T.get_duration(audio)
    def transcript(*spans):
        return [{"start": s, "end": e, "text": t} for s, e, t in spans]
    tail_opts = R.RepairOptions(backend="mlx", check_audio=True, passes=1)
    past = transcript((length - 8.0, length - 2.0, "the last thing anyone said"),
                      (length + 2.0, length + 8.0, "invented after the audio ends"))
    straddle = transcript((length - 8.0, length - 2.0, "the last thing anyone said"),
                          (length - 2.0, length + 8.0, "half heard, half invented"))
    short = transcript((length - 8.0, length - 4.0, "an ordinary line"),
                       (length - 4.0, length - 1.06, "the last thing anyone said"))
    inside = transcript((length - 8.0, length - 4.0, "an ordinary line"),
                        (length - 4.0, length + R.TAIL_TOLERANCE / 2,
                         "ending a shade past the end"))

    d_past = R.diagnose(past, audio)
    check("a segment stamped after the audio ends is a defect no gap scan can see",
          [x.kind for x in d_past].count("tail") == 1, [str(x) for x in d_past])
    check("it is not something a decode could fix, so it is not repairable",
          not any(x.repairable for x in d_past if x.kind == "tail"))
    check("diagnosing reports the overrun and changes nothing",
          past == transcript((length - 8.0, length - 2.0, "the last thing anyone said"),
                             (length + 2.0, length + 8.0,
                              "invented after the audio ends")), past)
    kept_past, trim_past = R.trim_tail(audio, past, tail_opts)
    check("the invented segment is dropped",
          [s["text"] for s in kept_past] == [past[0]["text"]],
          [s["text"] for s in kept_past])
    check("and the trim says what it dropped and where the audio ended",
          trim_past is not None and (trim_past[0], [s["text"] for s in trim_past[1]])
          == (length, [past[1]["text"]]), trim_past)

    kept_str, _ = R.trim_tail(audio, straddle, tail_opts)
    check("a segment straddling the end keeps its words, which exist in no other chunk",
          [s["text"] for s in kept_str] == [s["text"] for s in straddle],
          [s["text"] for s in kept_str])
    check("and is clamped back to where the recording stops",
          kept_str[-1]["end"] == length, kept_str[-1])

    check("a transcript stopping a second short of the end is not an overrun",
          not any(x.kind == "tail" for x in R.diagnose(short, audio)),
          [str(x) for x in R.diagnose(short, audio)])
    check("and nothing of it is trimmed",
          R.trim_tail(audio, short, tail_opts) == (short, None))
    check("an overrun inside the tolerance is Whisper's padding, not its invention",
          not any(x.kind == "tail" for x in R.diagnose(inside, audio)),
          [str(x) for x in R.diagnose(inside, audio)])
    check("and that tolerance is under the second CLAUDE.md calls noise",
          R.TAIL_TOLERANCE <= 1.0, R.TAIL_TOLERANCE)
    over = transcript((length - 8.0, length - 4.0, "an ordinary line"),
                      (length - 4.0, length + R.TAIL_TOLERANCE + 1.0,
                       "running well past the end"))
    check("an overrun past the tolerance is one",
          any(x.kind == "tail" for x in R.diagnose(over, audio)),
          [str(x) for x in R.diagnose(over, audio)])

    check("with no recording to compare against, nothing is claimed either way",
          not any(x.kind == "tail" for x in R.diagnose(past, None)))
    check("--no-audio-check still reports it, the way an unconfirmed rewind is",
          any(x.kind == "tail" for x in R.diagnose(past, audio, check_audio=False)))
    check("but declines to trim it, which is the same conservative default",
          R.trim_tail(audio, past, R.RepairOptions(check_audio=False)) == (past, None))
    check("a dry run says what it would drop and drops nothing",
          R.trim_tail(audio, past, tail_opts, dry_run=True)[0] is past)

    decoded.clear()
    T.transcribe_window = clean_window
    fixed_t, rep_t, rest_t = R.diagnose_repair_verify(audio, past, tail_opts,
                                                      title="test")
    check("the cycle removes the tail without spending a decode on it",
          decoded == [], decoded)
    check("the repaired transcript no longer outlasts its own audio",
          not any(x.kind == "tail" for x in rest_t), [str(x) for x in rest_t])
    check("and the trim reaches the report, so the caller rewrites the file",
          [(r[1], r[2]) for r in rep_t] == [(R.TAIL_TRIMMED, True)], rep_t)
    T.transcribe_window = _real_window

check.section("per-second peaks are read out of one ametadata print")
slices = ("frame:0 pts:0 pts_time:0\n"
          "lavfi.astats.Overall.Peak_level=-3.010300\n"
          "frame:1 pts:16000 pts_time:1\n"
          "lavfi.astats.Overall.Peak_level=-20.100000\n"
          "frame:2 pts:32000 pts_time:2\n"
          "lavfi.astats.Overall.Peak_level=-inf\n")
check("each slice's peak is read, in the order ffmpeg printed them",
      R.parse_peak_levels(slices) == (-3.0103, -20.1), R.parse_peak_levels(slices))
check("a digitally silent slice reports -inf, which is no number to average",
      len(R.parse_peak_levels(slices)) == 2, R.parse_peak_levels(slices))
check("the spread is the loudest second minus the quietest",
      abs(R.Level(-30.0, -3.0, 0.0, 3.0, R.parse_peak_levels(slices)).spread
          - 17.0897) < 1e-4,
      R.Level(-30.0, -3.0, 0.0, 3.0, R.parse_peak_levels(slices)).spread)
check("one second on its own has nothing to spread against",
      R.Level(-30.0, -3.0, 0.0, 1.0, (-3.0,)).spread is None)
check("nor has a span nothing could be measured over",
      R.Level(None, None, 0.0, 5.0).spread is None)
three = "\n".join(f"lavfi.astats.Overall.Peak_level={p}" for p in (-3.0, -10.0, -40.0))
check("a span that divides evenly keeps every slice",
      R.parse_peak_levels(three, dur=3.0) == (-3.0, -10.0, -40.0),
      R.parse_peak_levels(three, dur=3.0))
check("the short remainder at the end of an uneven span is not a comparable second",
      R.parse_peak_levels(three, dur=2.4) == (-3.0, -10.0),
      R.parse_peak_levels(three, dur=2.4))

check.section("a gap row carries the dynamics the triage procedure asks for")
if audio is None:
    check.skip("dynamics on a measured gap", "ffmpeg unavailable")
else:
    R._LEVEL_CACHE.clear()
    spawns = []
    _real_run = R.subprocess.run
    def counting_run(cmd, **kw):
        spawns.append(cmd)
        return _real_run(cmd, **kw)
    try:
        R.subprocess.run = counting_run
        tone_lvl = R.audio_level(audio, *AUDIO_TONE)
        chain = spawns[0][spawns[0].index("-af") + 1]
        check("measuring a stretch is one ffmpeg spawn, not one per second",
              len(spawns) == 1, len(spawns))
        check("that spawn asks for the level summary and the per-second peaks at once",
              "silencedetect" in chain and "astats" in chain, chain)
        check("a second look at the same stretch is answered without spawning again",
              R.audio_level(audio, *AUDIO_TONE) is tone_lvl and len(spawns) == 1,
              len(spawns))
        check("a stretch nobody measured yet is measured for itself",
              R.audio_level(audio, *AUDIO_SILENCE) is not None and len(spawns) == 2,
              len(spawns))
    finally:
        R.subprocess.run = _real_run

    check("a ten-second span comes back a second at a time",
          len(tone_lvl.peaks) == int(AUDIO_TONE[1] - AUDIO_TONE[0]), tone_lvl.peaks)
    check("a tone of constant amplitude reads flat, which is what applause does too",
          tone_lvl.spread is not None and tone_lvl.spread < 1.0, tone_lvl.spread)
    check("digital silence has no peak to report, so no spread is claimed for it",
          R.audio_level(audio, *AUDIO_SILENCE).spread is None,
          R.audio_level(audio, *AUDIO_SILENCE).peaks)
    speech_why = R.gap_is_speech(audio, *AUDIO_TONE)[1]
    check("the gap row shows the spread beside the peak it cannot be read without",
          "spread" in speech_why and "peak" in speech_why, speech_why)
    check("and says nothing of a spread where there was none to measure",
          "spread" not in R.gap_is_speech(audio, *AUDIO_SILENCE)[1],
          R.gap_is_speech(audio, *AUDIO_SILENCE)[1])
    check("the level alone still only says whether there is sound there",
          (R.gap_is_speech(audio, *AUDIO_TONE)[0],
           R.gap_is_speech(audio, *AUDIO_SILENCE)[0],
           R.gap_is_speech(audio, *AUDIO_MIXED)[0]) == (True, False, True))
    # The generated tone is loud and never moves, which is what applause does
    # and what speech does not — so on real ffmpeg output, not just on planted
    # numbers, the gate takes it away from the decode.
    check("a loud stretch that never moves is applause, not a gap worth decoding",
          R.classify_gap(audio, *AUDIO_TONE)[0] == R.AMBIENT,
          R.classify_gap(audio, *AUDIO_TONE))
    check("and silence is still the pause it always was",
          R.classify_gap(audio, *AUDIO_SILENCE)[0] == "silence",
          R.classify_gap(audio, *AUDIO_SILENCE))
    check("neither of those is a defect a decode is spent on",
          not any(R.Defect(k, 0, 10, "").repairable for k in (R.AMBIENT, "silence")))

    # The per-slice filters are the only new thing in that command, and an
    # ffmpeg that rejects one of them would fail the whole measurement — which
    # would report every gap as unmeasured, and an unmeasured gap is reported as
    # speech. Classification must survive losing the reporting extra.
    R._LEVEL_CACHE.clear()
    chains = []
    def picky_run(cmd, **kw):
        chain = cmd[cmd.index("-af") + 1]
        chains.append(chain)
        if "astats" in chain:
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr="Error reinitializing filters!")
        return _real_run(cmd, **kw)
    try:
        R.subprocess.run = picky_run
        fallback = R.audio_level(audio, *AUDIO_TONE)
        # Measured once, memoised, so this classifies the same unsliceable
        # measurement without spawning anything more.
        unsliced = R.classify_gap(audio, *AUDIO_TONE)[0]
    finally:
        R.subprocess.run = _real_run
        R._LEVEL_CACHE.clear()
    check("an ffmpeg that cannot slice is asked again for the level alone",
          len(chains) == 2 and "astats" not in chains[1], chains)
    check("so the classification still has a level to work from",
          fallback.mean is not None and -60 < fallback.mean < 0, fallback)
    check("and simply claims no dynamics rather than inventing them",
          (fallback.peaks, fallback.spread) == ((), None), fallback)
    check("the same tone the gate calls applause is only a gap once nothing "
          "can measure its dynamics",
          unsliced == "gap", unsliced)

check.section("the dynamics gate which gaps a decode is allowed to go to")
# A gap is classified from three measured numbers, so the fixture for the gate
# is the measurement itself: each span below is planted in the level memo under
# exactly the key audio_level computes for it, and nothing is opened, decoded or
# spawned. That buys the two cases generated tone cannot produce — a gap quiet
# enough to be off-mic, and gaps whose spread sits a known distance either side
# of the threshold — without anybody's recording.
GATE_AUDIO = "gate-fixture.wav"
GAP_SECONDS = 10.0
LOUD, QUIET = -20.0, -40.0          # either side of both peak thresholds
FLAT_SPREAD = 6.0                   # under the 9 dB default: applause, not speech
SPEECH_SPREAD = 15.0                # the 10–20 dB swing a talking room makes
MARGIN = 1.0                        # how far a test moves a threshold to flip it

def measured(start, peak, peaks, mean=-20.0, dur=GAP_SECONDS):
    """Plant one measurement and hand back the span it covers."""
    R._LEVEL_CACHE[(GATE_AUDIO, round(start, 2), round(dur, 2))] = R.Level(
        mean, peak, 0.0, dur, peaks)
    return start, start + dur

applause = measured(20.0, LOUD, (LOUD, LOUD - FLAT_SPREAD))
speech = measured(60.0, LOUD, (LOUD, LOUD - SPEECH_SPREAD))
off_mic = measured(100.0, QUIET, (QUIET, QUIET - SPEECH_SPREAD), mean=-45.0)

check("a loud stretch that barely moves is applause or room noise, not speech",
      R.classify_gap(GATE_AUDIO, *applause)[0] == R.AMBIENT,
      R.classify_gap(GATE_AUDIO, *applause))
check("the same level swinging like a conversation stays a gap",
      R.classify_gap(GATE_AUDIO, *speech)[0] == "gap",
      R.classify_gap(GATE_AUDIO, *speech))
check("and one that never rises above the microphone floor is off-mic",
      R.classify_gap(GATE_AUDIO, *off_mic)[0] == R.OFF_MIC,
      R.classify_gap(GATE_AUDIO, *off_mic))
check("the level alone would have called all three of them speech",
      [R.gap_is_speech(GATE_AUDIO, *s)[0] for s in (applause, speech, off_mic)]
      == [True, True, True])
check("neither gated bucket is a kind any decode could address",
      R.AMBIENT not in R.REPAIRABLE_KINDS and R.OFF_MIC not in R.REPAIRABLE_KINDS,
      R.REPAIRABLE_KINDS)

# A transcript whose only findings are those three gaps, so what the gate does
# can be read off the windows a repair would actually decode.
gate_tx = [{"start": 15.0, "end": applause[0], "text": "the line before the clapping"},
           {"start": applause[1], "end": speech[0], "text": "a long stretch of ordinary talk"},
           {"start": speech[1], "end": off_mic[0], "text": "more of the same, unremarkable"},
           {"start": off_mic[1], "end": 115.0, "text": "and the line after the quiet part"}]
gate_d = R.diagnose(gate_tx, GATE_AUDIO)
found = {(x.start, x.end): x.kind for x in gate_d}
check("a diagnosis files each gap under the bucket its dynamics put it in",
      found == {applause: R.AMBIENT, speech: "gap", off_mic: R.OFF_MIC}, found)
wins = R.defect_windows(gate_d, 5.0, R.REPAIRABLE_KINDS)
check("a loud flat gap is not selected as a repair window even with --include-gaps",
      applause not in wins, wins)
check("nor is an off-mic one, which no decode has ever recovered",
      off_mic not in wins, wins)
check("a mid-level gap with speech's own dynamics still is",
      wins == [speech], wins)
check("so opting into gaps now buys the one window worth decoding, not three",
      len(wins) == 1 and len(found) == 3, (wins, found))
def of_kind(defects, kind):
    """
    The first defect of a kind, or a placeholder saying there was none. A
    verdict that came back wrong then fails the check that asserts it, instead
    of ending the suite on an IndexError before the rest of the gate is read.
    """
    return next((x for x in defects if x.kind == kind),
                R.Defect(kind, 0.0, 0.0, "no defect of this kind was found"))

amb_defect = of_kind(gate_d, R.AMBIENT)
mic_defect = of_kind(gate_d, R.OFF_MIC)
check("the applause row carries the spread that put it there, not just a verdict",
      f"spread {FLAT_SPREAD:.1f}dB" in amb_defect.detail
      and f"peak {LOUD:.1f}dB" in amb_defect.detail, amb_defect.detail)
check("and the off-mic row carries the peak that put it there",
      f"peak {QUIET:.1f}dB" in mic_defect.detail, mic_defect.detail)
amb_line = diagnosis_line([amb_defect], R.AMBIENT)
check("applause is reported as correct behaviour, the way a silence is",
      "correct behaviour" in amb_line, amb_line)
check("not as a repair the tool declined to make",
      "not repaired" not in amb_line, amb_line)
mic_line = diagnosis_line([mic_defect], R.OFF_MIC)
check("an off-mic gap says the fix is at record time, not another decode",
      "record time" in mic_line, mic_line)
check("and is not filed under reported-but-not-repaired either",
      "not repaired" not in mic_line, mic_line)

# The thresholds decide real cases, so both directions of each are pinned: the
# same measurement changes bucket when the line moves past it, and only then.
edge = measured(140.0, LOUD,
                (LOUD, LOUD - (R.DEFAULT_GATE.ambient_spread_db - MARGIN)))
mid = measured(180.0, -30.0, (-30.0, -30.0 - SPEECH_SPREAD))
check("a gap a dB inside the flat line is applause on the shipped default",
      R.classify_gap(GATE_AUDIO, *edge)[0] == R.AMBIENT,
      R.classify_gap(GATE_AUDIO, *edge))
check("tightening --ambient-spread-db past it hands the same gap to the decode",
      R.classify_gap(GATE_AUDIO, *edge, R.GapGate(
          ambient_spread_db=R.DEFAULT_GATE.ambient_spread_db - 2 * MARGIN))[0] == "gap")
check("and widening it past a talking gap takes that one away from the decode",
      R.classify_gap(GATE_AUDIO, *speech,
                     R.GapGate(ambient_spread_db=SPEECH_SPREAD + MARGIN))[0]
      == R.AMBIENT)
check("raising --ambient-peak-db above a gap's peak stops it counting as loud",
      R.classify_gap(GATE_AUDIO, *edge,
                     R.GapGate(ambient_peak_db=LOUD + MARGIN))[0] == "gap")
check("lowering --off-mic-peak-db below a quiet gap sends it for a decode anyway",
      R.classify_gap(GATE_AUDIO, *off_mic,
                     R.GapGate(off_mic_peak_db=QUIET - 5 * MARGIN))[0] == "gap")
check("a gap between the two lines is decoded by default",
      R.classify_gap(GATE_AUDIO, *mid)[0] == "gap",
      R.classify_gap(GATE_AUDIO, *mid))
check("and raising --off-mic-peak-db over it rules it off-mic instead",
      R.classify_gap(GATE_AUDIO, *mid,
                     R.GapGate(off_mic_peak_db=-30.0 + MARGIN))[0] == R.OFF_MIC)
loosened = R.GapGate(ambient_spread_db=SPEECH_SPREAD + MARGIN)
check("moving a threshold moves which windows a repair goes to, not just labels",
      R.defect_windows(R.diagnose(gate_tx, GATE_AUDIO, gate=loosened), 5.0,
                       R.REPAIRABLE_KINDS) == [],
      R.defect_windows(R.diagnose(gate_tx, GATE_AUDIO, gate=loosened), 5.0,
                       R.REPAIRABLE_KINDS))

# Without a spread there is no bucket to be in. That has to fall back to the
# level-only decision rather than to a verdict: an ffmpeg that cannot slice
# fails every gap in the run at once, and a peak-only rule would file a whole
# recording as off-mic on the strength of a filter nobody has.
unsliced = measured(220.0, LOUD, ())
one_second = measured(260.0, LOUD, (LOUD,), dur=1.5)
quiet_unsliced = measured(300.0, QUIET, (), mean=-45.0)
check("a gap whose dynamics could not be measured keeps the level-only verdict",
      R.classify_gap(GATE_AUDIO, *unsliced)[0] == "gap",
      R.classify_gap(GATE_AUDIO, *unsliced))
check("a span too short for two whole seconds has nothing to compare, and so "
      "decides nothing",
      R.classify_gap(GATE_AUDIO, *one_second)[0] == "gap",
      R.classify_gap(GATE_AUDIO, *one_second))
check("a quiet unmeasurable gap is not filed off-mic on its peak alone",
      R.classify_gap(GATE_AUDIO, *quiet_unsliced)[0] == "gap",
      R.classify_gap(GATE_AUDIO, *quiet_unsliced))
check("the gate says as much itself: no spread, no bucket",
      R.DEFAULT_GATE.bucket(R.Level(-20.0, LOUD, 0.0, GAP_SECONDS, ())) is None)
check("and nothing measurable at all is not a bucket either",
      R.DEFAULT_GATE.bucket(R.Level(None, None, 0.0, GAP_SECONDS)) is None)
check("a gap over silence is still a silence, gate or no gate",
      R.classify_gap(GATE_AUDIO, *measured(340.0, QUIET, (QUIET, QUIET - 3.0),
                                           mean=-60.0))[0] == "silence")

check.section("the gap thresholds are flags, because the data sits on top of them")
gate_flags = argparse.ArgumentParser()
R.add_common(gate_flags)
check("the shipped gate is the triage CLAUDE.md measured",
      R.DEFAULT_GATE == R.GapGate(-28.0, 9.0, -32.0), R.DEFAULT_GATE)
check("a repair carries it, so the scan and the verify cannot gate differently",
      R.RepairOptions().gate == R.DEFAULT_GATE, R.RepairOptions().gate)
check("parsing no flags at all reproduces exactly that gate",
      R.gate_from_args(gate_flags.parse_args([])) == R.DEFAULT_GATE,
      R.gate_from_args(gate_flags.parse_args([])))
moved = gate_flags.parse_args(["--ambient-peak-db", "-30",
                               "--ambient-spread-db", "12",
                               "--off-mic-peak-db", "-40"])
check("and every one of the three can be moved from the command line",
      R.gate_from_args(moved) == R.GapGate(-30.0, 12.0, -40.0),
      R.gate_from_args(moved))
for _flag in ("ambient_peak_db", "ambient_spread_db", "off_mic_peak_db"):
    _help = [a.help for a in gate_flags._actions if a.dest == _flag][0]
    check(f"--{_flag.replace('_', '-')} states the default it ships with",
          str(getattr(R.DEFAULT_GATE, _flag)) in _help, _help)
    check(f"--{_flag.replace('_', '-')} says which way moving it decides more",
          "aise it" in _help or "ower it" in _help, _help)

check.section("the entry point itself still runs, gate and all")
# `verify` is the whole CLI path — flags parsed, gate built, settings checked,
# transcript scanned, exit status decided — and the one that decodes nothing,
# so the wiring can be exercised for the price of reading a file.
def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    argv_was = sys.argv
    sys.argv = ["repair.py"] + argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            R.main()
        code = None
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = argv_was
    return out.getvalue() + err.getvalue(), code

scanned, scan_code = run_cli(["verify", FIXTURE.path.name])
check("a verify run reaches the diagnosis and reports the planted loops",
      "LOOP" in scanned and scan_code == 1, (scan_code, scanned[-200:]))
refused, refuse_code = run_cli(["verify", FIXTURE.path.name,
                                "--ambient-spread-db", "0"])
check("an impossible gate stops the run before it scans anything",
      "LOOP" not in refused and refuse_code == 1, (refuse_code, refused))
check("and says which flag it is refusing and why",
      "--ambient-spread-db" in refused and "never negative" in refused, refused)

check.section("the write path keeps the order the repair produced")
# The transcript a global sort destroys is the one SEAM-4 exists for: a rewind
# whose seam nothing confirmed. The fixture is exactly that under
# --no-audio-check — its loop restarts 12s back over speech that was
# transcribed correctly — and sorting on the way out interleaves the loop
# line-by-line into the speech underneath it while erasing the backwards jump
# that is the only evidence anything is wrong (VERIFY-3). A `verify` run
# afterwards then reports a clean transcript that has been scrambled.
_real_duration = T.get_duration
order_stem = T.OUTPUT_DIR / "write-order-check"
try:
    T.transcribe_window = lambda *a, **kw: []   # every window comes back empty
    # Stubbed rather than left to ffprobe: the "recording" passed below is the
    # transcript itself, and tail_overrun reads a duration before it consults
    # --no-audio-check. A length past the last segment is the nothing-overran
    # case, which is what this section wants out of the way.
    T.get_duration = lambda path: FIXTURE.segments[-1]["end"] + 60.0
    wrote, wrote_code = run_cli(["repair", str(FIXTURE.path), str(FIXTURE.path),
                                 "--no-audio-check", "-o", order_stem.name])
finally:
    T.transcribe_window = _real_window
    T.get_duration = _real_duration

loaded = T.load_timestamped(FIXTURE.path)
written = T.load_timestamped(Path(str(order_stem) + ".timestamped.txt"))
check("a repair that could splice nothing still writes the transcript out",
      wrote_code is None and len(written) == len(loaded),
      (wrote_code, len(written), len(loaded), wrote[-300:]))
check("and writes it in the order it read it, segment for segment",
      [(s["start"], s["text"]) for s in written]
      == [(s["start"], s["text"]) for s in loaded],
      [s["text"] for s in written[:6]])
check("the one backwards jump the fixture was built with survives being "
      "written, so verify can still count it",
      sum(1 for i in range(1, len(written))
          if written[i]["start"] < written[i - 1]["start"] - 0.01) == 1,
      [(i, written[i]["start"]) for i in range(1, len(written))
       if written[i]["start"] < written[i - 1]["start"] - 0.01])
buried_at = [i for i, s in enumerate(written) if s["text"] in FIXTURE.duplicated]
check("the block the rewind buried comes back as one unbroken run, not shuffled "
      "line-by-line into the loop that covers it",
      len(buried_at) == len(FIXTURE.duplicated)
      and buried_at == list(range(buried_at[0], buried_at[0] + len(buried_at))),
      buried_at)
check("and a re-scan of the written file still calls the rewind a rewind",
      any(x.kind == "rewind" for x in R.diagnose(written, None, check_audio=False)),
      [str(x) for x in R.diagnose(written, None, check_audio=False)])

check.section("--in-place backs up every file it overwrites")
# save_output rewrites .txt, .timestamped.txt and .srt from one stem, so a
# backup of only the transcript named on the command line leaves the other two
# overwritten with nothing to restore them from. What they hold is hours of
# decoding that re-running the repair does not bring back (COST-7).
SAID = "the part of the schedule nobody had signed off on"
BODIES = {
    ".txt": SAID,
    ".timestamped.txt": f"[00:00:00.00 --> 00:00:03.00]  {SAID}\n",
    ".srt": f"1\n00:00:00,000 --> 00:00:03,000\n{SAID}\n\n",
}
with tempfile.TemporaryDirectory() as d:
    stem = Path(d) / "meeting"
    for ext, body in BODIES.items():
        Path(str(stem) + ext).write_text(body, encoding="utf-8")
    made = R.backup_outputs(stem)
    check("all three renderings are copied, not only the one that was handed in",
          sorted(p.name for p in made)
          == sorted("meeting" + ext + ".bak" for ext in BODIES),
          [p.name for p in made])
    check("and each copy holds what its original held",
          all(Path(str(stem) + ext + ".bak").read_text(encoding="utf-8") == body
              for ext, body in BODIES.items()),
          {ext: Path(str(stem) + ext + ".bak").read_text(encoding="utf-8")
           for ext in BODIES})
with tempfile.TemporaryDirectory() as d:
    # A stem written under --no-timestamps, or one whose .srt was deleted: a
    # .bak of a file that is not there would be an empty file claiming to be a
    # recoverable transcript.
    stem = Path(d) / "meeting"
    Path(str(stem) + ".timestamped.txt").write_text(BODIES[".timestamped.txt"],
                                                    encoding="utf-8")
    made = R.backup_outputs(stem)
    check("a sibling that was never written leaves no backup of nothing behind",
          [p.name for p in made] == ["meeting.timestamped.txt.bak"]
          and sorted(p.name for p in Path(d).iterdir())
              == ["meeting.timestamped.txt", "meeting.timestamped.txt.bak"],
          sorted(p.name for p in Path(d).iterdir()))

# The wiring, not just the helper: --in-place has to reach it before save_output
# writes over the originals.
place_stem = T.OUTPUT_DIR / "in-place-backup"
for ext, body in BODIES.items():
    Path(str(place_stem) + ext).write_text(body, encoding="utf-8")
try:
    T.transcribe_window = lambda *a, **kw: []
    T.get_duration = lambda path: 600.0
    placed, placed_code = run_cli(["repair", str(FIXTURE.path),
                                   str(place_stem) + ".timestamped.txt",
                                   "--no-audio-check", "--in-place"])
finally:
    T.transcribe_window = _real_window
    T.get_duration = _real_duration
check("an --in-place run leaves a .bak for each of the three files it rewrote",
      all(Path(str(place_stem) + ext + ".bak").exists() for ext in BODIES),
      [ext for ext in BODIES if not Path(str(place_stem) + ext + ".bak").exists()])
def backed_up(ext):
    # None rather than an exception for a .bak that is not there: a suite that
    # tracebacks stops, and the checks after this one are the ones that say
    # whether the run reported honestly about what it saved.
    p = Path(str(place_stem) + ext + ".bak")
    return p.read_text(encoding="utf-8") if p.exists() else None
check("each of those .bak files still holds what was there before the repair",
      all(backed_up(ext) == body for ext, body in BODIES.items()),
      {ext: backed_up(ext) for ext in BODIES})
check("and the run says what it backed up rather than naming one file",
      all("in-place-backup" + ext + ".bak" in placed for ext in BODIES),
      placed[-400:])
helped, _ = run_cli(["repair", "--help"])

def option_help(text, flag):
    """
    What argparse printed as one flag's help: from its entry in the option list
    to the next entry.

    Anchored on the flag at the start of a line, which is the one place it is
    an entry rather than a mention — the usage line names every flag, and one
    flag's help naming another is exactly what a repo that explains its
    refusals produces. A plain rsplit on the flag would then start the region
    inside a neighbour's help and read the wrong promise back.
    """
    body = text.rsplit("\n  " + flag, 1)[-1]
    cut = body.find("\n  -")
    return body if cut < 0 else body[:cut]

in_place_help = option_help(helped, "--in-place")
check("--in-place promises the backup it actually makes, all three files of it",
      all(ext in in_place_help for ext in BODIES), in_place_help)

check.section("--in-place and --output name different files, so both is refused")
# The two flags say contradictory things: --in-place is "overwrite what I passed
# in", --output is "write somewhere else and leave it alone". Given both, the
# run used to do half of each — the write went to the --output stem while the
# .bak was taken of the source, so three files were copied that nothing was
# about to overwrite and three were overwritten with nothing to restore them
# from. Both halves look right on their own, which is why nothing complained.
def refusal(fn, *a, **kw):
    """What a guard printed on its way out, or "" if it let the call through."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            fn(*a, **kw)
        except SystemExit:
            pass
    return err.getvalue()

both_flags = refusal(R.check_write_target, True, "somewhere-else")
check("asking for both stops the run instead of doing half of each",
      both_flags != "", both_flags)
check("and the refusal names both flags, not just the one it noticed first",
      "--in-place" in both_flags and "--output" in both_flags, both_flags)
check("it says what the pair would have done — backed up files nothing "
      "overwrites, overwritten files nothing was backed up from",
      ".bak" in both_flags and "overwritten" in both_flags, both_flags)
check("--in-place on its own still means overwrite the source",
      R.check_write_target(True, None) is None)
check("and --output on its own still means write a fresh stem",
      R.check_write_target(False, "somewhere-else") is None)
check("neither of them is the ordinary run, and stays one",
      R.check_write_target(False, None) is None)
orphan = refusal(R.check_write_target, False, None, True)
check("--replace-backup on its own is refused too: nothing else writes a .bak",
      "--replace-backup" in orphan and "--in-place" in orphan, orphan)
check("but it is exactly what --in-place is for",
      R.check_write_target(True, None, True) is None)

contradiction = T.OUTPUT_DIR / "contradiction"
# Cleared first, because the thing being asserted is an absence: a stem left
# behind by an earlier run of this suite — or by a run of it against a build
# that still wrote one — would otherwise read as this run having written it.
for _leftover in T.OUTPUT_DIR.glob("contradiction.*"):
    _leftover.unlink()
decoded.clear()
try:
    T.transcribe_window = clean_window
    both_out, both_code = run_cli(["repair", str(FIXTURE.path), str(FIXTURE.path),
                                   "--no-audio-check", "--in-place",
                                   "-o", contradiction.name])
finally:
    T.transcribe_window = _real_window
check("the CLI refuses the pair rather than writing one and backing up the other",
      both_code == 1, (both_code, both_out[-300:]))
check("and refuses before it has read a transcript or spent a decode",
      decoded == [] and "Loaded" not in both_out, (decoded, both_out[-300:]))
check("so nothing lands at the stem it was told to write to",
      not Path(str(contradiction) + ".timestamped.txt").exists())

check.section("a second --in-place repair does not overwrite the first one's .bak")
# T.backup_file writes <file>.bak unconditionally, so two in-place runs in a row
# put run one's *repaired* output where the original decode was. What is lost is
# not an edit but hours of compute nothing short of the audio can produce again
# (COST-8), given up by a command spelled exactly like the one that saved it.
with tempfile.TemporaryDirectory() as d:
    stem = Path(d) / "meeting"
    for ext, body in BODIES.items():
        Path(str(stem) + ext).write_text(body, encoding="utf-8")
    check("a stem nobody has repaired in place has no backup to lose",
          R.existing_backups(stem) == [] and R.check_backup_generation(stem) is None,
          R.existing_backups(stem))
    R.backup_outputs(stem)
    check("after one in-place repair every rendering has a backup standing behind it",
          sorted(p.name for p in R.existing_backups(stem))
          == sorted("meeting" + ext + ".bak" for ext in BODIES),
          [p.name for p in R.existing_backups(stem)])
    second = refusal(R.check_backup_generation, stem)
    check("so the next one is refused rather than allowed to copy over them",
          second != "", second)
    check("the refusal names the backups it is standing in front of",
          all("meeting" + ext + ".bak" in second for ext in BODIES), second)
    check("and offers both ways past it: write elsewhere, or say you meant it",
          "--output" in second and "--replace-backup" in second, second)
    check("--replace-backup is what lets the run through",
          R.check_backup_generation(stem, True) is None)
    Path(str(stem) + ".srt").unlink()
    check("a .bak whose own file is gone is in no danger from this run, so it "
          "does not block one either",
          all(p.name != "meeting.srt.bak" for p in R.existing_backups(stem)),
          [p.name for p in R.existing_backups(stem)])
    check("and the run would not have copied anything over it",
          [src.name for src, _ in R.backup_pairs(stem)]
          == ["meeting.txt", "meeting.timestamped.txt"],
          [src.name for src, _ in R.backup_pairs(stem)])

# The wiring, and the case the guard exists for: two in-place repairs of the
# same stem, the first of which really does change the files.
twice_stem = T.OUTPUT_DIR / "in-place-twice"
LOOPED = ([{"start": float(i), "end": float(i + 1), "text": "stuck line"}
           for i in range(5)]
          + [{"start": 5.0, "end": 8.0,
              "text": "and the meeting carried on from there"}])

def write_looped():
    """Plant a defective transcript, as three renderings, and read them back."""
    with contextlib.redirect_stdout(io.StringIO()):    # save_output's own chatter
        T.save_output({"text": T.rebuild_text(LOOPED), "segments": LOOPED},
                      twice_stem, True)
    return {ext: Path(str(twice_stem) + ext).read_text(encoding="utf-8")
            for ext in BODIES}

def repair_twice_stem(*extra):
    try:
        T.transcribe_window = clean_window
        T.get_duration = lambda path: 600.0
        return run_cli(["repair", str(FIXTURE.path),
                        str(twice_stem) + ".timestamped.txt",
                        "--no-audio-check", "--in-place"] + list(extra))
    finally:
        T.transcribe_window = _real_window
        T.get_duration = _real_duration

def backups_now():
    return {ext: Path(str(twice_stem) + ext + ".bak").read_text(encoding="utf-8")
            if Path(str(twice_stem) + ext + ".bak").exists() else None
            for ext in BODIES}

for _leftover in T.OUTPUT_DIR.glob("in-place-twice.*"):
    _leftover.unlink()          # this stem's .bak is what the run below asserts on
decoded.clear()
decode_original = write_looped()
first_out, first_code = repair_twice_stem()
check("the first in-place repair runs and leaves a .bak of each file it rewrote",
      first_code is None and backups_now() == decode_original,
      (first_code, first_out[-300:]))
check("and it really did change them, so the .bak is the only copy of what "
      "the decode produced",
      Path(str(twice_stem) + ".timestamped.txt").read_text(encoding="utf-8")
      != decode_original[".timestamped.txt"],
      Path(str(twice_stem) + ".timestamped.txt").read_text(encoding="utf-8"))

second_out, second_code = repair_twice_stem()
check("a second in-place repair over the same stem is refused",
      second_code == 1, (second_code, second_out[-300:]))
check("and refused before the transcript is loaded, let alone decoded",
      "Loaded" not in second_out, second_out[-300:])
check("so the pre-repair decode is still in the .bak rather than this run's input",
      backups_now() == decode_original,
      {ext: v[:60] for ext, v in backups_now().items() if v})
check("the refusal says which file stopped it and what it holds",
      "in-place-twice.timestamped.txt.bak" in second_out
      and "decode" in second_out, second_out[-400:])

replaced_out, replaced_code = repair_twice_stem("--replace-backup")
check("--replace-backup lets the same run through",
      replaced_code is None, (replaced_code, replaced_out[-300:]))
check("the older copy really is gone, which is what was asked for",
      backups_now() != decode_original,
      {ext: v[:60] for ext, v in backups_now().items() if v})
check("and the run says so out loud instead of reporting a backup as usual",
      "Replaced the backup" in replaced_out
      and "in-place-twice.timestamped.txt.bak" in replaced_out,
      replaced_out[-400:])

before_dry = backups_now()
dry_out, dry_code = repair_twice_stem("--dry-run")
check("a dry run is not made to argue about a backup it never takes",
      dry_code == 0 and "Dry run" in dry_out, (dry_code, dry_out[-300:]))
check("and having been let through it still writes and backs up nothing",
      backups_now() == before_dry, (before_dry, backups_now()))

replace_help = option_help(helped, "--replace-backup")
check("--replace-backup says what it gives up, not just what it permits",
      "decode" in replace_help and ".bak" in replace_help, replace_help)
check("--in-place says the backup is one generation and points at the override",
      "--replace-backup" in in_place_help, in_place_help)
check("and the two are read apart, so neither promise is being checked against "
      "the other flag's text",
      "Overwrite the source transcript" in in_place_help
      and "Overwrite the source transcript" not in replace_help,
      (in_place_help, replace_help))
check("the backup keeps the .bak name .gitignore and `make clean` both match, "
      "so no generation of it is committable or survives a clean",
      [bak.name for _, bak in R.backup_pairs(place_stem)]
      == ["in-place-backup" + ext + ".bak" for ext in BODIES],
      [bak.name for _, bak in R.backup_pairs(place_stem)])

check.section("a missing file and an impossible threshold stop the run")
check.raises("a transcript that is not there stops instead of tracebacking",
             R.require_file, "no-such-transcript.timestamped.txt",
             T.resolve_transcript, T.OUTPUT_DIR, "transcript")
check.raises("so does audio that is not there, rather than measuring nothing",
             R.require_file, "no-such-recording.m4a", T.resolve_input,
             T.INPUT_DIR, "audio file")
missing = io.StringIO()
with contextlib.redirect_stderr(missing):
    try:
        R.require_file("no-such-transcript.timestamped.txt", T.resolve_transcript,
                       T.OUTPUT_DIR, "transcript")
    except SystemExit:
        pass
check("the message names the file and says where else it looked",
      "no-such-transcript.timestamped.txt" in missing.getvalue()
      and "output/" in missing.getvalue(), missing.getvalue())
check("a bare name that is really in output/ resolves and comes back",
      R.require_file(FIXTURE.path.name, T.resolve_transcript, T.OUTPUT_DIR,
                     "transcript") == FIXTURE.path)
check.raises("--min-run below 2 is refused: a run of one is every segment",
             R.check_settings, 1, 5.0, 2)
check.raises("--min-gap of zero is refused: every segment pair would be a gap",
             R.check_settings, 3, 0.0, 2)
check.raises("--passes below 1 is refused: it repairs nothing and still writes",
             R.check_settings, 3, 5.0, 0)
check.raises("an off-mic line at 0 dBFS is refused: every gap peaks below it, "
             "so none would ever be repairable",
             R.check_settings, 3, 5.0, 2, R.GapGate(off_mic_peak_db=0.0))
check.raises("so is an applause line at 0 dBFS, which empties that bucket "
             "instead of tightening it",
             R.check_settings, 3, 5.0, 2, R.GapGate(ambient_peak_db=0.0))
check.raises("a flat threshold of zero is refused: no spread is ever negative",
             R.check_settings, 3, 5.0, 2, R.GapGate(ambient_spread_db=0.0))
check.raises("and so are buckets that overlap, where a gap is both too loud to "
             "be speech and too quiet to have been heard",
             R.check_settings, 3, 5.0, 2,
             R.GapGate(ambient_peak_db=-40.0, off_mic_peak_db=-30.0))
check("thresholds on the same side of each other are fine",
      R.check_settings(3, 5.0, 2, R.GapGate(-30.0, 12.0, -30.0)) is None)
defaults = R.RepairOptions()
check("the shipped defaults pass their own validation",
      R.check_settings(defaults.min_run, defaults.min_gap, defaults.passes,
                       defaults.gate) is None)

check.finish()
