import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import testlib
from testlib import (ROOT, Checks, FIXTURE, AUDIO_SILENCE, AUDIO_TONE,
                     build_audio_fixture)
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
check("a bare stem lands in output/", T.resolve_output("audio") == T.OUTPUT_DIR / "audio")
with contextlib.redirect_stderr(io.StringIO()):   # it warns; that is its own section
    check("an explicit directory is left alone",
          T.resolve_output("elsewhere/audio") == Path("elsewhere/audio"))
check("resolve_output strips a transcript extension",
      T.resolve_output("audio.timestamped.txt") == T.OUTPUT_DIR / "audio")
# The other half of FILES-11. transcribe.py --output and repair.py -o name a
# stem that save_output appends three extensions to; readable.py, diarize.py and
# names.py --output name the finished file. Stripping the extension off the
# second kind renames the file, so the two have separate resolvers rather than
# one with a mode flag, and both are checked here so neither can drift onto the
# other's rule.
check("a bare output filename lands in output/ too",
      T.resolve_output_file("notes.readable.md") == T.OUTPUT_DIR / "notes.readable.md",
      T.resolve_output_file("notes.readable.md"))
check("a file named .txt keeps its .txt, where a stem would have lost it",
      T.resolve_output_file("notes.txt") == T.OUTPUT_DIR / "notes.txt"
      and T.resolve_output("notes.txt") == T.OUTPUT_DIR / "notes",
      (T.resolve_output_file("notes.txt"), T.resolve_output("notes.txt")))
check("and so does a file named .srt or .timestamped.txt, the other two the "
      "stem resolver exists to strip",
      (T.resolve_output_file("notes.srt"),
       T.resolve_output_file("notes.timestamped.txt"))
      == (T.OUTPUT_DIR / "notes.srt", T.OUTPUT_DIR / "notes.timestamped.txt"))
check("a name with no extension at all is left with none",
      T.resolve_output_file("notes") == T.OUTPUT_DIR / "notes")
with contextlib.redirect_stderr(io.StringIO()):   # it warns; that is its own section
    check("an explicit directory is honoured for a file name as well",
          T.resolve_output_file("elsewhere/notes.readable.md")
          == Path("elsewhere/notes.readable.md"))
    check("dots inside a name are not an extension to a file resolver either",
          T.resolve_output_file("team.sync.2026-07-25.readable.md")
          == T.OUTPUT_DIR / "team.sync.2026-07-25.readable.md")
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

check.section("measuring real audio (everything else here stubs ffmpeg)")
# The silence-detection and duration helpers are the only part of this module
# that talks to a real recording, and repair's seam check trusts what they say:
# if the times came back relative to the seek instead of on the file's own
# clock, no seam would ever be confirmed, rewinds would silently stop being
# trimmed, and every stubbed test in all three suites would still pass.
audio = build_audio_fixture()
if audio is None:
    check.skip("silence, duration and extraction measured against real audio",
               "ffmpeg is not installed")
else:
    tone_secs = AUDIO_TONE[1] - AUDIO_TONE[0]
    quiet_start, quiet_end = AUDIO_SILENCE
    full_secs = quiet_end + tone_secs          # tone, silence, tone

    ends = T.silence_ends(audio)
    check("the one silence in the fixture is found, and only that one",
          len(ends) == 1, ends)
    check("it ends where the fixture stops being quiet",
          ends and abs(ends[0] - quiet_end) < 0.05, ends)

    scan_from = quiet_start + tone_secs / 2    # starts inside the silence
    shifted = T.silence_ends(audio, scan_from, tone_secs)
    check("scanning a stretch reports file time, not time since the seek — "
          "repair reads these as chunk boundaries before it deletes anything",
          shifted and abs(shifted[0] - quiet_end) < 0.05, (scan_from, shifted))
    check("and the shift is forward onto the file's clock, never back off it",
          all(s >= scan_from for s in shifted), (scan_from, shifted))

    check("the file's duration is what was generated",
          abs(T.get_duration(audio) - full_secs) < 0.05, T.get_duration(audio))

    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "copy.wav"
        shutil.copy(audio, copy)
        first = T.get_duration(copy)
        copy.unlink()
        try:
            again = T.get_duration(copy)
        except Exception as e:
            again = f"re-probed and failed: {e}"
        check("a duration is probed once and remembered — the window path asks "
              "for it on every decode attempt of every slice",
              again == first, again)

        dashed = Path(d) / "-clip.wav"
        shutil.copy(audio, dashed)
        cwd = os.getcwd()
        try:
            os.chdir(d)
            got = T.get_duration("-clip.wav")
        except Exception as e:
            got = f"ffprobe rejected it: {e}"
        finally:
            os.chdir(cwd)
        check("a filename beginning with '-' is a filename, not an ffprobe option",
              isinstance(got, float) and abs(got - full_secs) < 0.05, got)

        # Where the chunk is cut out of matters more than how fast: the input
        # seek this asserts is also the one that decides which audio arrives.
        clip_start = quiet_start + tone_secs / 2
        clip = Path(d) / "clip.wav"
        T.extract_chunk(audio, clip_start, tone_secs, clip)
        check("an extracted chunk is as long as it was asked to be",
              abs(T.get_duration(clip) - tone_secs) < 0.1, T.get_duration(clip))
        clip_ends = T.silence_ends(clip)
        check("and it holds the stretch that was asked for — the fixture's "
              "silence ends at the same moment, measured from the chunk's start",
              clip_ends and abs(clip_ends[0] - (quiet_end - clip_start)) < 0.1,
              (clip_start, clip_ends))

    # The speed of it is a property of where -ss sits in the command line.
    class _Recorder:
        cmd = None
        def run(self, cmd, **kw):
            self.cmd = cmd
            return SimpleNamespace(returncode=0, stdout="", stderr="")
    rec, real_subprocess = _Recorder(), T.subprocess
    try:
        T.subprocess = rec
        T.extract_chunk("in.m4a", 3600.0, 30.0, "out.wav")
    finally:
        T.subprocess = real_subprocess
    check("the seek happens before the input, so ffmpeg jumps to the chunk "
          "instead of decoding an hour of audio and discarding it",
          rec.cmd.index("-ss") < rec.cmd.index("-i")
          and rec.cmd.index("-t") < rec.cmd.index("-i"), rec.cmd)

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
check("a short window is one decode", len(T.window_slices("fake.m4a", 100.0, 130.0, 60)) == 2)

