"""
What a filename is allowed to do.

Two things are under test here and they are the same thing seen twice: prompt.py
fills placeholders in without ever letting a value become program text, and the
Makefile expands paths into recipes without ever letting a name become a
command. A recording is called whatever the phone, the download or the AirDrop
called it, so both have to hold for names nobody chose carefully.

The Makefile checks read `make -n`, which expands every recipe and runs none of
them, so no test here decodes anything, deletes anything of the user's, or costs
a minute. The one target that does get run for real — distclean — is run against
a throwaway copy of the Makefile in a temporary directory.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from testlib import Checks, ROOT
import prompt as P

check = Checks()

MAKE = shutil.which("make")

# A name with a space in it: the ordinary case, not the exotic one.
SPACED = "local/my recording.m4a"
# A name that ends the quoting and starts a command, which is what a file
# dropped into local/ by a sync client can be called.
NASTY = "local/x'; id; '.m4a"


# ── helpers ────────────────────────────────────────────────────────────────────

def logical_lines(text):
    """make -n prints continuations; the shell sees one line, so should we."""
    lines, buf = [], ""
    for raw in text.splitlines():
        buf += raw
        if buf.endswith("\\"):
            buf = buf[:-1] + " "
            continue
        if buf.strip():
            lines.append(buf)
        buf = ""
    if buf.strip():
        lines.append(buf)
    return lines


def expand(target=None, **variables):
    """The recipe make would run, expanded but not executed."""
    args = [MAKE, "-n"] + ([target] if target else []) \
        + [f"{k}={v}" for k, v in variables.items()]
    done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return done.stdout


def words(line):
    """How a shell would split the line. ValueError means the quoting is off."""
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return None


TARGETS = ["transcribe", "check", "fix", "analyze", "readable", "clean"]


# ── prompt.py ──────────────────────────────────────────────────────────────────

check.section("a placeholder value is data, never program text")

hostile = "local/x'; id; '.m4a"
check("a single quote in the value comes out as a single quote",
      P.render("see @AUDIO@ now", {"@AUDIO@": hostile}) == f"see {hostile} now",
      P.render("see @AUDIO@ now", {"@AUDIO@": hostile}))

for name, value in [("a semicolon", "a;b"), ("an ampersand", "a&b"),
                    ("a pipe", "a|b"), ("a backslash", r"a\b"),
                    ("a dollar sign", "a$b"), ("a backtick", "a`b`c"),
                    ("a newline", "a\nb"), ("a quote and a semicolon",
                                            "a\"; id; \"b")]:
    check(f"{name} in the value survives byte for byte",
          P.render("[@AUDIO@]", {"@AUDIO@": value}) == f"[{value}]",
          P.render("[@AUDIO@]", {"@AUDIO@": value}))

# The old implementation was `sed -e 's|@AUDIO@|VALUE|'`, where these mean
# something to the replacement side rather than being characters.
for name, value in [("a sed backreference", r"\1"),
                    ("sed's whole-match &", "&"),
                    ("a regex replacement group", r"\g<0>"),
                    ("a regex metacharacter", ".*")]:
    check(f"{name} in the value is a character, not an instruction",
          P.render("@AUDIO@", {"@AUDIO@": value}) == value,
          P.render("@AUDIO@", {"@AUDIO@": value}))

check("both placeholders are filled from their own values",
      P.render("@AUDIO@ -> @TRANSCRIPT@",
               {"@AUDIO@": "a.m4a", "@TRANSCRIPT@": "t.txt"}) == "a.m4a -> t.txt")
check("every occurrence is filled, not just the first",
      P.render("@AUDIO@ @AUDIO@ @AUDIO@", {"@AUDIO@": "x"}) == "x x x")
check("a value that is itself a placeholder is not substituted again",
      P.render("@AUDIO@", {"@AUDIO@": "@TRANSCRIPT@", "@TRANSCRIPT@": "t.txt"})
      == "@TRANSCRIPT@",
      P.render("@AUDIO@", {"@AUDIO@": "@TRANSCRIPT@", "@TRANSCRIPT@": "t.txt"}))

plain = "A prompt that names no files at all.\n\nRead it and report.\n"
check("a template with no placeholders comes back unchanged",
      P.render(plain, {"@AUDIO@": "a", "@TRANSCRIPT@": "t"}) == plain)
check("an empty template stays empty",
      P.render("", {"@AUDIO@": "a"}) == "")
check("text around the placeholder is preserved exactly",
      P.render("@AUDIO@x@AUDIO@", {"@AUDIO@": ""}) == "x")


check.section("prompt.py run as the Makefile runs it")

TMP = Path(tempfile.mkdtemp(prefix="mn-prompt-"))
template = TMP / "template.md"
template.write_text("audio is @AUDIO@ and the transcript is @TRANSCRIPT@.\n")


def run_prompt(args, env_extra):
    env = dict(os.environ)
    env.pop("MN_AUDIO", None)
    env.pop("MN_TRANSCRIPT", None)
    env.update(env_extra)
    return subprocess.run([sys.executable, str(ROOT / "prompt.py")] + args,
                          cwd=ROOT, capture_output=True, text=True, env=env)


rendered = run_prompt([str(template)],
                      {"MN_AUDIO": NASTY, "MN_TRANSCRIPT": "output/t.txt"})
check("the rendered prompt goes to stdout",
      rendered.stdout == f"audio is {NASTY} and the transcript is output/t.txt.\n",
      rendered.stdout)
check("and rendering succeeds",
      rendered.returncode == 0, rendered.stderr)

missing = run_prompt([str(TMP / "not-here.md")], {"MN_AUDIO": "a"})
check("a missing template is refused",
      missing.returncode != 0, missing.returncode)
check("and is explained in a sentence rather than a traceback",
      "Traceback" not in missing.stderr and "not-here.md" in missing.stderr,
      missing.stderr)

unset = run_prompt([str(template)], {"MN_TRANSCRIPT": "output/t.txt"})
check("a placeholder with nothing to fill it is refused, not left blank",
      unset.returncode != 0 and "MN_AUDIO" in unset.stderr, unset.stderr)
check("and that too is a sentence, not a traceback",
      "Traceback" not in unset.stderr, unset.stderr)

noargs = run_prompt([], {})
check("being called with no template at all prints usage",
      noargs.returncode != 0 and "usage" in noargs.stderr.lower(), noargs.stderr)

bare = TMP / "bare.md"
bare.write_text("nothing to fill in\n")
bare_run = run_prompt([str(bare)], {})
check("a template with no placeholders needs no environment at all",
      bare_run.returncode == 0 and bare_run.stdout == "nothing to fill in\n",
      bare_run.stdout + bare_run.stderr)


# ── the Makefile ───────────────────────────────────────────────────────────────

if MAKE is None:
    check.skip("the Makefile keeps a filename inside one shell word", "no make")
else:
    check.section("a name with a space in it is one argument, not several")
    for target in TARGETS:
        out = expand(target, INPUT=SPACED)
        lines = logical_lines(out)
        toks = [words(l) for l in lines]
        check(f"{target} expands to lines a shell can parse",
              all(t is not None for t in toks),
              [l for l, t in zip(lines, toks) if t is None])
        flat = [w for t in toks if t for w in t]
        check(f"{target} never splits the recording's name",
              all(w not in ("local/my", "output/my", "recording.m4a")
                  and not w.startswith("recording.") for w in flat),
              [w for w in flat if w.startswith("recording.")
               or w in ("local/my", "output/my", "recording.m4a")])
        check(f"{target} still mentions the path, whole",
              any("my recording" in w for w in flat), flat)

    argv = [w for line in logical_lines(expand("transcribe", INPUT=SPACED))
            for w in (words(line) or [])]
    check("transcribe passes the recording as a single argv entry",
          SPACED in argv, argv)
    check("and its output stem as another",
          "output/my recording" in argv, argv)

    check.section("a name that looks like a command is still just a name")
    for target in TARGETS:
        lines = logical_lines(expand(target, INPUT=NASTY))
        toks = [words(l) for l in lines]
        check(f"{target} expands to lines a shell can parse",
              all(t is not None for t in toks),
              [l for l, t in zip(lines, toks) if t is None])
        flat = [w for t in toks if t for w in t]
        check(f"{target} leaves nothing that would run as a command",
              "id" not in flat and ";" not in flat, flat)
        # Every word that mentions the name at all holds the whole of the part
        # that was trying to break out, quotes and semicolons included.
        check(f"{target} keeps the escape attempt inside one word",
              [w for w in flat if "id" in w]
              and all("'; id; '" in w for w in flat if "id" in w),
              [w for w in flat if "id" in w])

    check.section("the analyze prompt is rendered, not executed")
    marker_input = "local/a'; echo MN_PWNED; '.m4a"
    seeded = expand("analyze", INPUT=marker_input, PROMPT=str(template),
                    CLAUDE="echo")
    claude_line = [l for l in logical_lines(seeded) if l.strip().startswith("echo ")]
    check("the recipe ends in one command that seeds Claude with the prompt",
          len(claude_line) == 1, claude_line)
    if claude_line:
        run = subprocess.run(["sh", "-c", claude_line[0]], cwd=ROOT,
                             capture_output=True, text=True)
        check("running it fills the recording's name into the prompt",
              marker_input in run.stdout, run.stdout + run.stderr)
        # If the name escaped, the `echo MN_PWNED` buried in it would have run
        # and printed a line of its own; inside the prompt it is just words.
        check("and the name inside it never becomes a command of its own",
              "MN_PWNED" not in [l.strip() for l in run.stdout.splitlines()],
              run.stdout)
        check("the transcript's name is filled in from the environment too",
              "output/a" in run.stdout, run.stdout)
    check("no sed script is left for a filename to escape from",
          "sed" not in seeded, seeded)

    check.section("check and readable follow the repair, not the original")
    stem = ROOT / "output" / "mn-prompt-f7"
    plain_t = Path(str(stem) + ".timestamped.txt")
    repaired_t = Path(str(stem) + ".repaired.timestamped.txt")
    try:
        plain_t.write_text("[00:00:00.00 --> 00:00:01.00]  hello\n")
        as_input = f"local/{stem.name}.m4a"
        before = expand("check", INPUT=as_input)
        check("with no repair yet, check verifies the plain transcript",
              str(plain_t.relative_to(ROOT)) in before
              and ".repaired." not in before, before)

        repaired_t.write_text("[00:00:00.00 --> 00:00:01.00]  hello\n")
        after = expand("check", INPUT=as_input)
        check("once a repair exists, check verifies the repaired transcript",
              str(repaired_t.relative_to(ROOT)) in after, after)
        readable_after = expand("readable", INPUT=as_input)
        check("and readable summarises the repaired transcript, not the old one",
              str(repaired_t.relative_to(ROOT)) in readable_after,
              readable_after)
        check("the summary is still named after the recording, not the repair",
              "'output/mn-prompt-f7.summary.md'" in readable_after,
              readable_after)
    finally:
        plain_t.unlink(missing_ok=True)
        repaired_t.unlink(missing_ok=True)

    check.section("the deliverables land where ls will show them")
    from_transcript = expand("readable", INPUT="",
                             TRANSCRIPT="output/2026-01-01.timestamped.txt")
    check("with no INPUT, the output stem comes from the transcript",
          "'output/2026-01-01.summary.md'" in from_transcript, from_transcript)
    check("so nothing is written to a hidden output/.summary.md",
          "output/.summary.md" not in from_transcript, from_transcript)
    spaced_t = expand("readable", INPUT="",
                      TRANSCRIPT="output/two  spaces.timestamped.txt")
    check("and taking the extension off does not rewrite the spacing",
          "'output/two  spaces.summary.md'" in spaced_t, spaced_t)
    for ext in [".timestamped.txt", ".txt", ".srt"]:
        e = expand("readable", INPUT="", TRANSCRIPT=f"output/2026-01-01{ext}")
        check(f"a {ext} transcript gives the same output stem",
              "'output/2026-01-01.readable.md'" in e, e)
    check("a bare output stem is refused rather than guessed at",
          "no output stem" in expand("readable", INPUT="", TRANSCRIPT=""),
          expand("readable", INPUT="", TRANSCRIPT=""))

    check.section("the summary survives a failed run")
    r = expand("readable", INPUT=SPACED)
    check("Claude writes to a temporary file, not onto the previous summary",
          "> 'output/my recording.summary.md.tmp'" in r, r)
    tested = r.find("test -s 'output/my recording.summary.md.tmp'")
    moved = r.find("mv 'output/my recording.summary.md.tmp'")
    check("which only becomes the summary once it has something in it",
          0 <= tested < moved, (tested, moved))
    check("the summary itself is never opened for writing before then",
          "> 'output/my recording.summary.md'" not in r, r)

    check.section("clean removes what this recording wrote")
    c = expand("clean", INPUT=SPACED)
    for suffix in [".txt", ".timestamped.txt", ".srt", ".summary.md",
                   ".readable.md"]:
        check(f"clean removes the {suffix} it wrote",
              f"'output/my recording{suffix}'" in c, c)
    check("and the repaired and backup files, whose names are globs",
          "'output/my recording'.repaired.*" in c
          and "'output/my recording'.*.bak" in c, c)
    check("nothing else in output/ is named",
          "find output" not in c, c)

    check.section("run for real, clean deletes this recording and no other")
    # Against a copy of the Makefile in a temporary directory: these run the
    # recipe rather than printing it, and the point of the checks is what gets
    # deleted, so they are kept well away from anyone's transcripts.
    yard = Path(tempfile.mkdtemp(prefix="mn-clean-"))
    shutil.copy(ROOT / "Makefile", yard / "Makefile")
    (yard / "output").mkdir()

    def make_in_yard(target, **variables):
        args = [MAKE, target] + [f"{k}={v}" for k, v in variables.items()]
        return subprocess.run(args, cwd=yard, capture_output=True, text=True)

    mine = "Bob's standup"
    wrote = [Path(yard, "output", mine + s) for s in
             (".txt", ".timestamped.txt", ".srt", ".summary.md", ".readable.md",
              ".repaired.timestamped.txt", ".timestamped.txt.bak")]
    for f in wrote:
        f.write_text("x")
    neighbour = Path(yard, "output", "someone else.timestamped.txt")
    neighbour.write_text("hours of decoding")

    apostrophe = make_in_yard("clean", INPUT=f"local/{mine}.m4a")
    check("a recording called Bob's standup is a filename, not a syntax error",
          apostrophe.returncode == 0, apostrophe.stdout + apostrophe.stderr)
    check("and every file it wrote is gone, summary and readable included",
          not any(f.exists() for f in wrote), [f.name for f in wrote if f.exists()])
    check("while another meeting's transcript is untouched", neighbour.exists())

    accented = make_in_yard("clean", INPUT="local/réunion d'équipe.m4a")
    check("an accented name is accepted too — the guard is not an ASCII rule",
          accented.returncode == 0, accented.stdout + accented.stderr)

    hostile_run = make_in_yard("clean", INPUT="local/x;id;.m4a")
    check("a name carrying a semicolon is refused outright",
          hostile_run.returncode != 0, hostile_run.stdout)
    check("and says so, rather than running it",
          "will not hand to a shell" in hostile_run.stdout, hostile_run.stdout)
    check("a name carrying a backtick is refused too",
          make_in_yard("clean", INPUT="local/x`id`.m4a").returncode != 0)
    check("as is one carrying a pipe",
          make_in_yard("clean", INPUT="local/x|id.m4a").returncode != 0)
    check("nothing was deleted on the way", neighbour.exists())
    shutil.rmtree(yard, ignore_errors=True)

    check.section("distclean asks before deleting every transcript there is")
    # Against a copy, because the real one would take the user's transcripts
    # with it if it were wrong — which is the whole point of the check.
    sandbox = Path(tempfile.mkdtemp(prefix="mn-distclean-"))
    shutil.copy(ROOT / "Makefile", sandbox / "Makefile")
    (sandbox / "output").mkdir()
    (sandbox / "output" / ".gitkeep").touch()
    keep = sandbox / "output" / "someone-elses-meeting.timestamped.txt"
    keep.write_text("hours of decoding\n")
    (sandbox / ".venv").mkdir()
    (sandbox / ".venv" / "marker").touch()

    def distclean(**variables):
        args = [MAKE, "distclean"] + [f"{k}={v}" for k, v in variables.items()]
        return subprocess.run(args, cwd=sandbox, capture_output=True, text=True)

    unconfirmed = distclean()
    check("an unconfirmed distclean refuses", unconfirmed.returncode != 0,
          unconfirmed.stdout)
    check("and says what it would have destroyed",
          "EVERY transcript" in unconfirmed.stdout, unconfirmed.stdout)
    check("and destroys nothing", keep.exists() and (sandbox / ".venv").exists())

    absolute = distclean(CONFIRM="1", VENV="/tmp/mn-not-a-venv")
    check("an absolute VENV is refused rather than removed",
          absolute.returncode != 0 and "refusing to rm -rf" in absolute.stdout,
          absolute.stdout)
    check("and that refusal happens before anything is deleted", keep.exists())

    confirmed = distclean(CONFIRM="1")
    check("CONFIRM=1 does go through", confirmed.returncode == 0,
          confirmed.stdout + confirmed.stderr)
    check("removing the venv", not (sandbox / ".venv").exists())
    check("and the transcripts", not keep.exists())
    check("while leaving output/ itself in place",
          (sandbox / "output" / ".gitkeep").exists())
    shutil.rmtree(sandbox, ignore_errors=True)

    check.section("a bare make explains itself instead of building")
    default = expand("")
    check("the default goal prints help",
          "make transcribe" in default and "make readable" in default, default)
    check("it installs nothing on the way",
          "setup.sh" not in default, default)
    check("and decodes nothing — it names transcribe.py without running it",
          ".venv/bin/python" not in default, default)
    for var in ["INPUT", "TRANSCRIPT", "ARGS", "FIX_ARGS", "WINDOWS", "GAPS",
                "DRY", "IN_PLACE", "NO_REPAIR", "PRINT", "NO_SUMMARY",
                "OUTPUT", "CONFIRM"]:
        check(f"help documents {var}", var in default, default)
    check("help warns that ARGS and FIX_ARGS replace rather than append",
          "replace rather than append" in default, default)

    check.section("the suites the test target runs")
    t = expand("test")
    for suite in ["test_transcribe.py", "test_repair.py", "test_readable.py",
                  "test_prompt.py", "test_diarize.py", "test_names.py",
                  "test_glossary.py"]:
        check(f"make test runs {suite}", suite in t, t)

shutil.rmtree(TMP, ignore_errors=True)
check.finish()
