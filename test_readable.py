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

check.section("the naming caveat comes from an explicit flag, not a sniffed label")
# diarize.one_label renders a non-numeric cluster id as "Robin (SPEAKER_MAIN)"
# — no "(Speaker " substring — so sniffing the rendered label for that
# substring would call this document unnamed. render() must not do that when
# told the truth explicitly.
odd_cluster_marked = [(0.0, "asking the question", "Robin (SPEAKER_MAIN)"),
                      (2.1, "answering it", "Speaker 2")]
odd_named_doc = Rd.render(turn_segs, "meeting", "It happened.",
                          paras=odd_cluster_marked, named=True)
check("a non-numeric cluster id carrying a name still gets the named caveat",
      "speaker names are inferred" in odd_named_doc, odd_named_doc)
check("and not the 'acoustic clusters, not names' caveat a sniff would give it",
      "acoustic clusters, not names" not in odd_named_doc, odd_named_doc)
check("the transcript note says the same thing",
      "Names in brackets were inferred" in odd_named_doc, odd_named_doc)

# The same paragraphs, un-told: this is the defect the explicit flag exists to
# avoid, kept here as a demonstration of why the fallback is only best-effort
# and documented as such rather than trusted.
odd_sniffed_doc = Rd.render(turn_segs, "meeting", "It happened.",
                            paras=odd_cluster_marked)
check("without the flag, sniffing the same paragraphs is fooled by the "
      "non-numeric id",
      "acoustic clusters, not names" in odd_sniffed_doc, odd_sniffed_doc)

# The other direction: a label that *looks* named to a sniff ("(Speaker " is
# present) but the caller explicitly says it is not. named= overrides the
# sniff either way, because it is the truth and the label text is not.
lying_label = [(0.0, "asking the question", "Robin (Speaker 7)"),
              (2.1, "answering it", "Speaker 2")]
override_doc = Rd.render(turn_segs, "meeting", "It happened.",
                         paras=lying_label, named=False)
check("an explicit named=False is honoured even over a label that reads as named",
      "acoustic clusters, not names" in override_doc
      and "speaker names are inferred" not in override_doc, override_doc)

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

# -o names the finished file, not a stem — resolve_output would strip the
# .txt off "notes.txt" and silently write an extensionless "output/notes"
# (LOW-1). resolve_output_file leaves the extension exactly as given.
notes_txt_name = "readable-cli-test-notes.txt"
(OUTPUT_DIR / notes_txt_name).unlink(missing_ok=True)
# Also cleared: the stripped name a bug (or a previous, unfixed run) would
# have written instead, so a leftover from that never masquerades as a pass.
(OUTPUT_DIR / "readable-cli-test-notes").unlink(missing_ok=True)
notes_exit = run_main([transcript_name, "-o", notes_txt_name])
check("-o notes.txt writes output/notes.txt, extension intact",
      notes_exit is None and (OUTPUT_DIR / notes_txt_name).exists(),
      (notes_exit, list(OUTPUT_DIR.glob("readable-cli-test-notes*"))))
check("and not the stripped, extensionless output/notes",
      not (OUTPUT_DIR / "readable-cli-test-notes").exists())

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

check.section("the summary's timestamps are checked against the headings that exist")
# The defect this measures shipped: the summary was written from the raw
# .timestamped.txt, so it cited *segment* times, and only 20% of them were
# paragraph headings in the finished document — four out of five of its own
# cross-references pointed at a heading that was not there (DOC-10). Both
# halves are in hand at assembly time, so the check is free; DOC-13 is why it
# reports rather than refuses.
anchor_paras = [(0.0, "how the meeting opened"),
                (754.0, "the middle bit"),
                (3725.0, "and how it ended")]
