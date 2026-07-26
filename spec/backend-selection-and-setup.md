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
