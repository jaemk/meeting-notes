# meeting-notes

Turn a recording of a meeting into a document someone can act on: an executive
summary with owners and follow-ups, over a timestamped transcript marked with
who was speaking.

Whisper on its own does not survive a two-hour recording — it conditions on its
own output and gets stuck repeating itself, drops speech it cannot hear, and
invents endings for chunks whose audio has run out. So this splits long audio
at silence boundaries, then finds and re-transcribes its own defects before you
ever see them.

The other half of the design is **declining to guess**. A speaker left
unnamed, a gap reported rather than filled, a figure flagged as inconsistent —
these are correct outputs, not shortfalls. A wrong name or an invented number
that a reader cannot detect is worse than an obvious absence.

Nothing here is specific to one group or one meeting. It wants a single audio
file of people talking.

## Quick start

    ./setup.sh                                    # once — builds .venv
    cp ~/somewhere/meeting.m4a local/
    make transcribe INPUT=local/meeting.m4a       # hours; the long step
    make check      INPUT=local/meeting.m4a       # free; read what is left
    make readable   INPUT=local/meeting.m4a       # the deliverable

That produces `output/meeting.readable.md`. Everything else on this page is
optional: who was speaking (`make diarize`), putting names to them
(`make names`), and correcting proper nouns the decoder mishears
(`local/glossary.txt`).