check.section("chunk_boundaries: cut at silence, hard-cut when there is none")
check("snaps each cut to the nearest silence",
      T.chunk_boundaries(0, 300, 60, [58, 121, 179], 30) == [0, 58, 121, 179, 239, 300],
      T.chunk_boundaries(0, 300, 60, [58, 121, 179], 30))
check("ignores silence outside the tolerance",
      150 not in T.chunk_boundaries(0, 200, 60, [150], 30),
      T.chunk_boundaries(0, 200, 60, [150], 30))
check("never cuts backwards", all(
    b > a for a, b in zip(*(lambda s: (s[:-1], s[1:]))(
        T.chunk_boundaries(0, 300, 60, [10, 20, 250], 90)))))
check("a window barely over one chunk stays whole",
      T.chunk_boundaries(0, 65, 60, [], 30) == [0, 65])
check("tolerance is half a chunk", T.chunk_tolerance(60) == 30, T.chunk_tolerance(60))
check("and is capped for long chunks", T.chunk_tolerance(300) == 90, T.chunk_tolerance(300))
# regression: the tolerance used to be a flat 90s, so with -c 1 a lone silence
# at 2:20 would win the 1:00 cut and hand Whisper a 140s chunk — the long
# decode -c was set to prevent. A hard cut at the target beats that.
check("a distant silence no longer stretches a chunk past the tolerance",
      T.chunk_boundaries(0, 300, 60, [140]) == [0, 60, 140, 200, 260, 300],
      T.chunk_boundaries(0, 300, 60, [140]))
check("whole-file and window paths agree on the default tolerance",
      T.chunk_boundaries(0, 300, 60, [140]) ==
      T.chunk_boundaries(0, 300, 60, [140], T.chunk_tolerance(60)))

check.section("a long repair window is sliced like a whole file (stubbed backend)")
extracts, decoded = [], []
def fake_extract3(audio, start, dur, out):
    extracts.append((start, dur)); Path(out).write_text("x")
def fake_backend3(path, backend, model, lang, cache, cond=True):
    # A 2s segment at the centre of whatever span was just extracted, so each
    # slice contributes exactly one segment with its midpoint inside itself.
    dur = extracts[-1][1]
    decoded.append(len(decoded) + 1)
    return {"segments": [{"start": dur / 2 - 1, "end": dur / 2 + 1,
                          "text": f"slice {len(decoded)}"}]}
T.extract_chunk, T._run_backend = fake_extract3, fake_backend3
T.get_duration = lambda p: 3600.0
T.silence_ends = lambda p, start=None, dur=None: [58.0, 121.0]
sliced = T.transcribe_window("fake.m4a", (0.0, 180.0), "mlx", "large-v2", "en",
                             15.0, chunk_mins=1)
check("180s window became 3 decodes, not 1", len(extracts) == 3, extracts)
check("cuts landed on the silences",
      T.window_slices("fake.m4a", 0.0, 180.0, 60) == [0.0, 58.0, 121.0, 180.0],
      T.window_slices("fake.m4a", 0.0, 180.0, 60))
points = T.window_slices("fake.m4a", 0.0, 180.0, 60)
check("no slice runs much past a minute",
      all(b - a <= 60 + 30 for a, b in zip(points, points[1:])),
      [b - a for a, b in zip(points, points[1:])])
# A seam is a hard cut, so no slice can transcribe its neighbour's speech and
# have both copies spliced in. Only the window's outer edges get context.
check("internal seams are cut hard, with no padding across them",
      extracts[1] == (58.0, 121.0 - 58.0), extracts[1])
check("the last slice is padded on its outer edge only",
      extracts[2] == (121.0, (180.0 - 121.0) + 15.0), extracts[2])
check("the first slice's leading pad is clipped at the start of the file",
      extracts[0] == (0.0, 58.0), extracts[0])
check("slices tile the window without overlapping",
      all(a + d <= extracts[i + 1][0] + 0.001
          for i, (a, d) in enumerate(extracts[:-1])), extracts)
check("each slice contributed a segment",
      sorted(s["text"] for s in sliced) == ["slice 1", "slice 2", "slice 3"],
      [s["text"] for s in sliced])
check("sliced output stays inside the window",
      all(0.0 <= s["start"] and s["end"] <= 180.0 for s in sliced), sliced)
check("sliced output is sorted",
      all(sliced[i]["start"] <= sliced[i + 1]["start"] for i in range(len(sliced) - 1)))
extracts.clear()
T.transcribe_window("fake.m4a", (0.0, 40.0), "mlx", "large-v2", "en", 15.0, chunk_mins=1)
check("a window inside one chunk is still a single decode", len(extracts) == 1, extracts)

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
    nested = Path(d) / "does" / "not" / "exist" / "audio"
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
check("text is rebuilt from the segments that survived the merge",
      res["text"] == "hello hello", res["text"])
T.get_duration = lambda p: 100.0
res2 = T.transcribe("fake.m4a", "mlx", "medium", "en", 5)
check("short file not split", len(res2["segments"]) == 1, res2["segments"])

