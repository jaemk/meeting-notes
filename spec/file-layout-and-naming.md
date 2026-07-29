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

## FILES-11

There are two kinds of `--output` and they resolve differently.

`transcribe.py --output` and `repair.py -o` name a **stem**, which `save_output`
appends `.txt`, `.timestamped.txt` and `.srt` to. A transcript extension typed
on such a name is stripped, so `-o notes.timestamped.txt` writes
`notes.timestamped.txt` and not `notes.timestamped.txt.timestamped.txt`.

The `--output` of `readable.py`, `diarize.py` and `names.py` names a **file**:
one document, whose name the user chose. It keeps its extension exactly as
given, and a bare name still resolves into `output/` under `FILES-1` and is
still warned about when it lands somewhere inside the repo that git would commit
(`FILES-9`). Stripping here would rename the deliverable — `-o notes.txt` would
write `notes`, which the next stage's bare-name lookup no longer finds.

They are two resolvers rather than one with a mode flag, so that every caller
has to say which kind of name its flag takes. A shared resolver defaulting to
one of the two behaviours is how the wrong one gets picked up silently.

## FILES-12

A stem carries **one generation** of backup, and the repair that would replace
it is refused rather than allowed to.

`--in-place` copies each file it rewrites to `<file>.bak`, and that copy is
written unconditionally — so a second in-place repair of the same stem puts the
*first repair's output* where the original decode was, and reports it as
"Backed up original" while doing so. This qualifies `FILES-6` rather than
amending it: the `.bak` is still the immediately previous state only, and the
run that would overwrite it now stops first. `--replace-backup` is how you say
the older copy is not wanted, and a run that uses it names the backups it
replaced — the failure here is not the overwrite, it is the silence around it
(`COST-8`).

The refusal happens before the transcript is even loaded, so no decode is spent
on the way to it, and it names the `.bak` files that stopped it, the `--output`
stem that repairs without touching them, and the flag that overrides it. A
`.bak` whose own file is gone does not count: nothing would have been copied
over it.

Three other resolutions were considered and refused:

- **Numbered generations** (`.bak.1`, `.bak.2`) lose no data, and break two
  rules to do it. Neither `.gitignore`'s `*.bak` nor `make clean`'s
  `$(OUTPUT).*.bak` matches such a name, so every extra generation is a
  committable transcript (`FILES-8`, `FILES-9`) that a `clean` leaves behind
  (`FILES-7`). They also accumulate in `output/` with nothing to remove them.
- **Refusing only where the `.bak` would be overwritten by repaired content.**
  A repair that finds nothing writes a file identical to the one it read, so
  whether a rendering has been repaired cannot be recovered from its bytes.
  That rule would permit and refuse unpredictably, which is worse than either.
- **Documenting the loss instead of preventing it**, i.e. making `FILES-6`'s
  "immediately previous state only" louder at the point of use. The loss is
  silent, irreversible, and one keystroke from the command that created the
  file it destroys. Help text is read once; the command gets typed twice.

## FILES-13

`--in-place` and `--output` name different files and cannot be combined. Given
both, the repair wrote to the `--output` stem while the backup was taken of the
source transcript: three files copied that nothing was about to overwrite, and
three overwritten with nothing to restore them from — each half correct on its
own, which is why nothing objected.

The refusal is an explicit check rather than an argparse mutually-exclusive
group. Argparse would say "argument --output/-o: not allowed with argument
--in-place", which names the flags and stops there; the message here says what
each of them does to which file, because a user who typed both believed
something about them that is worth correcting. Every other refusal in this repo
is written the same way, for the same reason.

## FILES-14

A `--output` that does not name a file is refused where it was typed, not where
it fails.

Four values reach the file resolver looking like names and are not: `""` and
`"."`, which `Path` treats alike and which join onto `output/` as `output/`
itself; anything ending in `/`, which names a directory; and a bare `".."`,
which is the dangerous one — it has no directory component, so it takes the
bare-name branch and becomes `output/..`, i.e. the repo root, without passing
the `warn_if_committable` check (`FILES-9`) that every other escape from
`output/` goes through. This is the trap the Makefile's `need_output` guard
already refuses a *stem* for ("a bare `output/` would quietly write the
deliverables to `output/.summary.md`, paid for and invisible to `ls`"), one
level lower and for the same reason.

A `~` is expanded in the path handed back, not only in the copy judged for the
warning. Before that they could disagree: the verdict was reached on the
expanded path and the write happened on the unexpanded one, so whether the
warning described the file being written depended on where `~` pointed.
`_resolve_in`, the input-side equivalent, still does not expand — deliberately
left, because the shell expands `~` before an argument is ever seen and
changing it would move the input paths of every transcription and repair for a
case nobody types.

## FILES-15

A refused path reaches the user as a sentence, and names the flag it arrived on.

The rule in `FILES-14` is one function and the reporting is another. The
resolver raises, so a caller that wants to handle a refusal still can; the CLIs
share a wrapper that exits with the message instead, because a path that names
a directory is an ordinary mistake made typing a flag and not a bug in the
program — the line `prompt.py` takes about a template it cannot read, and
`require_file` about a recording that is not there.

The same rule serves `--output`, `--speakers` and `--names`, so the flag is
passed to it and the message says which one was wrong. A refusal that always
said `--output` would send someone to a flag they never typed.
