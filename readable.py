#!/usr/bin/env python3
"""
Turn a timestamped transcript into a document a person can read.

The .txt a transcription writes is one unbroken run of words — correct, and
unusable. This breaks it where the room went quiet, timestamps each paragraph
so a passage can be found in the recording, and optionally opens with a summary
written by Claude (see summarize.md and `make readable`).

  ./readable.py 2026-07-25.timestamped.txt
  ./readable.py 2026-07-25.timestamped.txt --summary output/2026-07-25.summary.md
  ./readable.py 2026-07-25.timestamped.txt --speakers
  ./readable.py 2026-07-25.timestamped.txt --speakers --transcript-only

Transcripts are looked up in output/ and the result is written beside them.

--transcript-only prints the paragraphed transcript to stdout and nothing else.
It exists so `make readable` can summarise the document it is about to build
rather than the raw transcript underneath it: same paragraphs, same speaker
labels, same `[H:MM:SS]` anchors, so the summary's cross-references land on
headings that exist.

With --speakers, paragraphs additionally break where the speaker changes and
carry a cluster label. It is off by default and silently unavailable without a
sidecar, so the deliverable never depends on the optional diarization install.
"""

import argparse
import os
import sys
from pathlib import Path

import transcribe as T

# A pause this long reads as the end of a thought. Shorter than the gap
# detector's threshold on purpose: this is about where a paragraph wants to
# break, not about whether speech went missing.
PARAGRAPH_PAUSE = 2.0
# And a paragraph ends here regardless, so an unbroken monologue still arrives
# in readable pieces.
PARAGRAPH_WORDS = 110


def fmt_clock(seconds):
    """H:MM:SS — hours unpadded, because these are read, not sorted."""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def document_title(stem):
    """
    The recording's name, without the pipeline's fingerprints. A repaired
    transcript is still a transcript of the same meeting, and '.repaired' in
    the heading tells the reader nothing they want to know.
    """
    name = Path(stem).name
    return name[: -len(".repaired")] if name.endswith(".repaired") else name


def paragraphs(segments, pause=PARAGRAPH_PAUSE, max_words=PARAGRAPH_WORDS,
               labels=None):
    """
    Group segments into (start, text, label) paragraphs, breaking at silence.

    Without `labels`, speakers are not marked — Whisper does not diarize — so
    a break at a pause is the closest thing to a turn boundary available. It
    lands on one often, because people pause when they hand off, but never
    assume it did. `label` is None in that case.

    `labels` is a speaker label per segment, as `diarize.speaker_labels`
    builds it. Given one, a paragraph also breaks wherever the label changes,
    which is a real turn boundary rather than an approximation of one. The
    pause and word-count breaks still apply inside a single speaker's run, so
    a long monologue still arrives in readable pieces.

    Assumes `segments` is given in the order the transcript should read —
    this walks it once and never sorts. A transcript still carrying rewinds
    (see CLAUDE.md — `repair.py repair` leaves them alone when it wasn't
    given the audio) will not raise here: a backwards jump just fails the
    `silent >= pause` test and the two stretches land in one paragraph
    rather than being split apart. Repair the transcript first if that
    matters; this function only paragraphs what it is handed.
    """
    out, current, start = [], [], None
    previous_end = None
    words = 0
    label = None
    for i, seg in enumerate(segments):
        text = seg["text"].strip()
        if not text:
            continue
        this_label = labels[i] if labels else None
        if current:
            silent = seg["start"] - previous_end
            if silent >= pause or words >= max_words or this_label != label:
                out.append((start, " ".join(current), label))
                current = []
                words = 0
        if not current:
            start = seg["start"]
            label = this_label
        current.append(text)
        words += len(text.split())
        previous_end = seg["end"]
    if current:
        out.append((start, " ".join(current), label))
    return out