check.section("a chunk overrunning its seam cannot reorder the transcript")
# Whisper does not stop where its audio does. A chunk ending mid-loop keeps
# emitting the same line with timestamps running past the end; merged as-is
# they sort after the next chunk's opening and time appears to run backwards.
calls = []
def looping_backend(path, backend, model, lang, cache, cond=True):
    calls.append(path)
    if len(calls) == 1:                     # chunk [0, 300), still looping at 300
        return {"text": "ignored", "segments": [
            {"start": 280.0, "end": 295.0, "text": "real speech"},
            {"start": 295.0, "end": 302.0, "text": "straddles the seam"},
            {"start": 302.0, "end": 327.0, "text": "loop tail"},
        ]}
    return {"text": "ignored",
            "segments": [{"start": 0.0, "end": 5.0, "text": "next chunk opening"}]}
T._run_backend = looping_backend
T.get_duration = lambda p: 600.0
res3 = T.transcribe("fake.m4a", "mlx", "medium", "en", 5)
texts = [s["text"] for s in res3["segments"]]
starts = [s["start"] for s in res3["segments"]]
check("the tail decoded past the chunk end is dropped", "loop tail" not in texts, texts)
check("so the merged timestamps never go backwards", starts == sorted(starts), starts)
check("a segment straddling the seam is clamped, not dropped — with no padding "
      "between chunks its opening words exist nowhere else",
      [(s["start"], s["end"]) for s in res3["segments"]
       if s["text"] == "straddles the seam"] == [(295.0, 300.0)], res3["segments"])
check("the .txt loses the hallucinated tail too",
      res3["text"] == "real speech straddles the seam next chunk opening", res3["text"])

check.section("clamp_to_chunk")
raw = [{"start": 10.0, "end": 20.0, "text": "inside"},
       {"start": 55.0, "end": 70.0, "text": "straddles"},
       {"start": 60.0, "end": 90.0, "text": "starts past the end"},
       {"start": 61.0, "end": 61.0, "text": "empty and past the end"}]
kept = T.clamp_to_chunk(raw, 0.0, 60.0)
check("segments starting at or after the chunk end are dropped",
      [s["text"] for s in kept] == ["inside", "straddles"], [s["text"] for s in kept])
check("a straddler keeps its text and ends at the seam",
      (kept[1]["start"], kept[1]["end"]) == (55.0, 60.0), kept[1])
check("a segment wholly inside is untouched", kept[0] == raw[0], kept[0])
check("the input is copied, not mutated", raw[1]["end"] == 70.0, raw[1])
check("clamping is a no-op when nothing overruns",
      T.clamp_to_chunk(raw[:1], 0.0, 60.0) == raw[:1])

check.section("trimming a seam overrun back out of a transcript already written")
merged = [
    {"start": 280.0, "end": 295.0, "text": "real speech"},
    {"start": 295.0, "end": 302.0, "text": "straddles the seam"},
    {"start": 302.0, "end": 327.0, "text": "loop tail"},
    {"start": 300.0, "end": 305.0, "text": "next chunk opening"},
    {"start": 305.0, "end": 310.0, "text": "and on it goes"},
]
check("the overrun is located and the seam with it",
      T.seam_overruns(merged) == [(2, 3, 300.0)], T.seam_overruns(merged))
out, trims = T.trim_seam_overruns(merged)
check("what the chunk decoded past its seam is dropped",
      [s["text"] for s in out] == ["real speech", "straddles the seam",
                                   "next chunk opening", "and on it goes"],
      [s["text"] for s in out])
check("the straddler keeps its words and ends at the seam",
      (out[1]["start"], out[1]["end"]) == (295.0, 300.0), out[1])
check("so time runs forwards afterwards", T.seam_overruns(out) == [], T.seam_overruns(out))
check("the trim names exactly what it removed", trims == [(300.0, [merged[2]])], trims)
check("the transcript passed in is not mutated",
      len(merged) == 5 and merged[1]["end"] == 302.0, merged[1])
check("a rejected seam is left alone — confirm() has the last word",
      T.trim_seam_overruns(merged, lambda seam: False) == (merged, []))
# The tail is audio the chunk never had, so how much the next chunk found to say
# for that stretch is beside the point — a quiet minute after the seam does not
# make an invented tail worth keeping.
orphan = merged[:3] + [{"start": 300.0, "end": 301.0, "text": "only a second of it"}]
check("a sparse next chunk does not save the tail",
      T.trim_seam_overruns(orphan)[1] == [(300.0, [merged[2]])],
      T.trim_seam_overruns(orphan)[1])

check.section("splicing a window that overlaps nothing (a gap)")
# A gap window has, by definition, no segment to take the place of. Deriving the
# insertion point from the first overlapping segment therefore found none and
# appended the replacement after everything — including everything later in the
# file — so the next diagnose scan read the backwards jump as a rewind and spent
# a decode on a window that was never wrong.
base = [{"start": 0.0, "end": 5.0, "text": "before the gap"},
        {"start": 100.0, "end": 105.0, "text": "after the gap"}]
filled, removed4 = T.splice(base, (50.0, 60.0),
                            [{"start": 52.0, "end": 55.0, "text": "GAP FILL"}])
check("nothing is removed, because nothing overlapped",
      removed4 == [], removed4)
check("the new lines land between their neighbours in time, not at the end",
      [s["text"] for s in filled] == ["before the gap", "GAP FILL", "after the gap"],
      [s["text"] for s in filled])
check("so the spliced transcript is still non-decreasing in start — the "
      "property whose violation manufactures a phantom rewind",
      [s["start"] for s in filled] == sorted(s["start"] for s in filled),
      [s["start"] for s in filled])
lead, _ = T.splice(base, (-20.0, -10.0),
                   [{"start": -15.0, "end": -12.0, "text": "EARLIEST"}])
check("a window before everything is inserted first",
      [s["text"] for s in lead][0] == "EARLIEST", [s["text"] for s in lead])
tail4, _ = T.splice(base, (200.0, 210.0),
                    [{"start": 202.0, "end": 205.0, "text": "LATEST"}])