anchor_clocks = [Rd.fmt_clock(p[0]) for p in anchor_paras]
cited_summary = "\n".join([
    "## Executive summary",
    "",
    f"It opened at **[{anchor_clocks[0]}]** and ran long.",
    f"The decision was taken at [{anchor_clocks[1]}], revisited at "
    f"[{anchor_clocks[1]}], and closed at `[{anchor_clocks[2]}]`.",
    "Rounded off, that first one is [0:12:30], and padded it is [00:12:34].",
    "See also [the Thornbury Cove notes](notes.md), which are not a citation.",
])
cited, missing = Rd.cited_anchors(cited_summary, anchor_paras)
check("a citation is found however the markdown wraps it — bare, bold or in "
      "backticks",
      all(c in cited for c in anchor_clocks), cited)
check("a timestamp cited twice counts once, since it names one place to look",
      cited.count(anchor_clocks[1]) == 1, cited)
check("text in brackets that is not a clock is not a citation",
      len(cited) == len(anchor_clocks) + 2, cited)
check("the three real ones resolve, and only the two bad ones are reported "
      "missing",
      not any(c in missing for c in anchor_clocks) and len(missing) == 2,
      missing)
check("a rounded citation resolves to nothing, because the reader's search "
      "for it will too",
      "0:12:30" in missing, missing)
check("and a padded hour is not the heading transcript_lines writes either",
      "00:12:34" in missing, missing)
anchor_only = "\n".join(Rd.transcript_lines(anchor_paras))
check("what it compares against is exactly the anchors transcript_lines "
      "renders, so the two cannot drift",
      bool(cited) and bool(missing)
      and all(f"**[{c}]**" in anchor_only for c in cited if c not in missing)
      and all(f"**[{c}]**" not in anchor_only for c in missing), anchor_only)
check("a summary citing nothing reports nothing, not a perfect score",
      Rd.cited_anchors("It happened, at no stated time.", anchor_paras)
      == ([], []))
check("an absent summary is handled without raising",
      Rd.cited_anchors(None, anchor_paras) == ([], []))

# A transcript whose paragraphs are known one per planted start: 3s of speech
# every 10s, so the 7s between them is well past PARAGRAPH_PAUSE. Ten of them,
# which is what makes a share rather than a count testable.
from contextlib import redirect_stderr

anchor_starts = [i * 10.0 for i in range(10)]
anchor_tx = "readable-anchor-test.timestamped.txt"
anchor_out = "readable-anchor-test.readable.md"
(OUTPUT_DIR / anchor_tx).write_text("".join(
    f"[00:{int(s) // 60:02d}:{int(s) % 60:02d}.00 --> "
    f"00:{int(s + 3) // 60:02d}:{int(s + 3) % 60:02d}.00]  "
    f"the {i}th thing anyone said\n"
    for i, s in enumerate(anchor_starts)))
real_anchors = [Rd.fmt_clock(s) for s in anchor_starts]
check("the anchor fixture really is one paragraph per planted start",
      len(Rd.paragraphs(T.load_timestamped(OUTPUT_DIR / anchor_tx)))
      == len(anchor_starts),
      len(Rd.paragraphs(T.load_timestamped(OUTPUT_DIR / anchor_tx))))
# Deliberately not multiples of ten: none of these is a heading in that file.
bogus_anchors = ["0:00:05", "0:00:07", "0:00:13", "0:00:21", "0:00:34",
                 "0:00:47", "0:01:11", "0:01:47"]


def write_anchor_summary(name, good, bogus):
    """A summary citing `good` headings and `bogus` places that are not."""
    body = ["## Executive summary", "", "Something was decided.", ""]
    body += [f"- a point worth finding, at `[{c}]`" for c in good + bogus]
    (OUTPUT_DIR / name).write_text("\n".join(body) + "\n")
    return name


