# Quick transcription (mlx GPU, base model)
.venv/bin/python transcribe.py beach.mp3

# Best accuracy
.venv/bin/python transcribe.py beach.mp3 --model large-v3

# With timestamps + SRT subtitles
.venv/bin/python transcribe.py beach.mp3 --model small --timestamps

# Force CPU if needed
.venv/bin/python transcribe.py beach.mp3 --backend openai --model medium


## Repairing a bad window

Whisper sometimes falls into a repetition loop — the same line emitted once a
second for 20+ seconds. Re-transcribe just that stretch and splice it back in
instead of redoing the whole file.

Find loops in an existing transcript:

    .venv/bin/python -c "import transcribe as t; \
      [print(c,'x',repr(s)) for _,c,s in t.find_repeats(t.load_timestamped('transcript.timestamped.txt'))]"

Preview what a repair would replace (no transcription, nothing written):

    .venv/bin/python transcribe.py beach.m4a --merge transcript.timestamped.txt \
        -w 1:49:54-1:50:21 --dry-run

Repair one or more windows — writes transcript.fixed.{txt,timestamped.txt,srt}:

    .venv/bin/python transcribe.py beach.m4a --merge transcript.timestamped.txt \
        -w 20:47-21:09 -w 1:49:54-1:50:21 --model large-v2 -l en

Add `--in-place` to overwrite the source transcript (a `.bak` is saved first).

Notes:
- Windows accept `SS`, `MM:SS` or `HH:MM:SS`, and `-w` is repeatable.
- Windows are widened to whole segment boundaries so a segment straddling the
  edge is never cut in half (`--no-snap` to disable).
- `--pad` seconds (default 15) of surrounding audio are decoded for context and
  then discarded, so the splice stays inside the window.
- Conditioning on previous text is **off** inside a window — that feedback is
  what causes the loops. `--condition-on-previous` re-enables it.
- The new output is re-checked for loops and warns if it looped again; try a
  different `--model` or a slightly different window if so.

Or via make:

    make fix WINDOWS="-w 20:47-21:09 -w 1:49:54-1:50:21"
    make fix WINDOWS="-w 20:47-21:09" DRY=1
    make test