def transcript_lines(paras):
    """
    The paragraph lines themselves, with no heading, summary or explanatory
    note around them.

    This is what the reader reads *and* what the summariser is given. It is one
    function rather than two so those two can never drift: the `[H:MM:SS]`
    anchors a summary cites are the anchors the document actually carries, and
    a speaker label the summariser attributes a decision to is the label
    printed beside that decision below it.
    """
    lines = []
    for para in paras:
        # Paragraphs are (start, text) or (start, text, label). Both are
        # accepted so a caller passing its own list keeps working.
        start, body = para[0], para[1]
        label = para[2] if len(para) > 2 else None
        prefix = f"**[{fmt_clock(start)}]**"
        lines += [f"{prefix} {label} — {body}" if label else f"{prefix} {body}",
                  ""]
    return lines


def write_piped(text, stream=None):
    """
    Write to stdout, tolerating a reader that stops early.

    `--transcript-only` exists to be piped, and a pipe can close before a
    150-minute transcript has finished arriving — `| head` while looking at it,
    or a summariser that dies on its first read. The OS raises EPIPE, Python
    raises BrokenPipeError, and a traceback about a broken pipe is noise: the
    reader got what it asked for and left.

    Pointing the file descriptor at devnull is what keeps it quiet. Catching
    the exception is not enough on its own — the interpreter flushes stdout
    again on the way out, and that second flush fails too, printing
    "Exception ignored in: <_io.TextIOWrapper name='<stdout>'>" after main()
    has already returned cleanly.
    """
    stream = stream or sys.stdout
    try:
        stream.write(text)
        stream.flush()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, stream.fileno())
        raise SystemExit(0)


def render(segments, title, summary=None, paras=None, corrections=None):
    """The whole document: heading, what it is, the summary, the transcript."""
    words = sum(len(s["text"].split()) for s in segments)
    # Not segments[-1]["end"]: a transcript with an unrepaired rewind (see
    # `paragraphs` above) does not end at its highest timestamp, so the
    # running time has to be the max over every segment, not the last one.
    running = max(s["end"] for s in segments)
    lines = [f"# Meeting transcript — {title}", "",
             f"{len(segments):,} segments · {words:,} words · "
             f"{fmt_clock(running)} running time", ""]

    if paras is None:
        paras = paragraphs(segments)
    labelled = any(len(p) > 2 and p[2] for p in paras)
    # A name renders as "Robin (Speaker 7)", so a bracket after a label is
    # what distinguishes a named document from a numbered one.
    named = any(len(p) > 2 and p[2] and "(Speaker " in p[2] for p in paras)

    if summary:
        if named:
            caveat = " and speaker names are inferred from what was said"
        elif labelled:
            caveat = " and speaker labels are acoustic clusters, not names"
        else:
            caveat = " and speakers are not labelled"
        lines += [summary.strip(), "",
                  "*Summary written by Claude from the transcript below. The "
                  "transcript is machine-generated" + caveat
                  + " — check anything that matters against the recording.*",
                  ""]

    lines += ["---", "", "## Full transcript", ""]
    if labelled:
        note = ("*Voices are separated by "
                "`pyannote/speaker-diarization-3.1`, which tells two speakers "
                "apart without knowing who either one is. A paragraph listing "
                "more than one speaker holds words from each of them — what "
                "is unknown is where one stops and the next starts, not who "
                "was there.")
        if named:
            note += (" Names in brackets were inferred from the transcript's "
                     "own words — someone introducing themselves, or being "
                     "addressed — and are best-effort: the cluster number is "
                     "kept beside each one so a wrong name can be traced, and "
                     "voices the transcript never names stay numbered.*")
        else:
            note += (" Labels are cluster numbers, not names: which person "
                     "each one is is not established here.*")
        lines += [note, ""]

    # Said out loud, and naming every word changed. A correction the reader
    # cannot see is a claim about the recording they have no way to check —
    # and the transcript files still hold the decoder's spelling, so anyone
    # comparing the two deserves to know why they differ.
    if corrections:
        listed = ", ".join(f"**{k}** (×{n})" for k, n in
                           sorted(corrections.items(),
                                  key=lambda kv: (-kv[1], kv[0])))
        lines += [f"*Spellings corrected from a glossary: {listed}. The "
                  f"decoder wrote these phonetically; the transcript files "
                  f"beside this document still carry its original spelling.*",
                  ""]

    lines += transcript_lines(paras)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Format a transcript as readable markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s audio.timestamped.txt
  %(prog)s audio.timestamped.txt --summary output/audio.summary.md
  %(prog)s audio.timestamped.txt --speakers
  %(prog)s audio.timestamped.txt -o output/somewhere-else.md