check("a window after everything still goes last",
      [s["text"] for s in tail4][-1] == "LATEST", [s["text"] for s in tail4])
check("an empty replacement for a window that hit nothing changes nothing",
      T.splice(base, (50.0, 60.0), []) == (base, []))
# The insertion index used to be counted twice over: the first overlapping
# index, then a count of the non-hits before it. They are the same number,
# because every segment before the first hit is a keeper — and the overlapping
# case must still land exactly there.
mid = base + [{"start": 200.0, "end": 205.0, "text": "later still"}]
over4, rem4b = T.splice(mid, (99.0, 106.0),
                        [{"start": 100.0, "end": 105.0, "text": "REDONE"}])
check("an overlapping window replaces its segments in place, where the old "
      "ones were",
      [s["text"] for s in over4] == ["before the gap", "REDONE", "later still"],
      [s["text"] for s in over4])
check("and reports exactly what it took out",
      [s["text"] for s in rem4b] == ["after the gap"], rem4b)
first_only, _ = T.splice(mid, (0.0, 6.0),
                         [{"start": 1.0, "end": 2.0, "text": "OPENING"}])
check("a window over the very first segment keeps the replacement first",
      [s["text"] for s in first_only][0] == "OPENING",
      [s["text"] for s in first_only])

check.section("a silence at the end of the file is not a chunk boundary")
# silencedetect emits a silence_end at EOF whenever a recording fades out, and
# snapping a cut to it appends the end twice: a final chunk of no audio at all,
# extracted as a header-only WAV and handed to Whisper to transcribe nothing.
fade = T.chunk_boundaries(0, 290, 60, [209.0, 290.0])
check("no chunk is shorter than the smallest amount of audio worth decoding",
      all(b - a >= T.MIN_CHUNK_SECS for a, b in zip(fade, fade[1:])),
      [round(b - a, 3) for a, b in zip(fade, fade[1:])])
check("the file is still covered end to end",
      (fade[0], fade[-1]) == (0, 290), fade)
check("a silence that is not at the end is still used as a cut",
      209.0 in fade, fade)
near = T.chunk_boundaries(0, 290, 60, [209.0, 289.9])
check("nor is one a hair short of the end",
      all(b - a >= T.MIN_CHUNK_SECS for a, b in zip(near, near[1:])),
      [round(b - a, 3) for a, b in zip(near, near[1:])])
# The window path splits on the same silences, so it has the same exposure:
# a silence a cut can reach, and another at the window's own end.
T.silence_ends = lambda p, start=None, dur=None: [start + 209.0, start + dur]
faded = T.window_slices("fake.m4a", 0.0, 290.0, 60)
check("a repair window that fades out at its end is sliced the same way",
      all(b - a >= T.MIN_CHUNK_SECS for a, b in zip(faded, faded[1:])),
      [round(b - a, 3) for a, b in zip(faded, faded[1:])])
check("and still covers the whole window",
      (faded[0], faded[-1]) == (0.0, 290.0), faded)
check.raises("a chunk size of zero is refused rather than looping forever "
             "building boundaries until memory runs out",
             T.chunk_boundaries, 0, 300, 0, [])
check.raises("and so is a negative one", T.chunk_boundaries, 0, 300, -5, [])

check.section("one loaded model per process, not one per decode")
# whisper.load_model reads a multi-hundred-MB checkpoint. The window path used
# to hand the backend a fresh {} on every call, so a repair reloaded the model
# for every slice of every attempt of every window.
T._OPENAI_CACHE.clear()
loads = []
def counting_backend(path, backend, model, lang, cache, cond=True):
    if model not in cache:
        cache[model] = object()          # what whisper.load_model costs, in effigy
        loads.append(model)
    return {"segments": [{"start": 0.0, "end": 2.0, "text": "decoded"}]}
T.extract_chunk = lambda a, s, d, o: Path(o).write_text("x")
T._run_backend = counting_backend
T.get_duration = lambda p: 3600.0
for span in ((0.0, 30.0), (30.0, 60.0)):
    T._decode_span("fake.m4a", span, 3600.0, "openai", "medium", "en",
                   0.0, 0.0, False)
check("a second slice reuses the model the first one loaded",
      loads == ["medium"], loads)
check("because the cache it is handed is the module's, not a new dict",
      "medium" in T._OPENAI_CACHE, list(T._OPENAI_CACHE))
T.get_duration = lambda p: 600.0
T.find_split_points = lambda p, c, d: [0.0, 300.0, 600.0]
T.transcribe("fake.m4a", "openai", "medium", "en", 5)
check("and the whole-file path shares it, so the repair pass that follows a "
      "transcription loads nothing again", loads == ["medium"], loads)
check("a different model is still loaded when one is asked for",
      (T._decode_span("fake.m4a", (0.0, 5.0), 600.0, "openai", "tiny", "en",
                      0.0, 0.0, False) is not None
       and loads == ["medium", "tiny"]), loads)

check.section("timestamps are truncated, never rounded into the next minute")
check("a fraction under the minute stays inside it",
      T.fmt_time(59.999) == "00:00:59.99", T.fmt_time(59.999))
check("and under the hour too",
      T.fmt_time(3599.996) == "00:59:59.99", T.fmt_time(3599.996))
edges = [0.0, 0.29, 12.29, 59.999, 60.0, 119.9999, 3599.996, 3600.0, 3661.5]
check("no stamp ever shows a sixtieth second",
      all(int(T.fmt_time(t).split(":")[2].split(".")[0]) < 60 for t in edges),
      [T.fmt_time(t) for t in edges])
check("the fmt_srt_time it shares a file with already truncated",
      (T.fmt_srt_time(59.999), T.fmt_srt_time(3599.996))
      == ("00:00:59,999", "00:59:59,996"),
      (T.fmt_srt_time(59.999), T.fmt_srt_time(3599.996)))
