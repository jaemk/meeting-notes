# meeting-notes

Whisper transcription that cleans up after itself. Long recordings are split at
silence boundaries to avoid Whisper's repetition bug, and whatever gets through
anyway is found and re-transcribed automatically before you ever see it.

## Setup

    ./setup.sh          # or: make setup

`setup.sh` is the only place anything is installed. It creates `.venv`, always
installs `openai-whisper` (CPU), and installs `mlx-whisper` **only on Apple
Silicon** — mlx is Metal-only, so on Intel Macs and Linux it would either fail
to build or install a package that can never load. The backend follows suit:
`--backend auto` (the default) picks mlx when this machine can run it and
openai otherwise. Asking for `--backend mlx` where it cannot run is an error
rather than a silent fallback.

`./setup.sh --force` rebuilds the venv from scratch.

## Transcribing

    make transcribe INPUT=recording.m4a

or directly:

    .venv/bin/python transcribe.py recording.m4a
    .venv/bin/python transcribe.py recording.m4a --model large-v3 --language en
    .venv/bin/python transcribe.py recording.m4a --backend openai --model small

Writes `<output>.txt`, `<output>.timestamped.txt` and `<output>.srt`.

Every run finishes with an automatic **diagnose → repair → verify** pass:

1. the fresh transcript is scanned for defects,
2. every repairable one is re-transcribed and spliced back in,
3. the result is scanned *again* and anything still outstanding is reported.

Pass `--no-repair` to keep the raw output, `--repair-model` to re-decode
defective windows with a different (usually larger) model than the main run,
and `--repair-passes N` to change how many diagnose/repair rounds it does.

## What it looks for

| kind      | what it is                                                        | repaired |
|-----------|-------------------------------------------------------------------|----------|
| `loop`    | the same line emitted once a second for 20+ seconds                | yes      |
| `stutter` | a phrase repeated 4+ times inside one segment                      | yes      |
| `canned`  | "Thanks for watching", "Subtitles by …" and friends                | yes      |
| `gap`     | 5+ seconds with **speech** underneath that produced no text        | yes      |
| `silence` | a gap with nothing but silence underneath — correct behaviour      | no       |
| `rewind`  | timestamps going backwards at a chunk seam                         | no       |

Gaps are classified by measuring the audio underneath them with `ffmpeg`, so a
pause in the conversation is not mistaken for dropped speech.

None of this is visible in the `.txt` output — you only see it in the
timestamps, which is why the check runs on its own.

## Repairing a transcript you already have

`repair.py` runs the same cycle against an existing transcript.

    # report only, exits nonzero if anything is wrong
    .venv/bin/python repair.py diagnose recording.m4a transcript.timestamped.txt

    # find and fix everything -> transcript.repaired.{txt,timestamped.txt,srt}
    .venv/bin/python repair.py repair recording.m4a transcript.timestamped.txt

    # re-check a transcript; exit status is the pass/fail gate
    .venv/bin/python repair.py verify transcript.repaired.timestamped.txt

Or via make:

    make check                       # verify $(TRANSCRIPT)
    make fix INPUT=recording.m4a     # repair everything it finds
    make fix DRY=1                   # preview, decode nothing
    make fix IN_PLACE=1              # overwrite the transcript, keeps a .bak
    make fix WINDOWS="-w 20:47-21:09 -w 1:49:54-1:50:21"

With `-w` only those stretches are re-decoded and detection is skipped for
window selection; without it the windows come from the diagnosis. Either way
it is the same splice-and-recheck code path.

Notes:

- Windows accept `SS`, `MM:SS` or `HH:MM:SS`, and `-w` is repeatable.
- Windows are widened to whole segment boundaries so a segment straddling the
  edge is never cut in half.
- `--pad` seconds (default 15) of surrounding audio are decoded for context and
  then discarded, so the splice stays inside the window.
- Conditioning on previous text is **off** inside a window — that feedback loop
  is what causes the repetitions in the first place.
- A window that comes back still broken is retried with double the context and
  then with `--fallback-model`. `--strict` refuses to splice anything that does
  not come back completely clean.

## Tests

    make test

`test_transcribe.py` and `test_repair.py` share the harness and fixture paths in
`testlib.py`. Everything decode-related is stubbed, so the suite runs in
seconds; the few checks that need the real audio in `local/` skip if it is
absent.
