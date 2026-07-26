# File layout and naming

Where things live, and why a bare filename on the command line is enough.

## FILES-1

Recordings live in `local/`, everything written lands in `output/`. Both are
gitignored.

## FILES-2

A bare filename is looked up in the directory that kind of file belongs to, so
`transcribe.py 2026-07-25.m4a` finds `local/2026-07-25.m4a` and
`repair.py verify 2026-07-25.timestamped.txt` finds it in `output/`.

## FILES-3

Anything with a directory component, or that already exists as given, is used
untouched.

## FILES-4

The transcript keeps the recording's name: `local/2026-07-25.m4a` writes
`output/2026-07-25.*`. Dots inside a name are not treated as an extension, so
`team.sync.2026-07-25.m4a` keeps all of it.

## FILES-5

A transcription writes three files: `.txt`, `.timestamped.txt` and `.srt`.

## FILES-6

A repair writes `.repaired.*` beside them. `--in-place` overwrites the source
transcript instead and saves a `.bak` first — of the immediately previous state
only.

## FILES-7

`--output` overrides the stem; `make clean` removes only this recording's
outputs and leaves the rest of `output/` alone.

## FILES-8

No recording and no transcript ever reaches the repo — not as a fixture, not as
an example in documentation, not quoted in a code comment.