check("the two formats agree on which second it is",
      all(T.fmt_time(t)[:8] == T.fmt_srt_time(t)[:8] for t in edges),
      [(T.fmt_time(t), T.fmt_srt_time(t)) for t in edges])
check("a hundredth is not truncated away by binary float noise",
      [T.fmt_time(t) for t in (0.29, 12.29, 3661.5)]
      == ["00:00:00.29", "00:00:12.29", "01:01:01.50"],
      [T.fmt_time(t) for t in (0.29, 12.29, 3661.5)])
check("every stamp reads back as a time within a hundredth of the real one",
      all(abs(sum(f * v for f, v in zip((3600, 60, 1),
                                        (int(p[0]), int(p[1]), float(p[2]))))
              - t) <= 0.01
          for t in edges for p in [T.fmt_time(t).split(":")]),
      [T.fmt_time(t) for t in edges])

check.section("the CLI flags that were inert or unstated")
P = T.build_parser()
plain = P.parse_args(["audio.m4a"])
check("timestamped output is still on by default", plain.timestamps is True)
check("--no-timestamps is the off switch the help text implied existed",
      P.parse_args(["audio.m4a", "--no-timestamps"]).timestamps is False)
check("-t still asks for them", P.parse_args(["audio.m4a", "-t"]).timestamps is True)
check("the model a stubborn window is retried with is named on the CLI",
      plain.fallback_model == T.DEFAULT_FALLBACK_MODEL, plain.fallback_model)
check("and can be pinned to a small one",
      P.parse_args(["audio.m4a", "--fallback-model", "tiny"]).fallback_model == "tiny")
# A stand-in for the repair module, so which flag lands on which option is
# checkable without it. Its gate reader just echoes the three thresholds back:
# assembling them is repair.py's job, and that it is really repair.py doing it
# is asserted against the real module further down.
fake_repair = SimpleNamespace(REPETITION_KINDS=("loop", "stutter", "canned"),
                              REPAIRABLE_KINDS=("loop", "stutter", "canned", "gap"),
                              gate_from_args=lambda a: (a.ambient_peak_db,
                                                        a.ambient_spread_db,
                                                        a.off_mic_peak_db))
draft = T.repair_kwargs(P.parse_args(["audio.m4a", "--model", "tiny",
                                      "--fallback-model", "tiny"]),
                        "openai", fake_repair)
check("a draft run's fallback model reaches the repair options, so --model "
      "tiny cannot quietly fetch a multi-gigabyte checkpoint instead",
      draft["fallback_model"] == "tiny", draft)
check("the repair model defaults to the model the transcription used",
      draft["model"] == "tiny", draft)
check("--repair-model overrides just that",
      T.repair_kwargs(P.parse_args(["audio.m4a", "--model", "tiny",
                                    "--repair-model", "small"]),
                      "openai", fake_repair)["model"] == "small")
check("gaps are not re-decoded unless they are asked for",
      draft["targets"] == fake_repair.REPETITION_KINDS, draft["targets"])
check("--include-gaps widens what earns a decode",
      T.repair_kwargs(P.parse_args(["audio.m4a", "--include-gaps"]),
                      "openai", fake_repair)["targets"]
      == fake_repair.REPAIRABLE_KINDS)
check("repair slices its windows with the chunk size this run was given",
      T.repair_kwargs(P.parse_args(["audio.m4a", "-c", "3"]),
                      "openai", fake_repair)["chunk_mins"] == 3)
check.raises("--chunk-size 0 is refused at the CLI rather than hanging the "
             "chunker", P.parse_args, ["audio.m4a", "-c", "0"])
check.raises("so is a negative chunk size", P.parse_args, ["audio.m4a", "-c", "-5"])
check.raises("so is one that is not a number", P.parse_args, ["audio.m4a", "-c", "x"])
check("a sane chunk size still parses",
      P.parse_args(["audio.m4a", "-c", "1"]).chunk_size == 1)
try:
    import repair as _repair
    from dataclasses import fields as _fields
    names = {f.name for f in _fields(_repair.RepairOptions)}
    unknown = set(T.repair_kwargs(plain, "openai", _repair)) - names
    check("every option this CLI builds is one repair actually accepts",
          unknown == set(), unknown)
except Exception as e:
    check.skip("every option this CLI builds is one repair actually accepts",
               f"repair.py not importable here: {e}")

check.section("the gap dynamics gate is tunable from the transcription path")
# Every number below is read off repair.DEFAULT_GATE rather than written out
# here: the property under test is that the two sides cannot be retuned
# separately, and a literal -28.0 in this file would be a third copy to drift.
# Guarded the same way as the cross-check above — with no repair.py there is
# nothing to compare against.
try:
    import repair as _repair
    from dataclasses import fields as _fields
except Exception as e:
    _repair = None
    check.skip("the three gap thresholds are repair.py's own",
               f"repair.py not importable here: {e}")
