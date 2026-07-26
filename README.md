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

## Where files live

    local/      recordings go here          (gitignored)
    output/     everything written lands here (gitignored)

Both directories are ignored, so no recording and no transcript ever reaches the
repo. A bare filename on the command line is looked up in the directory that
kind of file belongs to, so `transcribe.py 2026-07-25.m4a` finds
`local/2026-07-25.m4a` and `repair.py verify 2026-07-25.timestamped.txt` finds
it in `output/`. Anything with a directory component is used as given.

**The transcript keeps the recording's name.** `local/2026-07-25.m4a` writes
`output/2026-07-25.txt`, `output/2026-07-25.timestamped.txt` and
`output/2026-07-25.srt`; a repair pass adds `output/2026-07-25.repaired.*`.
Pass `--output` to override the stem.

## Transcribing

    make transcribe INPUT=local/2026-07-25.m4a

With no `INPUT`, make picks up `local/input.*`.

Or directly:

    .venv/bin/python transcribe.py 2026-07-25.m4a
    .venv/bin/python transcribe.py 2026-07-25.m4a --model large-v3 --language en
    .venv/bin/python transcribe.py 2026-07-25.m4a --backend openai --model small

Every run finishes with an automatic **diagnose → repair → verify** pass:

1. the fresh transcript is scanned for defects,
2. every repairable one is re-transcribed and spliced back in,
3. the result is scanned *again* and anything still outstanding is reported.

Pass `--no-repair` to keep the raw output, `--repair-model` to re-decode
defective windows with a different (usually larger) model than the main run,
and `--repair-passes N` to change how many diagnose/repair rounds it does.

`--chunk-size/-c` governs both halves: it caps the whole-file chunks *and* the
slices a repair window is decoded in, so the repair pass can never hand Whisper
a longer stretch than the transcription itself was allowed. `make` uses `-c 1`
for both.

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
    .venv/bin/python repair.py diagnose 2026-07-25.m4a 2026-07-25.timestamped.txt

    # find and fix everything -> output/2026-07-25.repaired.{txt,timestamped.txt,srt}
    .venv/bin/python repair.py repair 2026-07-25.m4a 2026-07-25.timestamped.txt

    # re-check a transcript; exit status is the pass/fail gate
    .venv/bin/python repair.py verify 2026-07-25.repaired.timestamped.txt

Or via make, where `INPUT` picks the transcript for you:

    make check INPUT=local/2026-07-25.m4a   # verify output/2026-07-25.timestamped.txt
    make fix   INPUT=local/2026-07-25.m4a   # repair everything it finds
    make fix DRY=1                          # preview, decode nothing
    make fix IN_PLACE=1                     # overwrite the transcript, keeps a .bak
    make fix WINDOWS="-w 20:47-21:09 -w 1:49:54-1:50:21"

`TRANSCRIPT=<file>` overrides that choice, and `make clean` removes just this
recording's outputs, leaving the rest of `output/` alone.

With `-w` only those stretches are re-decoded and detection is skipped for
window selection; without it the windows come from the diagnosis. Either way
it is the same splice-and-recheck code path.

Notes:

- Windows accept `SS`, `MM:SS` or `HH:MM:SS`, and `-w` is repeatable.
- Windows are widened to whole segment boundaries so a segment straddling the
  edge is never cut in half.
- A window longer than `--chunk-size` is decoded in slices cut at silence, the
  same way a whole file is chunked — one long decode is what makes Whisper loop
  in the first place, and a repair window is somewhere it already has. Slices
  are cut hard at the seam and padded only at the window's outer edges, so
  neither slice re-transcribes the other's speech.
- `--pad` seconds (default 15) of surrounding audio are decoded for context and
  then discarded, so the splice stays inside the window.
- Conditioning on previous text is **off** inside a window — that feedback loop
  is what causes the repetitions in the first place.
- A window that comes back still broken is retried with double the context and
  then with `--fallback-model`. `--strict` refuses to splice anything that does
  not come back completely clean.

## Tests

    make test

`test_transcribe.py` and `test_repair.py` share the harness in `testlib.py`,
which also builds both fixtures into `output/`: a synthetic transcript with a
known loop, rewind and gap planted in neutral filler, and thirty seconds of
ffmpeg-generated tone/silence for the gap classifier. Nothing depends on a
recording, so a fresh clone runs the whole suite — and every number the tests
assert is a property of the generator rather than of somebody's meeting.

Decoding is stubbed throughout, so it finishes in seconds. The only thing that
can skip is the audio-backed gap classification, if `ffmpeg` is not installed.
