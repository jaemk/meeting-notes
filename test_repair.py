import sys, os, tempfile
from pathlib import Path
sys.path.insert(0, '/Users/james/dev/meeting-notes')
import transcribe as T
import repair as R

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS {name}")
    else: fail += 1; print(f"  FAIL {name} {extra}")

segs = T.load_timestamped('/Users/james/dev/meeting-notes/saved-transcript.timestamped.txt')

print("— diagnose (no audio check) on the known-bad transcript —")
d = R.diagnose(segs, None, check_audio=False)
loops = [x for x in d if x.kind == "loop"]
gaps  = [x for x in d if x.kind == "gap"]
rew   = [x for x in d if x.kind == "rewind"]
check("finds 3 loops", len(loops) == 3, [x.detail for x in loops])
check("loop windows match", [round(l.start,2) for l in loops] == [1246.86, 5984.60, 6594.21],
      [l.start for l in loops])
check("finds 12 gaps", len(gaps) == 12, len(gaps))
check("finds the 1 rewind", len(rew) == 1, len(rew))
check("loops+gaps repairable", all(x.repairable for x in loops + gaps))
check("rewind not repairable", not rew[0].repairable)
check("sorted by time", all(d[i].start <= d[i+1].start for i in range(len(d)-1)))

print("— stutter / canned detection —")
synth = [
    {"start": 0, "end": 3, "text": "the budget the budget the budget the budget"},
    {"start": 3, "end": 6, "text": "Thanks for watching!"},
    {"start": 6, "end": 9, "text": "a normal line of speech here"},
    {"start": 9, "end": 12, "text": "Subtitles by the Amara.org community"},
]
ds = R.diagnose(synth, None, check_audio=False)
check("finds stutter", any(x.kind == "stutter" for x in ds), [x.kind for x in ds])
check("short repeated words are NOT stutters (people say 'no no no no')",
      R.find_stutters([{"start":0,"end":3,"text":"no no no no no no"}]) == [])
check("finds 2 canned", sum(1 for x in ds if x.kind == "canned") == 2,
      [x.detail for x in ds if x.kind == "canned"])
check("normal line untouched", not any(x.kind in ("stutter","canned") and x.start == 6 for x in ds))

print("— merge_windows —")
check("coalesces adjacent", R.merge_windows([(0,10),(12,20),(100,110)], 5) == [(0,20),(100,110)])
check("leaves distant alone", R.merge_windows([(0,10),(100,110)], 5) == [(0,10),(100,110)])
check("handles empty", R.merge_windows([]) == [])
check("handles nested", R.merge_windows([(0,50),(10,20)], 5) == [(0,50)])
check("real defects collapse 15 -> 13 windows",
      len(R.merge_windows([(x.start,x.end) for x in d if x.repairable], 5)) == 13,
      len(R.merge_windows([(x.start,x.end) for x in d if x.repairable], 5)))

print("— repair with stubbed backend (loop first, then clean) —")
class Args:
    backend, model, fallback_model, language = "mlx", "large-v2", "large-v3", "en"
    pad, join_within, strict = 15.0, 5.0, False
attempts = []
def stub_window(audio, window, backend, model, lang, pad, condition_on_prev=False):
    attempts.append({"window": window, "model": model, "pad": pad, "cond": condition_on_prev})
    a, b = window
    if len(attempts) == 1:                      # first try still loops
        return [{"start": a+i, "end": a+i+1, "text": "loop"} for i in range(int(b-a))]
    return [{"start": a, "end": b, "text": "recovered speech"}]
T.transcribe_window = stub_window
one_loop = [x for x in d if x.kind == "loop"][2:3]
out, report = R.repair("beach.m4a", segs, one_loop, Args())
check("escalated past the looping attempt", len(attempts) == 2, len(attempts))
check("conditioning off on every attempt", all(a["cond"] is False for a in attempts))
check("second attempt widened pad", attempts[1]["pad"] == 30.0, attempts[1]["pad"])
check("loop text gone", not any(s["text"] == "It's a dinghy." for s in out))
check("stub text spliced in", any(s["text"] == "recovered speech" for s in out))
win = one_loop[0]
in_window = [s for s in out if s["end"] > win.start and s["start"] < win.end]
check("no loop survives in the repaired window", not T.find_repeats(in_window), in_window)
check("untouched loops elsewhere still present (only 1 defect was repaired)",
      len(T.find_repeats(out)) == 2, [c for _,c,_ in T.find_repeats(out)])
check("report marks repaired", report[0][1] == "repaired", report)
check("neighbours preserved", any(s["text"].startswith("Well, and that's the problem") for s in out))

print("— strict mode refuses a bad window —")
attempts.clear()
def always_loops(audio, window, backend, model, lang, pad, condition_on_prev=False):
    attempts.append(1)
    a, b = window
    return [{"start": a+i, "end": a+i+1, "text": "loop"} for i in range(int(b-a))]
T.transcribe_window = always_loops
Args.strict = True
out2, report2 = R.repair("beach.m4a", segs, one_loop, Args())
check("exhausted all 3 attempts", len(attempts) == 3, len(attempts))
check("strict skipped the splice", report2[0][1].startswith("skipped"), report2)
check("original left untouched", any(s["text"] == "It's a dinghy." for s in out2))
check("segment count unchanged", len(out2) == len(segs))

print("— gap classification is wired to real audio —")
T.transcribe_window = stub_window
speech, why = R.gap_is_speech('/Users/james/dev/meeting-notes/beach.m4a', 5697.72, 5721.32)
check("known gap classified as speech", speech is True, why)
mean, peak, sil, dur = R.audio_level('/Users/james/dev/meeting-notes/beach.m4a', 0, 20)
check("audio_level reads dB", mean is not None and -60 < mean < 0, mean)
check("audio_level reports duration", abs(dur - 20) < 0.1, dur)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
