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
`--no-timestamps` writes the `.txt` alone — which also gives up the only view
the defects live in, since none of them are visible in the prose.

## FILES-6

A repair writes `.repaired.*` beside them. `--in-place` overwrites the source
transcript instead and saves a `.bak` first — of the immediately previous state
only.

## FILES-7

`--output` overrides the stem; `make clean` removes only this recording's
outputs and leaves the rest of `output/` alone. "This recording's outputs" is
every file the pipeline derives from it: `.txt`, `.timestamped.txt`, `.srt`,
`.repaired.*`, `.bak`, `.summary.md` and `.readable.md`. A `clean` that leaves
some of them behind is worse than none, because the next run assembles a
document from a stale summary.

## FILES-8

No recording and no transcript ever reaches the repo — not as a fixture, not as
an example in documentation, not quoted in a code comment.

## FILES-9

The ignore rules match by content type as well as by directory. `local/*` and
`output/*` cover where the tools write; `*.timestamped.txt`, `*.srt`,
`*.readable.md`, `*.summary.md`, `*.repaired.*` and `*.bak` cover what the
files *are*, so a transcript copied or written somewhere else is still not
committable. The two are deliberately redundant: `FILES-8` is the property that
matters, and a single directory rule is one `--output` away from being wrong.

## FILES-10

`make distclean` deletes the venv and everything in `output/` — every
transcript, not just this recording's — so it requires an explicit `CONFIRM=1`.
Nothing else in the Makefile is destructive beyond one recording.