if _repair is not None:
    G = _repair.DEFAULT_GATE
    check("all three thresholds are askable for here, and default to exactly "
          "the numbers repair.py gates on — so neither side can be retuned "
          "without the other",
          (plain.ambient_peak_db, plain.ambient_spread_db, plain.off_mic_peak_db)
          == (G.ambient_peak_db, G.ambient_spread_db, G.off_mic_peak_db),
          (plain.ambient_peak_db, plain.ambient_spread_db,
           plain.off_mic_peak_db, G))
    ours = T.FlagRecorder()
    T.add_gate_flags(ours, _repair)
    theirs = T.FlagRecorder()
    _repair.add_common(theirs)
    check("and each is registered with repair.py's own type, metavar and help "
          "text, so --help here promises what the repair pass will actually do",
          {a[0]: kw for a, kw in ours.calls}
          == {a[0]: kw for a, kw in theirs.calls if a[0] in T.GATE_FLAGS},
          [a[0] for a, _ in ours.calls])
    check.raises("a repair.py that renamed a threshold fails loudly rather "
                 "than leaving a flag the help text still advertises",
                 T.add_gate_flags, T.FlagRecorder(),
                 SimpleNamespace(add_common=lambda p: p.add_argument(
                     "--min-run", type=int, default=3)),
                 expect=RuntimeError)

    moved = P.parse_args(["audio.m4a",
                          "--ambient-peak-db", str(G.ambient_peak_db + 3),
                          "--ambient-spread-db", str(G.ambient_spread_db + 2),
                          "--off-mic-peak-db", str(G.off_mic_peak_db - 4)])
    tuned = _repair.RepairOptions(**T.repair_kwargs(moved, "openai", _repair))
    check("a moved applause threshold reaches the options the automatic pass "
          "runs with", tuned.gate.ambient_peak_db == G.ambient_peak_db + 3,
          tuned.gate)
    check("so does a moved spread threshold",
          tuned.gate.ambient_spread_db == G.ambient_spread_db + 2, tuned.gate)
    check("so does a moved off-mic threshold",
          tuned.gate.off_mic_peak_db == G.off_mic_peak_db - 4, tuned.gate)
    check("and they arrive as the gate repair classifies gaps with, not a "
          "loose triple", isinstance(tuned.gate, _repair.GapGate),
          type(tuned.gate).__name__)
    # The point of the flags, end to end: the same measured stretch is bucketed
    # differently because the transcription run said so. Loud and flat, just
    # above the default applause line.
    loud_flat = SimpleNamespace(peak=G.ambient_peak_db + 1,
                                spread=G.ambient_spread_db - 1)
    check("moving the line moves the verdict: a stretch the default gate calls "
          "applause is repairable under the raised one this run asked for",
          G.bucket(loud_flat) == _repair.AMBIENT
          and tuned.gate.bucket(loud_flat) == "gap",
          (G.bucket(loud_flat), tuned.gate.bucket(loud_flat)))

    base = _repair.RepairOptions(**T.repair_kwargs(plain, "openai", _repair))
    check("a run naming none of them gates on exactly what it gated on before "
          "the flags existed", base.gate == _repair.RepairOptions().gate
          and base.gate == _repair.DEFAULT_GATE, base.gate)
    differing = {f.name for f in _fields(_repair.RepairOptions)
                 if getattr(base, f.name)
                 != getattr(_repair.RepairOptions(), f.name)}
    check("so the gate is not among what such a run overrides at all",
          "gate" not in differing, differing)

    # Refused before a multi-hour transcription, not after: the run below names
    # a recording that does not exist, so if the gate check were anywhere later
    # the file error would be what came back instead.
    def _cli(*flags):
        return subprocess.run(
            [sys.executable, str(ROOT / "transcribe.py"),
             "no-such-recording.m4a", *flags],
            capture_output=True, text=True)
    crossed = _cli("--ambient-peak-db", str(G.off_mic_peak_db - 1))
    check("an applause threshold below the off-mic one — two buckets a gap "
          "would fall into at once — is refused",
          crossed.returncode == 1 and "--ambient-peak-db" in crossed.stderr,
          (crossed.returncode, crossed.stderr[-300:]))
    check("and refused before the recording is so much as looked for, let "
          "alone decoded",
          "not found" not in (crossed.stdout + crossed.stderr)
          and "Audio:" not in crossed.stdout,
          (crossed.stdout[-300:], crossed.stderr[-300:]))
    flat = _cli("--ambient-spread-db", "0")
    check("a spread of zero, which empties the applause bucket while looking "
          "like it narrowed it, is refused too",
          flat.returncode == 1 and "--ambient-spread-db" in flat.stderr,
          (flat.returncode, flat.stderr[-300:]))
    fine = _cli("--ambient-spread-db", str(G.ambient_spread_db + 1))
    check("while a coherent retune is waved through to the recording it was "
          "given, so the refusals above are about the gate and nothing else",
          "not found" in fine.stderr, (fine.returncode, fine.stderr[-300:]))

check.section("a transcript written outside output/ says so")
def resolved(stem):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        return T.resolve_output(stem), err.getvalue()
inside = str(ROOT / "transcripts" / "meeting")
path25, warned = resolved(inside)
check("a repo path outside output/ is still honoured — the warning does not "
      "refuse it", str(path25) == inside, path25)
check("but it is called out, because output/ is the only gitignored place a "
      "transcript can land in", "Warning" in warned and "gitignore" in warned,
      warned)
check("the ordinary case is silent", resolved("meeting") == (T.OUTPUT_DIR / "meeting", ""),
      resolved("meeting"))
check("naming output/ explicitly is silent too",
      resolved(str(T.OUTPUT_DIR / "meeting"))[1] == "",
      resolved(str(T.OUTPUT_DIR / "meeting")))
check("so is a subdirectory of output/",
      resolved(str(T.OUTPUT_DIR / "old" / "meeting"))[1] == "")
with tempfile.TemporaryDirectory() as d:
    check("somewhere else entirely on the disk is the author's own business",
          resolved(str(Path(d) / "meeting"))[1] == "",
          resolved(str(Path(d) / "meeting")))
with contextlib.redirect_stderr(io.StringIO()):
    check("the check says which it did, so it can be reasoned about",
          T.warn_if_committable(ROOT / "notes" / "x") is True
          and T.warn_if_committable(T.OUTPUT_DIR / "x") is False)

# The file resolver runs the same guard, because the documents the later stages
# write are as committable as a transcript is — a .readable.md carries the whole
# meeting in it.
def resolved_file(name):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        return T.resolve_output_file(name), err.getvalue()
doc_inside = str(ROOT / "documents" / "meeting.readable.md")
doc_path, doc_warned = resolved_file(doc_inside)
check("a document written into the repo but outside output/ is honoured and "
      "called out, exactly as a transcript stem is",
      str(doc_path) == doc_inside and "Warning" in doc_warned
      and "gitignore" in doc_warned, (doc_path, doc_warned))