def run_main_captured(argv):
    """
    main()'s exit code, stdout and stderr. Both streams are needed because the
    count and the warning deliberately go to different ones — a redirected
    stdout must not swallow the warning.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = run_main(argv)
    return code, out.getvalue(), err.getvalue()


all_good = write_anchor_summary("readable-anchor-all.summary.md",
                                real_anchors, [])
good_exit, good_out, good_err = run_main_captured(
    [anchor_tx, "--summary", all_good, "-o", anchor_out])
check("a healthy document reports every cited timestamp resolving",
      good_exit is None
      and f"{len(real_anchors)} of {len(real_anchors)}" in good_out, good_out)
check("and says what the number means, rather than printing a bare ratio",
      "resolve to a paragraph heading" in good_out, good_out)
check("a document whose citations all land warns about nothing",
      good_err == "", good_err)
check("the count stays on the console — the reader's document carries the "
      "caveat about the summary, not a statistic about it",
      "resolve to a paragraph heading" not in
      (OUTPUT_DIR / anchor_out).read_text()
      and "Summary anchors" not in (OUTPUT_DIR / anchor_out).read_text())

# Nine of ten: one anchor gone stale in a hand-edited summary is a typo, not
# the wiring failure, and must not cry wolf. This pins ANCHOR_WARN at or below
# 0.9.
nine = write_anchor_summary("readable-anchor-nine.summary.md",
                            real_anchors[:-1], bogus_anchors[:1])
nine_exit, nine_out, nine_err = run_main_captured(
    [anchor_tx, "--summary", nine, "-o", anchor_out])
check("nine citations in ten landing is reported plainly",
      nine_exit is None and f"9 of {len(real_anchors)}" in nine_out, nine_out)
check("and is not warned about — one stale anchor is a typo, not a defect in "
      "how the summary was written",
      nine_err == "", nine_err)

# Eight of ten: the other side of the threshold, so the two checks together
# pin it between 0.8 and 0.9 rather than merely asserting it is somewhere.
eight = write_anchor_summary("readable-anchor-eight.summary.md",
                             real_anchors[:-2], bogus_anchors[:2])
eight_exit, eight_out, eight_err = run_main_captured(
    [anchor_tx, "--summary", eight, "-o", anchor_out])
check("eight in ten is materially below all of them, and is warned about",
      eight_exit is None and "WARNING" in eight_err, (eight_out, eight_err))

# The measured failure itself: two citations in ten, the 20% the summary
# written from the raw transcript scored.
raw_like = write_anchor_summary("readable-anchor-raw.summary.md",
                                real_anchors[:2], bogus_anchors)
raw_exit, raw_out, raw_err = run_main_captured(
    [anchor_tx, "--summary", raw_like, "-o", anchor_out])
check("the 20% case that shipped is caught",
      raw_exit is None and "WARNING" in raw_err, (raw_out, raw_err))
check("the warning names timestamps the reader would have searched for in vain",
      f"[{bogus_anchors[0]}]" in raw_err, raw_err)
check("and says how to fix it, since the summary is what has to be rebuilt",
      "--transcript-only" in raw_err, raw_err)
check("a poor score is reported, never enforced: the document is still written",
      (OUTPUT_DIR / anchor_out).exists()
      and "Something was decided." in (OUTPUT_DIR / anchor_out).read_text()
      and "the 0th thing anyone said" in (OUTPUT_DIR / anchor_out).read_text())
check("the exit code stays clean, so `make readable` does not lose the "
      "summary it paid for",
      raw_exit is None, raw_exit)

# Without a summary there is nothing to cite and nothing to say about it.
plain_exit, plain_out, plain_err = run_main_captured(
    [anchor_tx, "-o", anchor_out])
check("a document with no summary reports no anchor count at all",
      plain_exit is None and "Summary anchors" not in plain_out
      and plain_err == "", (plain_out, plain_err))

# A summary that cites nothing is its own signal, and still not an error.
(OUTPUT_DIR / "readable-anchor-none.summary.md").write_text(
    "## Executive summary\n\nIt happened, at no stated time.\n")
none_exit, none_out, none_err = run_main_captured(
    [anchor_tx, "--summary", "readable-anchor-none.summary.md",
     "-o", anchor_out])
check("a summary citing no timestamps says so instead of scoring 100%",
      none_exit is None and "no [H:MM:SS] anchors" in none_out
      and "0 of 0" not in none_out, none_out)
check("and is not warned about, since nothing was mis-cited",
      none_err == "", none_err)

# --transcript-only is piped into the summariser, so nothing but the
# transcript may reach stdout — the count would land in the middle of it.
to_exit, to_out, to_err = run_main_captured([anchor_tx, "--transcript-only"])
check("--transcript-only still prints the transcript and nothing about anchors",
      to_exit is None and "the 0th thing anyone said" in to_out
      and "Summary anchors" not in to_out
      and "resolve to a paragraph heading" not in to_out, to_out)

check.section("a named, non-numeric cluster carries its caveat through main()")
# The end-to-end version of the sniffing defect: diarize.one_label renders a
# non-numeric id as "Wren Ashby (SPEAKER_MAIN)", which contains no "(Speaker "
# for a sniff to find, so a sniffed document would caption a named transcript
# as unnamed. This drives the real path — sidecar, names sidecar,
# speaker_labels, paragraphs, render — rather than hand-built paragraphs.
odd_tx = "readable-named-test.timestamped.txt"
odd_out = "readable-named-test.readable.md"
(OUTPUT_DIR / odd_tx).write_text(
    "[00:00:00.00 --> 00:00:02.00]  opening the meeting\n"
    "[00:00:02.00 --> 00:00:04.00]  and closing it again\n")
(OUTPUT_DIR / "readable-named-test.speakers.json").write_text(
    '{"turns": [{"start": 0.0, "end": 4.0, "speaker": "SPEAKER_MAIN"}]}')
odd_names_file = "readable-named-test.names.json"
(OUTPUT_DIR / odd_names_file).write_text(
    '{"names": {"SPEAKER_MAIN": {"name": "Wren Ashby", '
    '"confidence": "high", "basis": "introduces themselves"}}}')
odd_summary = "readable-named-test.summary.md"
(OUTPUT_DIR / odd_summary).write_text(
    "## Executive summary\n\nWren Ashby opened at [0:00:00].\n")

# --names alone, so the "--names implies --speakers" path and the bare sidecar
# lookup are both exercised on the way through.
odd_exit, _, _ = run_main_captured(
    [odd_tx, "--names", odd_names_file, "--summary", odd_summary,
     "-o", odd_out])
odd_doc = (OUTPUT_DIR / odd_out).read_text()
check("--names alone finds the speaker sidecar it implies", odd_exit is None,
      odd_exit)
check("the named, non-numeric cluster is labelled with both name and id",
      "Wren Ashby (SPEAKER_MAIN)" in odd_doc, odd_doc)
check("the assembled document gets the named caveat under the summary",
      "speaker names are inferred" in odd_doc, odd_doc)
check("not the 'acoustic clusters, not names' one a sniffed label would give it",
      "acoustic clusters, not names" not in odd_doc, odd_doc)
check("the transcript note says names were inferred too",
      "Names in brackets were inferred" in odd_doc, odd_doc)
check("no label in the document contains the substring the old sniff looked "
      "for, so nothing could have made it right by accident",
      "(Speaker " not in odd_doc, odd_doc)

# The other half of the same fact: main() must pass the truth on every path,
# and `names` is bound before the --speakers block for exactly that reason.
spk_only_exit, _, _ = run_main_captured(
    [odd_tx, "--speakers", "readable-named-test.speakers.json",
     "--summary", odd_summary, "-o", odd_out])
check("clusters without a names sidecar get the unnamed caveat, not a guess",
      spk_only_exit is None
      and "acoustic clusters, not names" in (OUTPUT_DIR / odd_out).read_text(),
      spk_only_exit)
try:
    # Caught rather than allowed to propagate: if `names` is ever initialised
    # inside `if args.speakers:` again, this path raises UnboundLocalError at
    # `named=bool(names)`, and that is a failed check, not a broken suite.
    unlabelled_exit, _, _ = run_main_captured(
        [odd_tx, "--summary", odd_summary, "-o", odd_out])
except Exception as e:
    unlabelled_exit = f"{type(e).__name__}: {e}"
check("a document with a summary and no --speakers at all still assembles: "
      "main() knows the naming answer on every path",
      unlabelled_exit is None, unlabelled_exit)
check("and it says speakers are not labelled, because they are not",
      "speakers are not labelled" in (OUTPUT_DIR / odd_out).read_text(),
      (OUTPUT_DIR / odd_out).read_text())

check.finish()
