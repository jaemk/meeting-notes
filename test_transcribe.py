import os
import tempfile
from pathlib import Path

from testlib import Checks, SAVED_TRANSCRIPT
import transcribe as T

check = Checks()

check.section("backend selection")
check("openai is always honoured", T.resolve_backend("openai") == "openai")
check("auto resolves to a real backend", T.resolve_backend("auto") in ("mlx", "openai"))
check("auto only picks mlx where mlx can run",
      T.resolve_backend("auto") != "mlx" or (T.is_apple_silicon() and T.mlx_installed()))
_real = (T.is_apple_silicon, T.mlx_installed)
try:
    T.is_apple_silicon, T.mlx_installed = (lambda: False), (lambda: False)
    check("auto falls back to openai off Apple Silicon",
          T.resolve_backend("auto") == "openai", T.resolve_backend("auto"))
    check.raises("explicit mlx off Apple Silicon is an error", T.resolve_backend, "mlx")
    T.is_apple_silicon = lambda: True
    check("auto needs mlx installed, not just the right chip",
          T.resolve_backend("auto") == "openai", T.resolve_backend("auto"))
    check.raises("explicit mlx without mlx-whisper is an error", T.resolve_backend, "mlx")
    T.mlx_installed = lambda: True
    check("mlx chosen when chip and package are both there",
          T.resolve_backend("auto") == "mlx" and T.resolve_backend("mlx") == "mlx")
finally:
    T.is_apple_silicon, T.mlx_installed = _real
check("window repair CLI no longer lives here (repair.py owns it)",
      not hasattr(T, "run_windows"))

check.section("parse_time / parse_window")
check("HH:MM:SS", T.parse_time("1:49:54") == 6594.0)
check("MM:SS", T.parse_time("20:47") == 1247.0)
check("SS float", T.parse_time("6594.21") == 6594.21)
check("window HHMMSS", T.parse_window("1:49:54-1:50:21") == (6594.0, 6621.0))
check("window secs", T.parse_window("6594-6621") == (6594.0, 6621.0))
check("window dotdot", T.parse_window("20:47..21:09") == (1247.0, 1269.0))
check.raises("reversed rejected", T.parse_window, "21:09-20:47")
check.raises("garbage rejected", T.parse_window, "garbage")

check.section("load_timestamped round trip on the real file")
segs = T.load_timestamped(SAVED_TRANSCRIPT)
check("2963 segments", len(segs) == 2963, len(segs))
check("first seg", segs[0]["text"].startswith("Guys, this is my last one"))
check("dinghy loop present", segs[2302]["text"] == "It's a dinghy.")

check.section("find_repeats on the real file")
runs = T.find_repeats(segs)
found = {(c, t) for _, c, t in runs}
check("finds 27x dinghy", (27, "It's a dinghy.") in found)
check("finds 22x idk", (22, "I don't know.") in found)
check("finds 4x sure", (4, "Sure.") in found)
check("only 3 runs", len(runs) == 3, [(c, t) for _, c, t in runs])

check.section("snap_window")
snapped = T.snap_window(segs, (6590.0, 6625.0))
check("snaps back to 6579.21", abs(snapped[0] - 6579.21) < 0.01, snapped)
check("snaps fwd to 6627.21", abs(snapped[1] - 6627.21) < 0.01, snapped)
exact = T.snap_window(segs, (6594.21, 6621.21))
check("exact window unchanged", exact == (6594.21, 6621.21), exact)
check("no-touch window unchanged", T.snap_window(segs, (999999, 999999 + 5)) == (999999, 999999 + 5))

check.section("splice")
merged, removed = T.splice(segs, (6594.21, 6621.21), [
    {"start": 6594.21, "end": 6600.0, "text": "NEW A"},
    {"start": 6600.0, "end": 6621.21, "text": "NEW B"},
])
check("removed 27 loop segs", len(removed) == 27, len(removed))
check("all removed were the loop", all(r["text"] == "It's a dinghy." for r in removed))
check("net count", len(merged) == 2963 - 27 + 2, len(merged))
check("neighbour before kept", any(s["text"] == "a dinghy." for s in merged))
check("neighbour after kept", any(s["text"].startswith("Well, and that's the problem") for s in merged))
check("no loop left", not any(s["text"] == "It's a dinghy." for s in merged))
check("new text in", [s["text"] for s in merged if s["text"].startswith("NEW")] == ["NEW A", "NEW B"])
# splice deliberately does NOT globally sort: the source file contains a
# rewound block whose timestamps go backwards, and re-sorting would interleave
# it line-by-line into its neighbour. Only the new material is ordered.
check("replacement inserted in order",
      [s["text"] for s in merged if s["text"].startswith("NEW")] == ["NEW A", "NEW B"])
check("pre-existing out-of-order block left as it was",
      [s["text"] for s in merged] == [s["text"] for s in segs[:2302]]
      + ["NEW A", "NEW B"] + [s["text"] for s in segs[2329:]])

check.section("splice of the rewinding idk loop (overlapping real audio)")
snap_idk = T.snap_window(segs, (1246.86, 1268.86))
m2, rem2 = T.splice(segs, snap_idk, [{"start": snap_idk[0], "end": snap_idk[1], "text": "REAL"}])
check("idk loop removed",
      not any(s["text"] == "I don't know." and 1246 < s["start"] < 1269 for s in m2))
check("duplicated real lines also removed",
      not any(s["text"].startswith("be okay and that might be") for s in m2))