check("a bare document name is silent, because it lands in output/",
      resolved_file("meeting.readable.md")
      == (T.OUTPUT_DIR / "meeting.readable.md", ""),
      resolved_file("meeting.readable.md"))
check("naming output/ explicitly is silent for a file too",
      resolved_file(str(T.OUTPUT_DIR / "meeting.readable.md"))[1] == "",
      resolved_file(str(T.OUTPUT_DIR / "meeting.readable.md")))
with tempfile.TemporaryDirectory() as d:
    check("and somewhere else entirely on the disk is the author's own business "
          "for a document as much as for a stem",
          resolved_file(str(Path(d) / "meeting.readable.md"))[1] == "",
          resolved_file(str(Path(d) / "meeting.readable.md")))

check.section("resolve_output_file's edges: empty, '..', trailing slash, and ~")
# An empty --output has one part (Path("") is Path(".")) and is not absolute,
# so before this it fell to the bare-name branch: OUTPUT_DIR / "" is OUTPUT_DIR
# itself, a directory path handed back where a file was asked for — the same
# failure need_output's Makefile guard exists to catch before a stem ever
# reaches save_output.
check.raises("an empty --output is refused rather than silently resolving to "
             "output/ itself",
             T.resolve_output_file, "", expect=ValueError)
check.raises("a bare '..' is refused too — with no directory component to "
             "route it through the warn_if_committable check every other "
             "escape from output/ goes through, OUTPUT_DIR / '..' would "
             "silently walk back out to OUTPUT_DIR's parent",
             T.resolve_output_file, "..", expect=ValueError)
check.raises("a trailing slash on a bare name is refused — 'notes/' names a "
             "directory, not the file this resolves to",
             T.resolve_output_file, "notes/", expect=ValueError)
check.raises("and so does 'output/' itself — the exact output/.summary.md "
             "trap the Makefile's need_output guard already refuses a stem "
             "for, one level lower",
             T.resolve_output_file, "output/", expect=ValueError)
with contextlib.redirect_stderr(io.StringIO()):
    check("'../escape.md' does have a directory component ('..', "
          "'escape.md'), so it is honoured as typed rather than refused — "
          "only a bare name with nothing left to call a file is",
          T.resolve_output_file("../escape.md") == Path("../escape.md"))

# warn_if_committable judges a ~-expanded copy of whatever it is handed, but
# the path resolve_output_file returned was the unexpanded one — so whether
# the warning's verdict and the path actually written to agreed depended on
# where ~ happened to point. Pointing $HOME at a path inside the repo (never
# created on disk — resolve_output_file only builds a Path, it never touches
# the filesystem) makes that disagreement concrete: the returned path must be
# the expanded one, and must be judged for the warning on that same path.
_real_home = os.environ.get("HOME")
try:
    os.environ["HOME"] = str(ROOT / "documents")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        got = T.resolve_output_file("~/meeting.readable.md")
    check("a ~ in a --output is expanded in the path handed back, not left "
          "for the caller to expand a second time",
          got == ROOT / "documents" / "meeting.readable.md", got)
    check("...and it is judged for the warning on that same expanded path, "
          "so the two can no longer disagree",
          "Warning" in err.getvalue(), err.getvalue())
finally:
    if _real_home is None:
        os.environ.pop("HOME", None)
    else:
        os.environ["HOME"] = _real_home

check.section("a refused --output reaches the user as a sentence, not a traceback")
# resolve_output_file raises so a caller can handle the refusal; every CLI that
# calls it wants the other thing — readable.py, diarize.py and names.py all
# turn a bad path into an exit, the way prompt.py does for a template it cannot
# read. The wrapper is what they share, so the message is written once.
check.raises("a directory handed to a CLI exits rather than raising, so the "
             "user gets a sentence instead of a stack trace",
             T.resolve_output_file_arg, "notes/", expect=SystemExit)
try:
    T.resolve_output_file_arg("notes/")
except SystemExit as e:
    check("the exit carries the refusal itself, so nothing has to restate it",
          "must name a file" in str(e) and "notes/" in str(e), str(e))
# The same rule serves --output, --speakers and --names. A refusal that always
# said "--output" would send someone to a flag they never typed.
for _flag in ("--speakers", "--names"):
    try:
        T.resolve_output_file_arg("sidecars/", _flag)
    except SystemExit as e:
        check(f"a refusal names {_flag}, the flag the value actually arrived on",
              str(e).startswith(_flag), str(e))
with contextlib.redirect_stderr(io.StringIO()):
    check("a good path is returned unchanged, so the wrapper only differs from "
          "resolve_output_file when it refuses",
          T.resolve_output_file_arg("notes.readable.md")
          == T.resolve_output_file("notes.readable.md"))

check.section("transcript files are UTF-8 whatever the locale says")
# Whisper output routinely contains non-ASCII, and backup_file round-trips a
# whole transcript through a decode and an encode — under a non-UTF-8 locale a
# default-encoding open would corrupt the very copy that undoes an in-place
# repair. Proven in a child interpreter, because the encoding an open() picks
# by default is fixed when the interpreter starts.
child = f'''
import locale, sys, tempfile
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
enc = locale.getpreferredencoding(False)
if "utf" in enc.lower().replace("-", ""):
    print("SKIP " + enc)
    raise SystemExit(0)
import transcribe as T
said = "caf\\u00e9 na\\u00efve \\u2014 \\u4f1a\\u8b70"
with tempfile.TemporaryDirectory() as d:
    stem = Path(d) / "meeting"
    T.save_output({{"text": said,
                   "segments": [{{"start": 0.0, "end": 1.0, "text": said}}]}},
                  stem, True)
    ts = Path(str(stem) + ".timestamped.txt")
    assert said.encode("utf-8") in ts.read_bytes(), "not written as utf-8"
    assert T.load_timestamped(ts)[0]["text"] == said, "did not read back"
    assert T.backup_file(ts).read_bytes() == ts.read_bytes(), "backup differs"
print("OK")
'''
r = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True,
                   env=dict(os.environ, LC_ALL="C", LANG="C",
                            PYTHONUTF8="0", PYTHONCOERCECLOCALE="0"))
