import os
import tempfile
from pathlib import Path

from testlib import Checks, FIXTURE
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

check.section("input comes from local/, output goes to output/")
check("audio is read from local/", T.INPUT_DIR == T.ROOT / "local", T.INPUT_DIR)
check("transcripts are written to output/", T.OUTPUT_DIR == T.ROOT / "output", T.OUTPUT_DIR)
check("the recording's name carries over to its transcript",
      T.default_output("local/2026-07-25.m4a") == T.OUTPUT_DIR / "2026-07-25",
      T.default_output("local/2026-07-25.m4a"))
check("dots in a recording name are not treated as an extension",
      T.default_output(Path("local/team.sync.2026-07-25.m4a")) ==
      T.OUTPUT_DIR / "team.sync.2026-07-25")
check("a bare stem lands in output/", T.resolve_output("beach") == T.OUTPUT_DIR / "beach")
check("an explicit directory is left alone",
      T.resolve_output("elsewhere/beach") == Path("elsewhere/beach"))
check("resolve_output strips a transcript extension",
      T.resolve_output("beach.timestamped.txt") == T.OUTPUT_DIR / "beach")
check("a bare transcript name is found in output/",
      T.resolve_transcript(FIXTURE.path.name) == FIXTURE.path,
      T.resolve_transcript(FIXTURE.path.name))
with tempfile.TemporaryDirectory() as d:
    (Path(d) / "clip.m4a").write_text("x")
    check("a bare filename is looked up in the directory it belongs in",
          T._resolve_in("clip.m4a", Path(d)) == Path(d) / "clip.m4a")
    check("an unknown name comes back as asked, so the error can name it",
          T._resolve_in("nope.m4a", Path(d)) == Path("nope.m4a"))
    check("a path with a directory in it is never redirected",
          T._resolve_in("sub/clip.m4a", Path(d)) == Path("sub/clip.m4a"))

check.section("parse_time / parse_window")
check("HH:MM:SS", T.parse_time("1:49:54") == 6594.0)
check("MM:SS", T.parse_time("20:47") == 1247.0)
check("SS float", T.parse_time("6594.21") == 6594.21)
check("window HHMMSS", T.parse_window("1:49:54-1:50:21") == (6594.0, 6621.0))
check("window secs", T.parse_window("6594-6621") == (6594.0, 6621.0))
check("window dotdot", T.parse_window("20:47..21:09") == (1247.0, 1269.0))
check.raises("reversed rejected", T.parse_window, "21:09-20:47")
check.raises("garbage rejected", T.parse_window, "garbage")

check.section("load_timestamped round trip on the fixture")
segs = T.load_timestamped(FIXTURE.path)
check("239 segments", len(segs) == 239, len(segs))
check("parses back to exactly what was written", segs == FIXTURE.segments)
check("first seg", segs[0]["text"].startswith("Okay, so where did we leave off"))
big = FIXTURE.big_loop
check("planted loop is where it says it is", segs[big.index]["text"] == big.text)

check.section("find_repeats on the fixture")
runs = T.find_repeats(segs)
found = {(c, t) for _, c, t in runs}
check("finds the 27-line loop", (27, "Yeah, absolutely.") in found, found)
check("finds the 22-line loop", (22, "I'm not sure about that.") in found, found)
check("finds the 4-line loop", (4, "Right.") in found, found)
check("only 3 runs", len(runs) == 3, [(c, t) for _, c, t in runs])

check.section("snap_window")
inside = T.snap_window(segs, (big.start + 4.5, big.end - 3.5))
check("widens to whole segments", inside == (big.start + 4.0, big.end - 3.0), inside)
check("exact window unchanged", T.snap_window(segs, (big.start, big.end)) == (big.start, big.end))
over = T.snap_window(segs, (big.start - 1.0, big.end + 1.0))
check("pulls in a neighbour it only clips", over == (big.start - 3.0, big.end + 3.0), over)
check("no-touch window unchanged",
      T.snap_window(segs, (999999, 999999 + 5)) == (999999, 999999 + 5))

check.section("splice")
merged, removed = T.splice(segs, (big.start, big.end), [
    {"start": big.start, "end": big.start + 12.0, "text": "NEW A"},
    {"start": big.start + 12.0, "end": big.end, "text": "NEW B"},
])
check("removed all 27 loop segs", len(removed) == 27, len(removed))
check("all removed were the loop", all(r["text"] == big.text for r in removed))
check("net count", len(merged) == 239 - 27 + 2, len(merged))
check("neighbour before kept", any(s["text"] == FIXTURE.before_big for s in merged))
check("neighbour after kept", any(s["text"] == FIXTURE.after_big for s in merged))
check("no loop left", not any(s["text"] == big.text for s in merged))
check("new text in", [s["text"] for s in merged if s["text"].startswith("NEW")] == ["NEW A", "NEW B"])
# splice deliberately does NOT globally sort: a transcript can contain a
# rewound block whose timestamps go backwards, and re-sorting would interleave
# it line-by-line into its neighbour. Only the new material is ordered.
check("replacement inserted in order",
      [s["text"] for s in merged if s["text"].startswith("NEW")] == ["NEW A", "NEW B"])
check("pre-existing out-of-order block left as it was",
      [s["text"] for s in merged] == [s["text"] for s in segs[:big.index]]
      + ["NEW A", "NEW B"] + [s["text"] for s in segs[big.index + 27:]])

check.section("splice of the rewinding loop (overlaps real speech)")
rw = FIXTURE.rewind_loop
snap_rw = T.snap_window(segs, (rw.start, rw.end))
m2, rem2 = T.splice(segs, snap_rw, [{"start": snap_rw[0], "end": snap_rw[1], "text": "REAL"}])
check("loop removed", not any(s["text"] == rw.text for s in m2))
check("the real lines it buried are removed with it",
      not any(s["text"] in FIXTURE.duplicated for s in m2))
check("removed the loop plus the 4 lines it re-covered", len(rem2) == rw.count + 4, len(rem2))
check("speech outside the rewind survives",
      any(s["text"] == FIXTURE.after_big for s in m2))
print(f"    (snapped {snap_rw[0]:.2f}-{snap_rw[1]:.2f}, removed {len(rem2)} segs — "
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
    stem = Path(d) / "2026-07-25.repaired"
    T.save_output({"text": "hi", "segments": [{"start": 0, "end": 1, "text": "hi"}]}, stem, True)
    names = sorted(os.listdir(d))
    check("writes 3 dotted files",
          names == ["2026-07-25.repaired.srt", "2026-07-25.repaired.timestamped.txt",
                    "2026-07-25.repaired.txt"], names)
    nested = Path(d) / "does" / "not" / "exist" / "beach"
    T.save_output({"text": "hi", "segments": []}, nested, True)
    check("creates the output directory if it is missing",
          (Path(str(nested) + ".txt")).exists())
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
