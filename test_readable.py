import pathlib
import sys
from testlib import Checks, FIXTURE, OUTPUT_DIR
import transcribe as T
import readable as Rd

check = Checks()

check.section("paragraphs break where the room went quiet")
segs = [{"start": 0.0, "end": 2.0, "text": "first thought"},
        {"start": 2.1, "end": 4.0, "text": "still the same one"},
        {"start": 7.0, "end": 9.0, "text": "after a long pause"},
        {"start": 9.1, "end": 11.0, "text": "carrying on"}]
paras = Rd.paragraphs(segs)
check("a 3s pause starts a new paragraph, a 0.1s one does not",
      [p[1] for p in paras] == ["first thought still the same one",
                                "after a long pause carrying on"], paras)
check("each paragraph is stamped with its own first segment",
      [p[0] for p in paras] == [0.0, 7.0], [p[0] for p in paras])
check("a pause exactly at the threshold breaks",
      len(Rd.paragraphs([{"start": 0.0, "end": 1.0, "text": "a"},
                         {"start": 3.0, "end": 4.0, "text": "b"}])) == 2)

# An unbroken monologue still has to arrive in readable pieces.
monologue = [{"start": float(i), "end": i + 1.0, "text": "word " * 20}
             for i in range(10)]
check("a speaker who never pauses is still split by length",
      len(Rd.paragraphs(monologue)) > 1, len(Rd.paragraphs(monologue)))
check("and the split respects the word cap",
      all(len(p[1].split()) <= Rd.PARAGRAPH_WORDS + 20
          for p in Rd.paragraphs(monologue)),
      [len(p[1].split()) for p in Rd.paragraphs(monologue)])

check.section("empty segments never become empty paragraphs")
holes = [{"start": 0.0, "end": 1.0, "text": "said something"},
         {"start": 1.0, "end": 2.0, "text": "   "},
         {"start": 2.0, "end": 3.0, "text": "and then more"}]
check("blank text is skipped rather than breaking the paragraph",
      [p[1] for p in Rd.paragraphs(holes)] == ["said something and then more"],
      Rd.paragraphs(holes))
check("a transcript of nothing but blanks yields no paragraphs",
      Rd.paragraphs([{"start": 0.0, "end": 1.0, "text": ""}]) == [])

check.section("speaker labels break a paragraph where a pause would not")
turn_segs = [{"start": 0.0, "end": 2.0, "text": "asking the question"},
             {"start": 2.1, "end": 4.0, "text": "and finishing it"},
             {"start": 4.1, "end": 6.0, "text": "answering it"}]
plain = Rd.paragraphs(turn_segs)
marked = Rd.paragraphs(turn_segs, labels=["Speaker 1", "Speaker 1", "Speaker 2"])
check("without labels the three run together, since nobody paused",
      len(plain) == 1, plain)
check("with labels the change of speaker splits them",
      len(marked) == 2, marked)
check("and each paragraph carries the label it belongs to",
      [p[2] for p in marked] == ["Speaker 1", "Speaker 2"], marked)
check("the words are unchanged by labelling",
      " ".join(p[1] for p in marked) == plain[0][1], marked)
check("an unlabelled paragraph reports None rather than inventing a speaker",
      plain[0][2] is None, plain[0])
check("a pause still breaks inside one speaker's own run",
      len(Rd.paragraphs(segs, labels=["Speaker 1"] * 4)) == 2,
      Rd.paragraphs(segs, labels=["Speaker 1"] * 4))
check("labels are indexed by segment, so a blank segment does not shift them",
      [p[2] for p in Rd.paragraphs(holes, labels=["A", "B", "A"])] == ["A"],
      Rd.paragraphs(holes, labels=["A", "B", "A"]))

check.section("a labelled document says the labels are not names")
labelled_doc = Rd.render(turn_segs, "meeting", paras=marked)
check("each speaker's paragraph is attributed in the body",
      "Speaker 1 — asking" in labelled_doc and "Speaker 2 — answering" in labelled_doc,
      labelled_doc)
check("the document warns that a label is a cluster, not a person",
      "not names" in labelled_doc)
check("an unlabelled document makes no such claim, having made no labels",
      "not names" not in Rd.render(turn_segs, "meeting"))
check("the summary note tracks whether speakers were labelled",
      "acoustic clusters, not names" in
      Rd.render(turn_segs, "meeting", "It happened.", paras=marked)
      and "speakers are not labelled" in
      Rd.render(turn_segs, "meeting", "It happened."))

check.section("the clock is written for reading, not sorting")
check("hours are unpadded and minutes and seconds are",
      Rd.fmt_clock(3 * 3600 + 4 * 60 + 5) == "3:04:05", Rd.fmt_clock(11045))
