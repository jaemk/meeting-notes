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

bad_name = "readable-cli-test-malformed.timestamped.txt"
(OUTPUT_DIR / bad_name).write_text("this line has no timestamp at all\n")
bad_exit = run_main([bad_name])
check("a malformed transcript line exits cleanly instead of raising ValueError",
      isinstance(bad_exit, str), bad_exit)
if isinstance(bad_exit, str):
    check("the clean error names the file that failed to parse",
          bad_name in bad_exit, bad_exit)

check.finish()
