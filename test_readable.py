from testlib import Checks, FIXTURE
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

check.finish()