Two of those steps cost real time — see [What a run costs](#what-a-run-costs)
before starting a long recording. If you would rather not think about the
order, `make pipeline INPUT=local/meeting.m4a` runs every step without
stopping, but it skips the two places a person is supposed to look.

## What you need first

- **Python 3.9–3.13.** `setup.sh` checks the version before it installs
  anything: below 3.9 `openai-whisper` will not install, and above 3.13 numba
  — which it depends on — has no wheel yet, so pip tries to compile it and
  fails several minutes in. Build the venv from a particular interpreter with
  `PYTHON=/usr/bin/python3.12 ./setup.sh`, or take your chances above the
  tested range with `ALLOW_UNTESTED_PYTHON=1 ./setup.sh`.
- **`ffmpeg` and `ffprobe` on `PATH`** — `brew install ffmpeg`, or
  `apt install ffmpeg`. Not optional and not a degraded mode: `ffprobe` reads
  the recording's duration, and `ffmpeg` finds the silences chunks are cut at,
  extracts every chunk and every repair window, and measures the audio under a
  gap so a pause is not mistaken for dropped speech. `setup.sh` refuses to
  finish without them, because otherwise the first sign of trouble is a bare
  `FileNotFoundError` partway into a long run.
- **Room for the model weights**, which are *not* downloaded during setup — see
  [What a run costs](#what-a-run-costs).
- The **`claude` CLI**, for `make analyze`, `make names` and the summary half
  of `make readable`. Everything else runs offline once the weights are
  cached, and `make readable NO_SUMMARY=1` gives you the assembled transcript
  without it.

Optional, and deliberately not installed by `setup.sh`:

- **Speaker diarization** — `pip install -r requirements-diarize.txt`, plus a
  Hugging Face account. 65 packages and 1–2 GB for a feature the transcription
  pipeline does not need, so someone who only wants transcripts does not pay
  for it. See [Who was speaking](#who-was-speaking).

Everything degrades cleanly. Without the `claude` CLI you get transcripts and
a formatted document; without diarization you get an unlabelled one; without
either you still get the part that takes hours and cannot be redone without
the audio.

## Setup

    ./setup.sh          # or: make setup
    ./setup.sh --force  # rebuild the venv from scratch

`setup.sh` is the only place anything is installed. It creates `.venv`, always
installs `openai-whisper` (CPU), and installs `mlx-whisper` **only on Apple
Silicon** — mlx is Metal-only, so on Intel Macs and Linux it would either fail
to build or install a package that can never load. The backend follows suit:
`--backend auto` (the default) picks mlx when this machine can run it and
openai otherwise. Asking for `--backend mlx` where it cannot run is an error
rather than a silent fallback.

Both are installed from **[`requirements.txt`](requirements.txt)**, which
pins exact versions confirmed to work together — a record of a known-good
environment, not a curated minimum. `mlx-whisper`'s line carries a PEP 508
marker (`platform_machine == "arm64" and sys_platform == "darwin"`) so the
same file installs correctly everywhere: pip skips that line on Intel Macs
and Linux instead of failing. Only the two direct dependencies are pinned —
their transitive dependencies (`torch`, `numpy`, `numba`, `mlx`, ...) are left
to the resolver, because a full `pip freeze` from one Python version/platform
can be unsatisfiable on another, and this repo supports Python 3.9–3.13 on
several platforms. Upgrading a version is a deliberate decision, not a
drive-by: see the header of `requirements.txt` for how to re-verify and
refresh the pins.

It takes one optional argument and rejects anything else: `./setup.sh --froce`
exits nonzero instead of quietly doing a non-force setup.

`make help` lists every target and the variables it takes.

## What a run costs

Transcribing a meeting is an errand you start and walk away from, not a command
you wait on. Four things are worth knowing before the first one.

**Wall clock.** Decoding is slower than the recording on a CPU and faster than
it on Apple Silicon, and the gap between the two is enormous — an order of
magnitude, not a few percent. For a 2½-hour recording at the settings `make`
uses (`--model large-v2 -c 5`):

- **Apple Silicon, mlx backend** (what `--backend auto` picks there): hours,
  not minutes. Start it before lunch.
- **CPU backend** — Intel Macs, Linux, or an explicit `--backend openai`:
  roughly 5–10× slower again. `setup.sh`'s model table is in the same units;
  `medium ~6x` there means about six hours of compute per hour of audio, not
  six times faster than realtime. Plan an overnight run, or take a draft from
  `--model small`.

**Chunk size is not the loop knob it looks like.** `make` used to pass `-c 1`
on the theory that shorter chunks loop less. Measured across `-c 1`, `2`, `3`,
`5` and `10` on the worst 30 minutes of a real recording, loops came back 4,
8, 5, 3 and 3 — no trend. Loops start a mean 46% of the way into their chunk
and cluster by position in the *recording*, not the chunk: they are a decoder
failure on hard audio, and a shorter chunk cannot reach them. So `make` now
passes `-c 5`, which is faster (one-minute chunks turn a 2½-hour recording
into ~150 separate `ffmpeg` extractions, each seeking from the start of the
file), cuts on silence more often, and keeps a 2× margin under the ten minutes
where conditioning really does take over. See `spec/chunked-transcription.md`,
CHUNK-7 … CHUNK-12.

`FIX_ARGS` still passes `-c 1`, and that is not an inconsistency: a repair
window is already about a minute, so there `-c 1` means "do not sub-chunk
this" rather than "keep the decode short".

The automatic repair pass at the end is the cheap part, and the only part with
published numbers here: on a 2½-hour meeting it was 12 decode windows and 182
seconds of decoding (29 windows / 391s with `--include-gaps`). That figure is
the *repair*, not the run — do not read it as the cost of the transcription.

**The model download happens on the first decode, not during setup.** Nothing
is fetched by `setup.sh`. The first time a model is used, its weights are
downloaded — roughly 0.5 GB for `small`, ~1.5 GB for `medium`, ~3 GB for the
`large` family, less for the 4-bit mlx repos — into `~/.cache/whisper` (openai)
or the Hugging Face cache (mlx). So a first run appears to stall right after
`Split into N chunks`: the downloader prints its own progress and nothing about
the transcription moves until it lands. It is cached afterwards, but budget it
separately the first time and do not start a long recording on a hotel
connection.

**There is no incremental save and no resume.** `transcribe.py` accumulates
every chunk's segments in memory and writes `.txt`, `.timestamped.txt` and
`.srt` only after the last chunk finishes. Ctrl-C, a laptop going to sleep, or
an out-of-memory kill at chunk 140 of 150 loses the entire run — there is no
partial file to pick up from. On macOS, `caffeinate -i make transcribe …`. A
`repair.py` run is different: its input transcript is already on disk, so a
failed repair costs you the decodes, not the transcript.

**Nothing above applies to a dry run.** `make fix DRY=1` and `make check` decode
nothing and finish in seconds; they are the right way to find out what a repair
would spend before spending it.

## Where files live

    local/      recordings go here          (gitignored)
    output/     everything written lands here (gitignored)

Both directories are ignored, so no recording and no transcript ever reaches the
repo. A bare filename on the command line is looked up in the directory that
kind of file belongs to, so `transcribe.py 2026-07-25.m4a` finds
`local/2026-07-25.m4a` and `repair.py verify 2026-07-25.timestamped.txt` finds
it in `output/`. Anything with a directory component is used as given.

**Nothing from a meeting is committable, wherever it lands.** Ignoring the two
directories is not enough on its own — a file written somewhere else by a
`--output` flag, or dropped in the repo root by hand, would otherwise be fair
game. So `.gitignore` also matches by what a file *is*: every audio and video
extension, `.timestamped.txt`/`.srt`/`.readable.md`/`.summary.md`/`.repaired.*`,
and the four sidecars below. If you add a stage that writes something new,
add its pattern too.

The sidecars deserve naming, because they are more identifying than the
transcript and much easier to send to someone by accident:

    NAME.speakers.json          which stretches are the same voice
    NAME.names.json             which voice is which real person
    NAME.names-candidates.json  every name-like mention, with the
                                surrounding conversation quoted around it
    local/glossary.txt          the real spellings of local names

`names-candidates.json` is the one to be careful with: it is a few hundred KB
of names and quoted context, which is a larger disclosure than the full
transcript in a far more convenient package.

To check the rules are still doing their job:

    git check-ignore -v local/x.m4a output/x.names.json glossary.txt
    git status --porcelain --untracked-files=all   # nothing from a meeting here

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
`--repair-passes N` to change how many diagnose/repair rounds it does, and
`--fallback-model` to choose the model a still-broken window escalates to.
`--no-timestamps` writes the plain `.txt` only, skipping `.timestamped.txt` and
`.srt` — which also means skipping the only view the defects are visible in.

`--repair-passes` on `transcribe.py` and `--passes` on `repair.py` are the same
knob under two names, with the same default of 2: one is the transcription
handing a setting to the repair pass, the other is that pass being run on its
own. `repair.py`'s `--model` and `--language` take the same values as
`transcribe.py`'s. The three gap-dynamics thresholds described below —
`--ambient-peak-db`, `--ambient-spread-db` and `--off-mic-peak-db` — are on both
as well, with the same defaults either way; an incoherent combination is refused
before the transcription starts rather than after it.

`--chunk-size/-c` governs both halves: it caps the whole-file chunks *and* the
slices a repair window is decoded in, so the repair pass can never hand Whisper
a longer stretch than the transcription itself was allowed. `make` uses `-c 5`
for the transcription and `-c 1` for repair windows.

**`ARGS` is how you pass any of that through `make`**, and it is a
*replacement*, not an addition:

    ARGS ?= --model large-v2 -c 5 -l en        # the Makefile's default

    make transcribe INPUT=local/audio.m4a ARGS="--model large-v3 -c 5 -l en"

Setting `ARGS` discards that default wholesale. `make transcribe
ARGS="--backend openai"` does not mean "the usual settings, on the CPU" — it
means `--model medium` and the language auto-detected, which is slower and
less accurate than what you thought you asked for. Restate every flag you
still want. The same applies to `FIX_ARGS` for `make fix` (below), which
defaults to `--model large-v2 -c 1 -l en`.

## What it looks for

| kind      | what it is                                                        | repaired          |
|-----------|-------------------------------------------------------------------|-------------------|
| `loop`    | `--min-run` identical lines in a row (default 3)                   | yes               |
| `stutter` | a phrase repeated 4+ times inside one segment                      | yes               |
| `canned`  | "Thanks for watching", "Subtitles by …" and friends                | yes               |
| `gap`     | 5+ seconds with **speech dynamics** underneath that produced no text | `--include-gaps`|
| `silence` | a gap with nothing but silence underneath — correct behaviour      | no                |
| `ambient` | a gap over loud but flat audio: applause, room noise — not speech  | no                |
| `off-mic` | a gap too quiet for the microphone to have caught the words        | no                |
| `rewind`  | timestamps going backwards at a chunk seam                         | trimmed, no decode|

A `loop` in the wild is usually the same line once a second for twenty seconds
or more, and that is the shape worth picturing — but the rule has no duration
in it at all. It is `--min-run` or more *consecutive* segments whose text is
identical once stripped and case-folded, defaulting to 3 — so three short
segments in a row, a few seconds of audio, is a finding too. Raise `--min-run`
if that is noisier than you want.

Gaps are classified by measuring the audio underneath them with `ffmpeg`, so a
pause in the conversation is not mistaken for dropped speech.

Level alone cannot do that job, though: applause is as loud as a sentence. The
**dynamics** can — applause and room noise sit flat from one second to the next,
speech swings 10–20 dB — so the spread between a gap's quietest and loudest
second decides which gaps a decode may go to. Loud and flat is `ambient` and
quiet throughout is `off-mic`; neither is repairable, both are reported with the
numbers that put them there, and `--include-gaps` reaches only what is left in
between. Three flags move the lines: `--ambient-peak-db` (default −28),
`--ambient-spread-db` (default 9) and `--off-mic-peak-db` (default −32). They are
flags because on the recording they were measured on several gaps sat a few
tenths of a dB either side of the spread threshold. Where the spread cannot be
measured at all, the level-only verdict stands and nothing is bucketed.

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

    # report only, exits nonzero if it finds anything it would repair
    .venv/bin/python repair.py diagnose 2026-07-25.m4a 2026-07-25.timestamped.txt

    # find and fix everything -> output/2026-07-25.repaired.{txt,timestamped.txt,srt}
    .venv/bin/python repair.py repair 2026-07-25.m4a 2026-07-25.timestamped.txt

    # re-check a transcript; exit status is the pass/fail gate
    .venv/bin/python repair.py verify 2026-07-25.repaired.timestamped.txt

`diagnose` and `verify` exit nonzero for the kinds they are *targeting*, which
by default is the repetitions alone. A transcript whose only findings are gaps,
silences or rewinds exits 0 and says so in its report — the gaps are listed but
were never going to be decoded, and failing on them would fail every clean
transcript forever. Add `--include-gaps` and gaps count against the exit status
too, exactly as they then count towards a repair.

Or via make, where `INPUT` picks the transcript for you:

    make check INPUT=local/2026-07-25.m4a   # verify output/2026-07-25.timestamped.txt
    make fix   INPUT=local/2026-07-25.m4a   # repair everything it finds
    make fix DRY=1                          # preview, decode nothing
    make fix IN_PLACE=1                     # overwrite the transcript, keeps a .bak
    make fix WINDOWS="-w 20:47-21:09 -w 1:49:54-1:50:21"
    make fix GAPS=1                         # repair dropped speech too

`TRANSCRIPT=<file>` overrides that choice.

`FIX_ARGS` carries the model, language and chunk size into `make fix`, and like
`ARGS` it **replaces** the Makefile's default (`--model large-v2 -c 1 -l en`)
rather than adding to it:

    make fix FIX_ARGS="--strict"            # ← -c 1 and -l en are now GONE
    make fix FIX_ARGS="--model large-v2 -c 1 -l en --pad 30 --strict"

The first line drops the repair back to 5-minute slices, which is the
long-decode condition the chunking exists to avoid — a repair window is by
definition somewhere Whisper has already looped, so it is the last place to
hand it a long stretch. `WINDOWS`, `GAPS`, `DRY` and `IN_PLACE` are separate
variables and are safe to set on their own; anything that is a flag to
`repair.py` goes in `FIX_ARGS`, in full.

`make clean` removes just this recording's outputs — its `.txt`,
`.timestamped.txt`, `.srt`, any `.repaired.*`, any `.bak`, and the
`.summary.md` and `.readable.md` built from them — leaving the rest of
`output/` alone. `make distclean` is the blunt one: it deletes the venv and
*everything* in `output/`, so it asks for `CONFIRM=1` before doing it.

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

## Who was speaking

Optional, and the one feature with an install of its own.

    make diarize  INPUT=local/2026-07-25.m4a   # once per recording
    make speakers INPUT=local/2026-07-25.m4a   # render it standalone, instant

Whisper does not identify speakers. `diarize.py` runs
`pyannote/speaker-diarization-3.1` over the audio and writes
`output/NAME.speakers.json` — a sidecar saying which stretches are the same
voice, without knowing whose. `make readable SPEAKERS=1` then marks the
transcript up with cluster numbers.

**It costs about a tenth of the recording's length** (12.8 minutes for a
150-minute meeting on an M4) and needs a separate install plus a Hugging Face
account:

    .venv/bin/pip install -r requirements-diarize.txt

Read that file's header before you do — it is 65 packages and 1–2 GB, and the
Hugging Face side has three steps pip cannot do for you (accept the model
conditions on your *account*, create a read token, `.venv/bin/hf auth login`).
It also records two upstream incompatibilities that will otherwise cost you an
afternoon. Nothing else in the project imports it, so skipping this is a
supported configuration rather than a broken one.

`diarize` is the expensive half and runs once per recording; `speakers`
re-renders from the sidecar for free.

**Labels are cluster numbers, never names**, and a paragraph attributed to two
speakers spans a hand-off — it holds words from each, and what is unknown is
where one stops, not who was there. Do not sweep `--contested-ratio` looking
for a better value: it was derived twice, and every band from 0.3 to 0.9
scores the same, because cluster onset error is larger than a transcript
segment.

## Putting names to the voices

    make names INPUT=local/2026-07-25.m4a

Meetings name their own participants — people introduce themselves and address
each other all the way through. `names.py gather` collects every name-like
mention with its context (free, mechanical, deliberately over-inclusive), hands
them to Claude with `naming.md`, and validates the answer into
`output/NAME.names.json`.

The validation is the point of the step. It refuses a cluster the recording
does not have, and any evidence quote that does not appear in the transcript
word for word — so a name has to rest on something that was actually said. It
does **not** make a name right: a real quote pinned to the wrong cluster still
passes, which is why every name carries its evidence and its confidence.

**Expect most clusters to stay anonymous.** That is the designed outcome.
Report coverage as a share of *speech* rather than of clusters — the largest
ten clusters usually hold about 80% of what was said, so naming a handful of
them covers most of the meeting.

`make readable NAMES=1` renders them as `Name (Speaker 7)`, keeping the cluster
number beside each name so a wrong one can be traced back.

## Proper nouns the decoder cannot know

Whisper spells unfamiliar names phonetically, and does it *consistently* —
which is what makes it dangerous. A place name wrong the same way on every page
reads as authoritative, and nothing upstream catches it: the repair loop finds
loops, rewinds and gaps, and a misspelled name is none of those. The audio does
not distinguish a wrong spelling from a right one either, so no measurement
settles it. The only source of truth is a person who knows the name.

Write them down once, in `local/glossary.txt`:

    # <correct spelling>: <variant>, <variant>, ...
    Wren Ashby: Ren Ashbee, Wren Ashbee
    Thornbury Cove: Thornberry Cove, Thorn Bury Cove

Left of the colon is the spelling you want; right of it are the spellings the
transcript actually contains. Matching ignores case and is anchored to word
boundaries, so a short entry never rewrites the inside of an unrelated word.

`make readable` applies it automatically — **having a glossary is the request
to use it**, because a switch you can forget to set produces exactly the
silently-wrong document this exists to prevent. `GLOSSARY=` turns it off for a
run; `GLOSSARY=<file>` names one explicitly.

Check one before trusting it:

    .venv/bin/python glossary.py local/glossary.txt --against output/NAME.repaired.timestamped.txt

That reports what it would correct **and which entries never matched**. The
second half is the useful one: an entry that never fires is either a spelling
the decoder never produced or one you typed wrong, and those are
indistinguishable until something goes looking. Expect to find variants in
passes — apply what you know, re-render, and read what the summary still flags.

Two rules:

- **It never edits the transcript.** `.timestamped.txt`, `.srt` and `.txt`
  keep what the decoder wrote, because they are the audit trail back to the
  audio. Corrections are applied when a document is rendered, and the document
  says a glossary was applied and names every word it changed.
- **Never add a spelling you are guessing at.** A glossary entry is a name.
  Two inconsistent spellings are better than one that is consistently wrong,
  because a reader can see an inconsistency and cannot see an error.

A glossary is nothing but real names, so keep it in `local/`, which is
gitignored.

## The document a person reads

    make readable                    summarise with Claude, then assemble
    make readable SPEAKERS=1         label who is speaking (needs make diarize)
    make readable NAMES=1            and name them (needs make names)
    make readable NO_SUMMARY=1       transcript only — no Claude, no cost
    make readable SUMMARY_PROMPT=<f> ask for a different summary

The `.txt` a transcription writes is one unbroken run of words: correct, and
unusable. `make readable` produces `output/NAME.readable.md` — an executive
summary and a topic-by-topic list of outcomes, follow-ups and owners, with the
transcript underneath it broken into paragraphs where the room went quiet and
timestamped so a passage can be found in the recording. Upload it to Google
Docs directly; Drive converts Markdown on import.

It is two explicit steps, and only the first costs anything. The summary is
written by Claude from `summarize.md` and saved as `output/NAME.summary.md`
before the document is assembled, so it can be re-read, hand-edited, or
regenerated without rebuilding the transcript — and so a bad summary is obvious
rather than buried in the middle of a 23,000-word file. `readable.py` runs on
its own if you only want the formatting.

`NAMES=1` implies `SPEAKERS=1` — a name is put to a cluster, so there has to
be one. Neither flag gives the plain document.

**The summary is written from the document, not from the raw transcript.**
`make readable` pipes `readable.py --transcript-only` into Claude, so the
summariser sees the same paragraphs, the same speaker labels and the same
`[H:MM:SS]` anchors the reader will. That is what stops it describing an
unlabelled transcript directly above a labelled one, and what makes the
timestamps it cites land on headings that actually exist — before the pipe, 4
out of 5 of them pointed at nothing.

`summarize.md` is worth reading before you trust the output. It tells Claude
what the transcript is — machine-generated, single microphone, speakers
labelled only if a diarization pass ran — and to flag uncertainty rather than
fill gaps, which is the difference between a summary you can act on and one
that invents a number. In particular it is told that a figure stated once and
revised a minute later means take the last one **and say the earlier ones
disagreed**, rather than silently picking a number.

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
and what not to do. `@AUDIO@` and `@TRANSCRIPT@` in that file are filled in by
`prompt.py` with whatever `INPUT`/`TRANSCRIPT` resolve to, so the prompt is
worth reading and editing directly; it is the part of this repo that encodes
judgement rather than rules. Rendering is a small script rather than a `sed`
expression in the recipe because a path is not a safe thing to interpolate into
one.

Requires the `claude` CLI on `PATH` (`CLAUDE=` to point elsewhere).

## Tests

    make test

Seven suites — `test_transcribe.py`, `test_repair.py`, `test_readable.py`,
`test_prompt.py`, `test_diarize.py`, `test_names.py` and `test_glossary.py`,
812 checks in total — share the harness in `testlib.py`, which also builds both
fixtures into `output/`: a synthetic transcript with a known loop, rewind and
gap planted in neutral filler, and thirty seconds of ffmpeg-generated
tone/silence for the gap classifier. Nothing depends on a recording, so a fresh
clone runs the whole suite — and every number the tests assert is a property of
the generator rather than of somebody's meeting.

Check names read as sentences about behaviour rather than as function names,
because the suite doubles as the description of what each part promises.

Decoding is stubbed throughout, so it finishes in seconds — and the speaker
suites do not need the optional diarization install either. The only thing
that can skip is the audio-backed gap classification, if `ffmpeg` is not
installed.

## What is written down where

- **`spec/`** — what each part is supposed to do, as numbered statements with
  stable IDs: chunking and seam clamping, defect detection, gap classification,
  window repair, the readable document, the test fixtures. Start at
  [`spec/README.md`](spec/README.md), which carries the status of every feature.
  This is the place to read before trusting a multi-hour run with a recording
  you cannot make again.
- **`analyze.md`** — the reasoning a reader needs to review a transcript: which
  side of a seam is lying, what each defect kind costs, what not to do.
- **`summarize.md`** — what Claude is told about the transcript before it
  summarises it.
- **`naming.md`** — how Claude is told to weigh evidence when putting names to
  voices, and why returning almost nothing is the correct answer.
- **`CLAUDE.md`** — the purpose of the project, how it is driven, and what has
  already been tried and did not work. Read it before changing anything: most
  of it is measurements that rule out an approach which sounds obvious.
- **`.claude/skills/transcribe/`** — the running order as a Claude Code skill,
  which stops at the two points where a person has to look. The `make` targets
  work the same way without it.