print(f"    (snapped {snap_idk[0]:.2f}-{snap_idk[1]:.2f}, removed {len(rem2)} segs — "
      f"loop + real lines re-covering the same clock time)")

check.section("transcribe_window padding / midpoint trimming (stubbed backend)")
calls = {}
def fake_extract(audio, start, dur, out):
    calls['start'], calls['dur'] = start, dur
    Path(out).write_text("x")
def fake_backend(path, backend, model, lang, cache, cond=True):
    calls['cond'] = cond
    return {"segments": [
        {"start": 5,  "end": 12, "text": "in the pad, drop me"},
        {"start": 13, "end": 20, "text": "straddles start, mid 101"},
        {"start": 20, "end": 30, "text": "solidly inside"},
        {"start": 40, "end": 50, "text": "straddles end, mid 130"},
        {"start": 52, "end": 58, "text": "after, drop me"},
    ]}
T.extract_chunk, T.get_duration, T._run_backend = fake_extract, (lambda p: 3600.0), fake_backend
out = T.transcribe_window("fake.m4a", (100.0, 130.0), "mlx", "large-v2", "en", 15.0)
check("decoded with pad", (calls['start'], calls['dur']) == (85.0, 60.0), (calls['start'], calls['dur']))
check("conditioning off by default", calls['cond'] is False)
check("pad-only segments dropped", all("drop me" not in s["text"] for s in out))
check("clamped to window start", out[0]["start"] == 100.0, out[0])
check("no segment escapes window", all(100.0 <= s["start"] and s["end"] <= 130.0 for s in out))
# regression: a segment straddling the window edge must NOT vanish — the old
# segments covering that time were already spliced out, so dropping it loses speech
check("edge-straddling segment recovered", any("straddles end" in s["text"] for s in out),
      [s['text'] for s in out])
check("kept 3 segments", len(out) == 3, [s['text'] for s in out])
# the only remaining hole is the genuine silence in the stub data (115–125),
# not the window edges the fix is about
check("no hole at window edges", T.holes(out, 100.0, 130.0) == [(115.0, 125.0)],
      T.holes(out, 100.0, 130.0))
check("sorted output", all(out[i]["start"] <= out[i + 1]["start"] for i in range(len(out) - 1)))

check.section("holes / uncovered_span")
segs3 = [{"start": 0, "end": 5, "text": "a"}, {"start": 10, "end": 20, "text": "b"}]
check("finds interior hole", T.holes(segs3, 0, 20) == [(5, 10)], T.holes(segs3, 0, 20))
check("finds trailing hole", T.holes(segs3, 0, 30) == [(5, 10), (20, 30)], T.holes(segs3, 0, 30))
check("finds leading hole", T.holes(segs3, -5, 20) == [(-5, 0), (5, 10)], T.holes(segs3, -5, 20))
check("min_size filters", T.holes(segs3, 0, 20, min_size=10) == [])
check("uncovered_span sums", T.uncovered_span(segs3, 0, 30) == 15, T.uncovered_span(segs3, 0, 30))
check("full coverage = 0", T.uncovered_span([{"start": 0, "end": 30, "text": "x"}], 0, 30) == 0)
check("overlapping segments counted once",
      T.uncovered_span([{"start": 0, "end": 20, "text": "x"}, {"start": 5, "end": 10, "text": "y"}], 0, 20) == 0)

check.section("save_output dotted stem / backup_file")
with tempfile.TemporaryDirectory() as d:
    stem = Path(d) / "saved-transcript.fixed"
    T.save_output({"text": "hi", "segments": [{"start": 0, "end": 1, "text": "hi"}]}, stem, True)
    names = sorted(os.listdir(d))
    check("writes 3 dotted files",
          names == ["saved-transcript.fixed.srt", "saved-transcript.fixed.timestamped.txt",
                    "saved-transcript.fixed.txt"], names)
    src = Path(d) / "t.timestamped.txt"
    src.write_text("original")
    bak = T.backup_file(src)
    check("backup keeps the original bytes", bak.read_text() == "original")
    check("backup is named .bak", bak.name == "t.timestamped.txt.bak", bak.name)
check("output_stem strips .timestamped.txt", str(T.output_stem("a/b.timestamped.txt")) == "a/b")
check("output_stem leaves plain stem", str(T.output_stem("a/b")) == "a/b")

check.section("full-file chunked path still offsets timestamps (stubbed backend)")
chunks = []
def fake_extract2(audio, start, dur, out):
    chunks.append((start, dur)); Path(out).write_text("x")
def fake_backend2(path, backend, model, lang, cache, cond=True):
    return {"text": "chunk text", "segments": [{"start": 0.0, "end": 2.0, "text": "hello"}]}
T.extract_chunk, T._run_backend = fake_extract2, fake_backend2
T.get_duration = lambda p: 600.0
T.find_split_points = lambda p, c, d: [0.0, 300.0, 600.0]
res = T.transcribe("fake.m4a", "mlx", "medium", "en", 5)
check("two chunks decoded", len(chunks) == 2, chunks)
check("segment offsets applied", [s["start"] for s in res["segments"]] == [0.0, 300.0],
      [s["start"] for s in res["segments"]])
check("text joined", res["text"] == "chunk text chunk text", res["text"])
T.get_duration = lambda p: 100.0
res2 = T.transcribe("fake.m4a", "mlx", "medium", "en", 5)
check("short file not split", len(res2["segments"]) == 1, res2["segments"])

check.finish()