if r.stdout.startswith("SKIP"):
    check.skip("saving, reading back and backing up non-ASCII speech",
               f"this interpreter cannot be made non-UTF-8: {r.stdout.strip()}")
else:
    check("saving, reading back and backing up non-ASCII speech survives an "
          "interpreter whose locale encoding is ASCII",
          r.returncode == 0 and r.stdout.strip().endswith("OK"),
          (r.stdout[-200:], r.stderr[-400:]))

check.section("the repaired transcript is written in the order repair returned")
if _repair is None:
    check.skip("main writes the repaired segments in the order repair returned",
               "repair.py not importable here")
else:
    # main() writes twice: once for the raw transcription and again if the repair
    # spliced anything. That second write used to sort the segments first — a
    # no-op on everything the merge produces, since clamp_to_chunk makes a rewind
    # impossible in a fresh transcript (MERGE-2, MERGE-3), and destructive on a
    # repair that handed one back anyway: it shuffles the rewound block
    # line-by-line into the speech underneath it and erases the backwards jump
    # that is the only evidence of it (SEAM-8, VERIFY-3). Nothing decodes and
    # nothing is written here: transcribe and the repair cycle are stubbed and
    # save_output is a recorder, so this is the wiring alone.
    rewound = [
        {"start": 100.0, "end": 106.0, "text": "the sentence that was really there"},
        {"start": 106.0, "end": 112.0, "text": "and the one that followed it"},
        {"start": 112.0, "end": 118.0, "text": "the last thing said before the seam"},
        {"start": 106.0, "end": 109.0, "text": "the overrun tail, restamped backwards"},
        {"start": 109.0, "end": 112.0, "text": "still the overrun tail"},
        {"start": 118.0, "end": 124.0, "text": "what the next chunk actually heard"},
    ]
    saved = []
    _real_transcribe, _real_save = T.transcribe, T.save_output
    _real_cycle = _repair.diagnose_repair_verify
    _argv_was = sys.argv
    try:
        T.transcribe = lambda *a, **kw: {
            "text": " ".join(s["text"] for s in rewound),
            "segments": [dict(s) for s in rewound],
        }
        T.save_output = lambda result, path, stamps: saved.append(result["segments"])
        # Hands back what it was given, with a report row that says a window was
        # spliced — which is the only condition under which main writes twice.
        _repair.diagnose_repair_verify = lambda audio, segs, opts, **kw: (
            segs, [((100.0, 124.0), "repaired", True, 12, 12)], [])
        # FIXTURE.path is passed only because it exists and has a directory
        # component; no byte of it is read, since transcribe never runs.
        sys.argv = ["transcribe.py", str(FIXTURE.path)]
        with contextlib.redirect_stdout(io.StringIO()):
            T.main()
    finally:
        T.transcribe, T.save_output = _real_transcribe, _real_save
        _repair.diagnose_repair_verify = _real_cycle
        sys.argv = _argv_was

    check("a repair that spliced something rewrites the files, so what is on "
          "disk is the repaired transcript", len(saved) == 2, len(saved))
    check("and that second write is the order the repair returned, segment for "
          "segment, with nothing re-sorting it on the way out",
          [s["text"] for s in saved[-1]] == [s["text"] for s in rewound],
          [s["text"] for s in saved[-1]])
    check("so a backwards jump the repair could not confirm reaches the file, "
          "where verify counts it, instead of being tidied away",
          sum(1 for i in range(1, len(saved[-1]))
              if saved[-1][i]["start"] < saved[-1][i - 1]["start"] - 0.01) == 1,
          [s["start"] for s in saved[-1]])

check.section("the harness protects itself")
# Both of these guard the harness rather than transcribe.py, and both were
# added without coverage because the shard that wrote them could not edit a
# suite. They are here because a harness that silently lies is worse than no
# harness: a truncated fixture would fail the real-audio checks above for a
# reason that has nothing to do with the code under test.
if audio is None:
    check.skip("a half-written audio fixture is rebuilt, not reused",
               "ffmpeg is not installed")
else:
    testlib.FIXTURE_AUDIO.write_bytes(b"RIFF truncated, as an interrupted ffmpeg leaves it")
    rebuilt = testlib.build_audio_fixture()
    check("a half-written audio fixture is rebuilt rather than cached forever",
          rebuilt is not None
          and abs(testlib._probe_duration(rebuilt) - testlib._AUDIO_FIXTURE_DURATION) < 0.5,
          f"still {testlib._probe_duration(testlib.FIXTURE_AUDIO)}s after rebuild")

# raises(expect=...) has to be checked on a throwaway Checks, because the
# behaviour under test is a check *failing*.
probe = testlib.Checks()
with contextlib.redirect_stdout(io.StringIO()):
    probe.raises("", lambda: (_ for _ in ()).throw(TypeError("wrong reason")),
                 expect=ValueError)
check("a rejection that raised for the wrong reason is not counted as the "
      "rejection under test",
      probe.failed == 1 and probe.ok == 0,
      f"ok={probe.ok} failed={probe.failed}")

probe = testlib.Checks()
with contextlib.redirect_stdout(io.StringIO()):
    probe.raises("", lambda: (_ for _ in ()).throw(ValueError("the right reason")),
                 expect=ValueError)
check("the expected exception type still passes", probe.ok == 1 and probe.failed == 0,
      f"ok={probe.ok} failed={probe.failed}")

check.finish()