check("under an hour still shows the hour, so columns line up",
      Rd.fmt_clock(65) == "0:01:05", Rd.fmt_clock(65))
check("fractions are truncated, never rounded up past the segment",
      Rd.fmt_clock(59.9) == "0:00:59", Rd.fmt_clock(59.9))

check.section("the title names the meeting, not the pipeline")
check("a repaired transcript is titled like the recording",
      Rd.document_title("output/2026-07-25.repaired") == "2026-07-25",
      Rd.document_title("output/2026-07-25.repaired"))
check("an ordinary transcript keeps its name",
      Rd.document_title("output/2026-07-25") == "2026-07-25")
check("'.repaired' anywhere but the end is left alone",
      Rd.document_title("output/2026.repaired.notes") == "2026.repaired.notes")

check.section("the document")
real = T.load_timestamped(FIXTURE.path)
doc = Rd.render(real, "2026-07-25")
check("opens with the title", doc.startswith("# Meeting transcript — 2026-07-25"))
check("states what it is before anything else",
      "words ·" in doc.split("---")[0], doc.split("\n")[2])
check("no summary means no summary heading", "## Executive summary" not in doc)
check("the transcript is all there",
      all(s["text"].strip() in doc for s in real if s["text"].strip()))
check("every paragraph carries a timestamp",
      doc.count("**[") == len(Rd.paragraphs(real)), doc.count("**["))

with_summary = Rd.render(real, "2026-07-25", "## Executive summary\n\nIt happened.")
check("a summary is placed above the transcript",
      with_summary.index("## Executive summary") <
      with_summary.index("## Full transcript"))
check("and is labelled as machine-written, since it is",
      "written by Claude" in with_summary)
check("the transcript survives the summary being added",
      with_summary.split("## Full transcript")[1] ==
      doc.split("## Full transcript")[1])

check.section("a caller-supplied paragraph list is used, not recomputed")
custom_paras = [(0.0, "totally custom body text")]
custom_doc = Rd.render(real, "2026-07-25", paras=custom_paras)
check("the document's transcript came from the paragraphs passed in",
      "totally custom body text" in custom_doc and
      custom_doc.count("**[") == 1, custom_doc.count("**["))
check("render still paragraphs for itself when nothing is passed",
      Rd.render(real, "2026-07-25").count("**[") == len(Rd.paragraphs(real)))

check.section("running time survives a rewind")
# A chunk that overran its seam and was merged verbatim (repair.py leaves
# this alone unless it has the audio — see CLAUDE.md) puts a segment near
# the end of the list whose own end is far short of the transcript's real
# extent. The reproduction from the finding: three segments, last one
# ending at 5:10, actual extent is 10:00.
rewound = [
    {"start": 0.0, "end": 300.0, "text": "first chunk covers the first five minutes"},
    {"start": 305.0, "end": 600.0, "text": "second chunk runs on to the real end"},
    {"start": 295.0, "end": 310.0, "text": "first chunk's overrun tail, stamped before the seam"},
]
rewound_doc = Rd.render(rewound, "rewind-case")
check("the header reports the transcript's real extent, not the last segment's",
      "0:10:00 running time" in rewound_doc, rewound_doc.split("\n")[2])
check("not the pre-fix answer, which stopped at the last segment's own end",
      "0:05:10 running time" not in rewound_doc)
check("paragraphs() itself doesn't raise on a backwards jump",
      len(Rd.paragraphs(rewound)) >= 1, Rd.paragraphs(rewound))

check.section("main()'s file lookups and error handling")
transcript_name = "readable-cli-test.timestamped.txt"
summary_name = "readable-cli-test.summary.md"
output_name = "readable-cli-test.readable.md"
(OUTPUT_DIR / transcript_name).write_text(
    "[00:00:00.00 --> 00:00:02.00]  hello there\n"
    "[00:00:02.00 --> 00:00:04.00]  general kenobi\n"
)
(OUTPUT_DIR / summary_name).write_text("## Executive summary\n\nIt happened.\n")


def run_main(argv):
    old_argv = sys.argv
    sys.argv = ["readable.py"] + argv
    try:
        Rd.main()
        return None
    except SystemExit as e:
        return e.code
    finally:
        sys.argv = old_argv


exit_code = run_main([transcript_name, "--summary", summary_name, "-o", output_name])
check("a bare --summary name resolves in output/, same as the transcript",
      exit_code is None, exit_code)
check("a bare --output name is also written into output/, not the cwd",
      (OUTPUT_DIR / output_name).exists(), OUTPUT_DIR / output_name)
if (OUTPUT_DIR / output_name).exists():
    check("the resolved summary made it into the document",
          "It happened." in (OUTPUT_DIR / output_name).read_text())

