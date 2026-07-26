# Backend selection and setup

Two Whisper implementations, one of which only exists on some machines.

## BACKEND-1

`setup.sh` is the only place anything is installed. The Makefile decides when
to call it, never what it does.

## BACKEND-2

`openai-whisper` (CPU) is always installed. `mlx-whisper` is installed only on
Apple Silicon: mlx is Metal-only, so elsewhere it would either fail to build or
install a package that can never load.

## BACKEND-3

`--backend auto`, the default, picks mlx when the machine can run it and openai
otherwise.

## BACKEND-4

Asking for `--backend mlx` where it cannot run is an error, not a silent
fallback. A run that quietly used a different backend than requested is a run
whose output cannot be reasoned about.

## BACKEND-5

`./setup.sh --force` rebuilds the venv from scratch.

## BACKEND-6

Make targets depend on a setup stamp, so a fresh clone runs setup once and then
never again unless `setup.sh` itself changes.

## BACKEND-7

`setup.sh` checks its prerequisites before it installs anything, and fails with
a sentence naming the fix rather than letting them surface later:

- **Python 3.9–3.13.** Below the floor `openai-whisper` will not install; above
  the ceiling numba has no wheel and pip tries to compile it, minutes in.
  `PYTHON=<interpreter>` chooses the interpreter, `ALLOW_UNTESTED_PYTHON=1`
  waives the ceiling.
- **`ffmpeg` and `ffprobe` on `PATH`.** Every code path needs them — duration,
  silence detection, chunk and window extraction, gap measurement — so a
  missing binary is a failed setup, not a degraded mode. Without the check the
  first symptom is a `FileNotFoundError` partway into a multi-hour run.

## BACKEND-8

`setup.sh` takes one optional argument. An unrecognised one is an error, not a
silently non-`--force` run: `./setup.sh --froce` used to look like it had
rebuilt the venv.

## BACKEND-9

Setup installs code, never model weights. The weights are fetched on the first
decode that needs them, which is where the time and the gigabytes go; the setup
banner says so, because a first run otherwise appears to hang after
`Split into N chunks`.
