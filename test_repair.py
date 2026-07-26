from testlib import (Checks, FIXTURE, AUDIO_MIXED, AUDIO_SILENCE, AUDIO_TONE,
                     build_audio_fixture)
import transcribe as T
import repair as R

check = Checks()

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
w = R.defect_windows(d, 5)
check("10 repairable defects collapse to 9 windows",
      (sum(1 for x in d if x.repairable), len(w)) == (10, 9), (len(d), len(w)))
check("the two gaps 3s apart became one window", (474.0, 495.0) in w, w)
check("defect_windows ignores non-repairable kinds",
      R.defect_windows([x for x in d if x.kind == "rewind"], 5) == [])

check.section("RepairOptions defaults")
opts = R.RepairOptions()
check("defaults to auto backend", opts.backend == "auto", opts.backend)
check("large-v2 with a large-v3 fallback",
      (opts.model, opts.fallback_model) == ("large-v2", "large-v3"))
check("two passes by default", opts.passes == 2)
check("overrides apply", R.RepairOptions(model="small", passes=5).model == "small")

check.section("repair with stubbed backend (loop first, then clean)")
opts = R.RepairOptions(backend="mlx", language="en")
attempts = []
def stub_window(audio, window, backend, model, lang, pad, condition_on_prev=False):
    attempts.append({"window": window, "model": model, "pad": pad, "cond": condition_on_prev})
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
def always_loops(audio, window, backend, model, lang, pad, condition_on_prev=False):
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
def clean_window(audio, window, backend, model, lang, pad, condition_on_prev=False):
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
    mean, peak, sil, dur = R.audio_level(audio, *AUDIO_TONE)
    check("audio_level reads dB", mean is not None and -60 < mean < 0, mean)
    check("audio_level reports the silence it found", sil == 0.0, sil)
    check("audio_level reports duration", abs(dur - 10) < 0.1, dur)
    mean_q, _, sil_q, _ = R.audio_level(audio, *AUDIO_SILENCE)
    check("silence reads far quieter than tone", mean_q < mean - 30, (mean_q, mean))
    check("and is reported as silent for its whole length", sil_q > 9.0, sil_q)

check.finish()