check.section("--speakers on the command line")
speakers_name = "readable-cli-test.speakers.json"
# Removed rather than assumed absent: the run below writes it, so leaving it
# in place makes this check pass on a first run and fail on every later one.
(OUTPUT_DIR / speakers_name).unlink(missing_ok=True)
missing_exit = run_main([transcript_name, "--speakers", "-o", output_name])
check("with no sidecar anywhere it says so instead of rendering unlabelled",
      isinstance(missing_exit, str) and "diarize.py run" in missing_exit,
      missing_exit)

(OUTPUT_DIR / speakers_name).write_text(
    '{"turns": [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},'
    ' {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"}]}')
spk_exit = run_main([transcript_name, "--speakers", "-o", output_name])
check("a bare --speakers finds the sidecar beside the transcript",
      spk_exit is None, spk_exit)
if (OUTPUT_DIR / output_name).exists():
    spk_doc = (OUTPUT_DIR / output_name).read_text()
    check("both planted voices are named in the rendered document",
          "Speaker 0" in spk_doc and "Speaker 1" in spk_doc, spk_doc)
    check("the transcript's own words are still all present",
          "hello there" in spk_doc and "general kenobi" in spk_doc)

named_exit = run_main([transcript_name, "--speakers", speakers_name,
                       "-o", output_name])
check("naming the sidecar explicitly works the same way",
      named_exit is None, named_exit)
bad_sidecar = "readable-cli-test.badspeakers.json"
(OUTPUT_DIR / bad_sidecar).write_text("{not json")
bad_side_exit = run_main([transcript_name, "--speakers", bad_sidecar,
                          "-o", output_name])
check("an unreadable sidecar is refused rather than silently dropped",
      isinstance(bad_side_exit, str) and "Can't read" in bad_side_exit,
      bad_side_exit)

no_spk_exit = run_main([transcript_name, "-o", output_name])
check("without --speakers the sidecar is ignored even when it is sitting there",
      no_spk_exit is None
      and "Speaker 0" not in (OUTPUT_DIR / output_name).read_text())

check.section("--transcript-only is the summariser's view of the document")
# The wiring this protects: the summary used to be written from the raw
# .timestamped.txt while the document below it carried speakers and names, so
# the summariser announced "this transcript is not diarized" above a diarized
# transcript and cited timestamps that matched no heading in the finished file.
# Both halves now render through transcript_lines, so they cannot disagree.
segs_two = [{"start": 0.0, "end": 2.0, "text": "hello there"},
            {"start": 2.0, "end": 4.0, "text": "general kenobi"}]
lab_paras = Rd.paragraphs(segs_two, labels=["Robin (Speaker 0)", "Speaker 1"])
only = "\n".join(Rd.transcript_lines(lab_paras))
doc_with = Rd.render(segs_two, "t", summary="## Executive summary\n\nx",
                     paras=lab_paras)

check("every line it emits appears verbatim in the assembled document",
      all(ln in doc_with for ln in only.splitlines() if ln.strip()), only)
check("it carries the speaker labels, so the summariser can see who spoke",
      "Robin (Speaker 0)" in only and "Speaker 1" in only, only)
check("it carries the same [H:MM:SS] anchors the document headings use",
      "**[0:00:00]**" in only and "**[0:00:02]**" in only, only)
check("it stops at the transcript — no heading, no summary, no notes",
      "# Meeting transcript" not in only
      and "Executive summary" not in only
      and "pyannote" not in only, only)

# The reason the pipe in `make readable` is safe: stdout is the transcript and
# only the transcript, so a progress line cannot end up inside the summary.
import io
from contextlib import redirect_stdout

buf = io.StringIO()
with redirect_stdout(buf):
    to_exit = run_main([transcript_name, "--speakers", speakers_name,
                        "--transcript-only"])
piped = buf.getvalue()
check("--transcript-only exits cleanly", to_exit is None, to_exit)
check("it writes the transcript to stdout, ready to pipe into the summariser",
      "hello there" in piped and "general kenobi" in piped, piped)
check("and writes nothing else there — no 'Saved:' line to corrupt the pipe",
      "Saved:" not in piped, piped)
check("the labels from the sidecar reach stdout too",
      "Speaker 0" in piped and "Speaker 1" in piped, piped)

# --summary opens a document; --transcript-only builds no document. Honouring
# either one silently would hide that the other was ignored.
clash = run_main([transcript_name, "--transcript-only",
                  "--summary", summary_name])
check("asking for a summary and no document at once is refused, not guessed",
      isinstance(clash, str) and "--transcript-only" in clash, clash)

before = (OUTPUT_DIR / output_name).read_text()
with redirect_stdout(io.StringIO()):
    run_main([transcript_name, "--transcript-only", "-o", output_name])
check("it never writes the document, so a summary pass cannot clobber one",
      (OUTPUT_DIR / output_name).read_text() == before)