`make readable` runs this with a summary generated by Claude first.
""")
    ap.add_argument("transcript")
    ap.add_argument("--summary", default=None,
                    help="Markdown file to open the document with")
    ap.add_argument("--title", default=None, help="Defaults to the file's stem")
    ap.add_argument("--output", "-o", default=None,
                    help="Defaults to <stem>.readable.md beside the transcript")
    ap.add_argument("--speakers", nargs="?", const=True, default=None,
                    metavar="SIDECAR",
                    help="Mark speaker changes from a diarization sidecar. "
                         "Bare, it looks for <stem>.speakers.json; with a "
                         "path, it uses that. Run ./diarize.py run first.")
    ap.add_argument("--names", nargs="?", const=True, default=None,
                    metavar="SIDECAR",
                    help="Also put names to the clusters, from a names "
                         "sidecar (see names.py). Implies --speakers. Bare, "
                         "it looks for <stem>.names.json.")
    ap.add_argument("--glossary", nargs="?", const=True, default=None,
                    metavar="FILE",
                    help="Correct proper nouns the decoder spelled "
                         "phonetically, from a glossary (see glossary.py). "
                         "Bare, it looks for <stem>.glossary.txt then "
                         "local/glossary.txt. Applies to the rendered "
                         "document only — the transcript files are left as "
                         "the decoder wrote them.")
    ap.add_argument("--transcript-only", action="store_true",
                    help="Print just the paragraphed transcript to stdout — "
                         "no heading, no summary, no notes. This is what "
                         "`make readable` pipes into Claude to summarise, so "
                         "the summary is written from the same labels and the "
                         "same timestamps the reader sees.")
    args = ap.parse_args()

    # --summary asks to put a summary in; --transcript-only asks to leave
    # everything but the transcript out. Together they are a slip, not a
    # configuration, and silently honouring one would hide the other.
    if args.transcript_only and args.summary:
        sys.exit("--transcript-only writes no document, so --summary has "
                 "nothing to open. Drop one of them.")

    path = T.resolve_transcript(args.transcript)
    if not path.exists():
        sys.exit(f"No transcript at {path}")
    try:
        segments = T.load_timestamped(path)
    except ValueError as e:
        sys.exit(f"Can't read {path}: {e}")
    if not segments:
        sys.exit(f"{path} has no segments")

    summary = None
    if args.summary:
        # Same lookup as the transcript itself, so a bare name finds it
        # beside the transcript in output/ instead of only in the cwd.
        summary_path = T.resolve_transcript(args.summary)
        if not summary_path.exists():
            sys.exit(f"No summary at {summary_path}")
        summary = summary_path.read_text().strip()
        if not summary:
            sys.exit(f"{summary_path} is empty — the summary step produced nothing")

    stem = T.output_stem(path)
    title = args.title or document_title(stem)

    labels = None
    # Naming clusters is meaningless without the clusters, so --names turns
    # --speakers on rather than failing on a combination the user plainly
    # meant.
    if args.names and not args.speakers:
        args.speakers = True
    if args.speakers:
        # Imported here, not at module scope: diarize.py imports this file, so
        # a top-level import would be circular, and readable.py must keep
        # working in a venv that never installed the optional diarization.
        import diarize as D
        if args.speakers is True:
            sidecar, tried = D.find_sidecar(stem)
            if sidecar is None:
                looked = "\n".join(f"  {c}" for c in tried)
                sys.exit(f"No speaker sidecar. Looked for:\n{looked}\n"
                         f"Run it first:  ./diarize.py run <audio>")
        else:
            sidecar = T.resolve_output(args.speakers)
            if not sidecar.exists():
                sys.exit(f"No speaker sidecar at {sidecar}")
        try:
            turns = D.load_turns(sidecar)
        except ValueError as e:
            sys.exit(f"Can't read {sidecar}: {e}")

        names = None
        if args.names:
            import names as N
            if args.names is True:
                names_file, tried = D.find_sidecar(stem, ".names.json")
                if names_file is None:
                    looked = "\n".join(f"  {c}" for c in tried)
                    sys.exit(f"No names sidecar. Looked for:\n{looked}\n"
                             f"Build one first:  make names INPUT=<audio>")
            else:
                names_file = T.resolve_output(args.names)
                if not names_file.exists():
                    sys.exit(f"No names sidecar at {names_file}")
            try:
                names = N.load_names(names_file)
            except ValueError as e:
                sys.exit(f"Can't read {names_file}: {e}")

        labels = D.speaker_labels(segments, turns, names=names)

    paras = paragraphs(segments, labels=labels)

    # Applied to the paragraphs, which is the one place both outputs come
    # from: the document below and the `--transcript-only` text the summariser
    # reads. Correcting here rather than in each of them separately is what
    # stops the summary and the transcript under it spelling a name two ways.
    corrections = {}
    if args.glossary:
        import glossary as G
        if args.glossary is True:
            gpath = G.find(stem)
            if gpath is None:
                looked = "\n".join(
                    f"  {c}" for c in
                    [f"{stem}.glossary.txt", *G.DEFAULT_NAMES])
                sys.exit(f"No glossary. Looked for:\n{looked}\n"
                         f"Write one, or name it with --glossary FILE.")
        else:
            # Used as given, unlike --speakers and --names. Those name files
            # the pipeline generated, so resolving them into output/ is a
            # convenience; a glossary is a file the user wrote, living
            # wherever they keep it (local/, by default, because it is full of
            # real names). T.resolve_output would also strip the `.txt` off
            # it, since it exists to turn a name into a stem.
            gpath = Path(args.glossary)
            if not gpath.exists():
                sys.exit(f"No glossary at {gpath}")
        try:
            rules = G.load(gpath)
        except G.GlossaryError as e:
            sys.exit(f"Refusing this glossary: {e}")
        fixed = []
        for para in paras:
            body, counts = G.apply(para[1], rules)
            for k, n in counts.items():
                corrections[k] = corrections.get(k, 0) + n
            label = para[2] if len(para) > 2 else None
            if label:
                # Labels carry names too, and a name put to a cluster comes
                # from the same mis-decoded text the body does.
                label, lcounts = G.apply(label, rules)
                for k, n in lcounts.items():
                    corrections[k] = corrections.get(k, 0) + n
            fixed.append((para[0], body, label))
        paras = fixed

    # Straight to stdout so the caller can pipe it into the summariser without
    # an intermediate file to write, name, clean up or leave stale. Nothing
    # else is printed on this path for the same reason — the progress line
    # below would land in the middle of the transcript.
    if args.transcript_only:
        write_piped("\n".join(transcript_lines(paras)))
        return

    # Same rule as everything else this repo writes: a bare name lands in
    # output/, a path with a directory in it is used as given.
    out = T.resolve_output(args.output) if args.output else Path(f"{stem}.readable.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(segments, title, summary, paras=paras,
                          corrections=corrections))

    print(f"Saved: {out}  ({len(paras)} paragraphs"
          f"{', with summary' if summary else ', no summary'}"
          f"{', with speakers' if labels else ''})")
    if args.glossary:
        import glossary as G
        print(f"  {G.summarise(corrections)}")


if __name__ == "__main__":
    main()
