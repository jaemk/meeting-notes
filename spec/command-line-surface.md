# Command-line surface

What the two CLIs and the Makefile accept, what they reject, and what they
confirm before doing something expensive or destructive. A decode costs
minutes to hours, so an argument that is wrong needs to be caught in the
first second rather than discovered in the output.

**Status: pending.** `CLI-3`, `CLI-4` and `CLI-6` describe behaviour landing
with the change this file was written for; `CLI-1`, `CLI-2` and `CLI-5` already
hold.

## CLI-1

`ARGS` (for `make transcribe`) and `FIX_ARGS` (for `make fix`) carry the model,
language and chunk size. Both are `?=` defaults, so setting either **replaces**
the whole string rather than adding to it. `make fix FIX_ARGS="--strict"`
therefore discards `-c 1` and drops the repair back to 5-minute slices — the
long-decode condition the chunking exists to avoid, in the one place Whisper
has already demonstrably looped. Any documentation of these variables states
the replacement semantics; anything that must survive is restated in full.

## CLI-2

Everything that selects *what* to work on is its own variable — `INPUT`,
`TRANSCRIPT`, `WINDOWS`, `GAPS`, `DRY`, `IN_PLACE`, `PROMPT`, `SUMMARY_PROMPT`
— so the common cases never require rewriting `ARGS`/`FIX_ARGS` and cannot lose
`-c 1` by accident.

## CLI-3

Numeric arguments are validated by the parser, before anything is read,
measured or decoded, and the message names the flag and the bound it broke.
A `--chunk-size 0`, a negative `--pad` or a `--passes 0` is a run that either
never terminates, decodes nothing, or silently does no work — all of which cost
the user the discovery time of a real run.

## CLI-4

Every option has help text. A flag that appears in `--help` with no
explanation, such as `repair.py`'s `--model` and `--language` did, is
indistinguishable from one that is unsafe to touch.

## CLI-5

The same setting keeps the same name and default across both CLIs where it
exists in both: `--chunk-size/-c`, `--model`, `--language`, `--backend`,
`--strict`, `--include-gaps`, `--fallback-model`. The one deliberate exception
is `transcribe.py --repair-passes` against `repair.py --passes` (`AUTO-9`),
which are the same knob named for their context.

## CLI-6

`make help` lists every target and the variables it takes, from the Makefile
itself, so the list cannot fall behind the targets it documents.

## CLI-7

A target that destroys more than one recording's output asks first. `make
distclean` requires `CONFIRM=1` (`FILES-10`); `make clean` does not, because it
is scoped to the recording named by `INPUT`.
