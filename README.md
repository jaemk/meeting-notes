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
2. every *targeted* one is re-transcribed and spliced back in,
3. the result is scanned *again* and anything still outstanding is reported.

**Only the repetitions are targeted.** A loop, a stutter or a line of
boilerplate is text Whisper demonstrably got wrong, sitting in a window a few
seconds long — re-decoding it is minutes of work. Gaps are a different animal:
they are far more numerous, most of them are pauses the audio check could not
positively rule out, and running Whisper over near-silence is how you get
"Thanks for watching" where there was nothing. So gaps are *reported* and left
alone unless you pass `--include-gaps`.

On a 2½-hour meeting that is the difference between 12 decode windows (182s)
and 29 (391s).

Pass `--no-repair` to keep the raw output, `--repair-model` to re-decode
defective windows with a different (usually larger) model than the main run,
and `--repair-passes N` to change how many diagnose/repair rounds it does.

`--chunk-size/-c` governs both halves: it caps the whole-file chunks *and* the
slices a repair window is decoded in, so the repair pass can never hand Whisper
a longer stretch than the transcription itself was allowed. `make` uses `-c 1`
for both.

## What it looks for

| kind      | what it is                                                        | repaired          |
|-----------|-------------------------------------------------------------------|-------------------|
| `loop`    | the same line emitted once a second for 20+ seconds                | yes               |
| `stutter` | a phrase repeated 4+ times inside one segment                      | yes               |
| `canned`  | "Thanks for watching", "Subtitles by …" and friends                | yes               |
| `gap`     | 5+ seconds with **speech** underneath that produced no text        | `--include-gaps`  |
| `silence` | a gap with nothing but silence underneath — correct behaviour      | no                |
| `rewind`  | timestamps going backwards at a chunk seam                         | trimmed, no decode|

Gaps are classified by measuring the audio underneath them with `ffmpeg`, so a
pause in the conversation is not mistaken for dropped speech.

Rewinds are deleted, not re-decoded. Whisper does not stop where its audio
does: a chunk that ends mid-loop keeps emitting the same line for another 10–30
seconds, and merged as-is that tail sorts after the next chunk's opening so time
appears to run backwards. During transcription each chunk's segments are clamped
to the audio that chunk covered, so the tail never reaches the file. In a
transcript that already has one, `repair.py` does the same thing retroactively:
the tail is text a chunk invented past the end of its own audio, so dropping it
*is* the fix and it costs no decoding.

That trim needs the recording. Before deleting anything it confirms each seam
really is a chunk boundary by looking for the silence the split was cut at —
without that check a transcript whose timestamps are merely disordered would
have its real speech deleted instead. Given `verify` alone, or `--no-audio-check`,
rewinds are reported and left alone.

`--include-gaps` means the same thing wherever it appears, and the check and
the repair share it deliberately: `verify` fails on exactly what a `fix` would
have gone and re-decoded, so `fix` then `check` converges instead of forever
reporting gaps nothing was ever going to touch.

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
    make fix GAPS=1                         # repair dropped speech too

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

## Asking Claude to look at it

    make analyze                    interactive, seeded with the prompt
    make analyze PRINT=1            one-shot; prints its findings and exits
    make analyze PROMPT=<file>      ask something else entirely

`check` and `fix` apply rules. `analyze` is for the judgement calls they can't
make: whether a gap over loud audio is dropped speech or a round of applause,
whether a repaired window came back better or worse than what it replaced, which
of the remaining findings are worth spending compute on. It hands the transcript
to Claude Code along with `analyze.md` — the reasoning behind all of the above,
which side of a seam is lying and why, what each defect kind costs to repair,
and what not to do. `@AUDIO@` and `@TRANSCRIPT@` in that file are filled in with
whatever `INPUT`/`TRANSCRIPT` resolve to, so the prompt is worth reading and
editing directly; it is the part of this repo that encodes judgement rather than
rules.

Requires the `claude` CLI on `PATH` (`CLAUDE=` to point elsewhere).

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