check.section("a reader that stops early closes the pipe, it does not crash")
# `--transcript-only` is built to be piped, so the reader going away first is
# ordinary, not exceptional: `| head` while eyeballing it, or a summariser that
# dies on its first read. Without the devnull redirect this printed a
# BrokenPipeError traceback and then a second "Exception ignored" during
# interpreter shutdown.
#
# Deliberately not the shared fixture: it renders to about 10KB, which fits
# inside the 64KB pipe buffer, so the write would succeed and the test would
# pass without ever breaking a pipe. This transcript is sized past the buffer
# so the EPIPE is the point of the test rather than a coincidence of timing.
import subprocess

big_name = "readable-pipe-test.timestamped.txt"
big_path = OUTPUT_DIR / big_name
big_path.write_text("".join(
    f"[{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}.00 --> "
    f"{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}.99]  "
    + "a much longer line of transcript text to push past the buffer\n"
    for i in range(2000)))
rendered = subprocess.run(
    [sys.executable, "readable.py", str(big_path), "--transcript-only"],
    capture_output=True, text=True)
check("the oversized transcript really does exceed a 64KB pipe buffer",
      len(rendered.stdout.encode()) > 65536, len(rendered.stdout.encode()))

piped_run = subprocess.run(
    f"{sys.executable} readable.py {big_path} --transcript-only | head -c 1",
    shell=True, capture_output=True, text=True)
check("a closed pipe prints no traceback",
      "BrokenPipeError" not in piped_run.stderr
      and "Traceback" not in piped_run.stderr, piped_run.stderr)
check("and no 'Exception ignored' from the flush on the way out",
      "Exception ignored" not in piped_run.stderr, piped_run.stderr)
check("the reader still got the start of the transcript",
      piped_run.stdout.startswith("*"), piped_run.stdout[:40])

check("writing to a live stream is unaffected",
      (lambda b: (Rd.write_piped("kept", b), b.getvalue())[1])(io.StringIO())
      == "kept")

check.section("--glossary corrects the document without touching the transcript")
# The point of applying corrections here rather than in the summary and the
# document separately: both come from these paragraphs, so a name cannot be
# spelled one way in the summary and another way in the transcript below it.
gloss_name = str(OUTPUT_DIR / "readable-cli-test.glossary.txt")
pathlib.Path(gloss_name).write_text("General Kenobi: general kenobi\n")

buf = io.StringIO()
with redirect_stdout(buf):
    g_exit = run_main([transcript_name, "--glossary", gloss_name,
                       "--transcript-only"])
g_piped = buf.getvalue()
check("--glossary exits cleanly", g_exit is None, g_exit)
check("the summariser's copy is corrected, so the summary spells it right",
      "General Kenobi" in g_piped, g_piped)

g_doc_out = "readable-glossary-test.readable.md"
run_main([transcript_name, "--glossary", gloss_name, "-o", g_doc_out])
g_doc = (OUTPUT_DIR / g_doc_out).read_text()
check("the assembled document is corrected the same way",
      "General Kenobi" in g_doc, g_doc)
check("the document says a glossary was applied, and names what changed",
      "Spellings corrected" in g_doc and "General Kenobi" in g_doc, g_doc)
check("the transcript file itself is left exactly as the decoder wrote it",
      "general kenobi" in (OUTPUT_DIR / transcript_name).read_text()
      and "General Kenobi" not in (OUTPUT_DIR / transcript_name).read_text())
check("a document built without a glossary carries no correction note",
      "Spellings corrected" not in
      (run_main([transcript_name, "-o", g_doc_out]),
       (OUTPUT_DIR / g_doc_out).read_text())[1])

bad_gloss = str(OUTPUT_DIR / "readable-cli-test-bad.glossary.txt")
pathlib.Path(bad_gloss).write_text("no colon on this line\n")
g_bad = run_main([transcript_name, "--glossary", bad_gloss, "-o", g_doc_out])
check("a malformed glossary is refused rather than silently skipped",
      isinstance(g_bad, str) and "Refusing this glossary" in g_bad, g_bad)
g_missing = run_main([transcript_name, "--glossary", "no-such-glossary.txt",
                      "-o", g_doc_out])
check("naming a glossary that is not there is an error, not a no-op",
      isinstance(g_missing, str) and "No glossary at" in g_missing, g_missing)

bad_name = "readable-cli-test-malformed.timestamped.txt"
(OUTPUT_DIR / bad_name).write_text("this line has no timestamp at all\n")
bad_exit = run_main([bad_name])
check("a malformed transcript line exits cleanly instead of raising ValueError",
      isinstance(bad_exit, str), bad_exit)
if isinstance(bad_exit, str):
    check("the clean error names the file that failed to parse",
          bad_name in bad_exit, bad_exit)

check.finish()
