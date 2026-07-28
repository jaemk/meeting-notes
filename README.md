# meeting-notes

Transcribe a meeting recording and turn it into a document you can read: an
executive summary with action items, followed by the full transcript broken
into timestamped paragraphs, optionally labelled with who was speaking.

It runs locally. The transcription uses Whisper on your own machine, so the
audio never leaves it. The summary step sends the transcript to Claude, and you
can skip that step if you would rather it didn't.

Whisper on its own struggles with long recordings: it repeats itself, skips
speech it can't make out, and sometimes keeps transcribing past the end of what
it was given. This project splits the audio into chunks, then checks its own
output for those problems and re-transcribes the parts that went wrong.

## What you get

`output/meeting.readable.md`. The content below is made up, but the structure
is real:

    # Meeting transcript — meeting

    1,847 segments · 12,402 words · 1:22:15 running time

    ## Executive summary

    The hall committee met to settle the roof tender...

    ## Action items

    | What | Owner | By when | Timestamp |
    |---|---|---|---|
    | Circulate the revised quote | Wren Ashby | 12 March | `[0:41:07]` |
    | Confirm the hall is insured | not assigned | not stated | `[1:03:22]` |

    ## Topics discussed

    - **Roof tender** — Three quotes were read out...
      - *Outcome:* lowest quote accepted subject to insurance.
      - *Follow-up:* circulate the revised quote.
      - *Owner:* Wren Ashby.
      - *Timestamp:* `[0:41:07]`

    ## Full transcript

    **[0:00:00]** Wren Ashby (Speaker 3) — Right, shall we make a start...

    **[0:00:34]** Speaker 11 — Before we do, can I ask about the notice period?

Three things in that are easy to misread:

- `Speaker 11` with no name is normal. Names are only attached when someone is
  addressed by name in the recording, so most voices stay as numbers.
- A paragraph listing two speakers covers a hand-off between them. It contains
  words from both, and the exact changeover point isn't known.
- `not assigned` and `not stated` are real answers. The summary is asked to
  leave these blank rather than guess.

You can upload the file to Google Docs directly; Drive converts Markdown on
import.

## Requirements

**macOS or Linux.** The setup script is a shell script and the pipeline calls
`ffmpeg` throughout. On Windows, use WSL.

**Python 3.9 to 3.13.** Below 3.9, `openai-whisper` won't install. Above 3.13,
numba has no wheel yet, so pip tries to compile it and fails a few minutes in.

**ffmpeg and ffprobe on your PATH.** Used on every run to read the recording's
duration, find silences to split at, and extract audio for each chunk.

    brew install ffmpeg          # macOS
    sudo apt install ffmpeg      # Debian/Ubuntu
    sudo dnf install ffmpeg      # Fedora

**Disk space for the model.** Whisper's weights download the first time you
transcribe, not during setup: roughly 0.5 GB for `small`, 1.5 GB for `medium`,
3 GB for the `large` models.

**The `claude` CLI**, if you want the summary. It's used by `make readable`,
`make names` and `make analyze`. Everything else works without it.

A machine with Apple Silicon will be substantially faster; see
[How long it takes](#how-long-it-takes).

## Setup

    git clone <this repo> && cd meeting-notes
    ./setup.sh

That creates `.venv` and installs Whisper. It doesn't download any model
weights, and it doesn't install speaker diarization, which is optional and
covered below.

    ./setup.sh --force                      # rebuild the venv from scratch
    PYTHON=/usr/bin/python3.12 ./setup.sh    # use a specific interpreter

On Apple Silicon the setup also installs `mlx-whisper`, which uses the GPU and
is much faster. On Intel Macs and Linux it's skipped, and the CPU backend is
used instead. You don't need to choose; the default picks whichever will run.

## Running it

Put the recording in `local/`, then work through the steps. Only the first one
takes real time.

### 1. Transcribe

    make transcribe INPUT=local/meeting.m4a

This splits the audio, transcribes each chunk, joins the results, then checks
the transcript for problems and re-transcribes the affected parts. Expect it to
take a while: see [How long it takes](#how-long-it-takes).

Output is `output/meeting.txt`, `output/meeting.timestamped.txt` and
`output/meeting.srt`, plus `output/meeting.repaired.*` if anything was fixed.

### 2. See what's left

    make check INPUT=local/meeting.m4a

Lists anything the automatic pass couldn't fix. It exits with a non-zero status
if there's something outstanding, which is how the Makefile uses it, so a
non-zero exit here is information rather than an error.

Findings come in a few kinds:

| kind | meaning | what to do |
|---|---|---|
| `loop`, `stutter`, `canned` | Whisper repeated itself | worth re-transcribing (step 3) |
| `gap` | speech that produced no text | re-transcribe; about two thirds come back with something |
| `ambient` | applause or room noise, not speech | leave it |
| `off-mic` | someone too far from the microphone | can't be recovered |
| `silence` | a genuine pause | nothing to do |
| `rewind` | a chunk overran its boundary | already fixed automatically |

`ambient` and `off-mic` are listed with the measurements behind them so you can
disagree, but neither is worth re-transcribing. Re-transcribing near-silence is
how phrases like "Thanks for watching" end up in a transcript.

### 3. Fix anything worth fixing

    make fix INPUT=local/meeting.m4a WINDOWS="-w 20:47-21:09"

Add `DRY=1` to see what it would do without transcribing anything. Each window
takes about fifteen seconds.

If a repaired section comes back without punctuation or capitals, it came from
a fallback attempt and is usually worse than what it replaced. Revert it.

### 4. Write the document

    make readable INPUT=local/meeting.m4a

Claude writes the summary into `output/meeting.summary.md`, then the transcript
is assembled underneath it into `output/meeting.readable.md`. These are two
separate steps so you can read or edit the summary on its own, and so
regenerating it doesn't rebuild anything else.

    make readable INPUT=... NO_SUMMARY=1     # transcript only, no Claude

That's the whole core pipeline. The rest is optional.

## Who was speaking

Whisper doesn't identify speakers. Diarization is a separate model that groups
the audio by voice, and it needs its own install.

    .venv/bin/pip install -r requirements-diarize.txt

That's 65 packages and 1–2 GB, which is why it isn't part of the main setup.
Read the top of that file before installing: it records two version conflicts
that are awkward to diagnose from the error messages alone.

The model weights are gated on Hugging Face, and pip can't do that part. All
three of these are needed, and missing any one produces the same unhelpful 401:

1. On huggingface.co, accept the conditions for
   `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` (and
   `pyannote/wespeaker-voxceleb-resnet34-LM` if it asks). This is tied to your
   account, not to the token.
2. Create a read token. If you use a fine-grained token, tick "Read access to
   contents of all public gated repos you can access".
3. Run `.venv/bin/hf auth login`. The command is `hf`, not `huggingface-cli`,
   which was renamed but still appears in most documentation.

Then:

    make diarize  INPUT=local/meeting.m4a     # once per recording
    make readable INPUT=local/meeting.m4a SPEAKERS=1

Diarization takes roughly a tenth of the recording's length, so about 13
minutes for a 2½-hour meeting. It only needs to run once. `make speakers`
re-renders the result on its own, which is quick.

Speakers come out as numbers, not names. A recording will typically produce
more clusters than there were people, because someone who says one word gets
their own.

## Putting names to voices

    make names INPUT=local/meeting.m4a

People introduce themselves and address each other by name during a meeting.
This collects every name-like mention with its surrounding context, asks Claude
which cluster each name belongs to, and checks the answer: the cluster has to
exist, and the quoted evidence has to appear in the transcript word for word.

Then render with names:

    make readable INPUT=local/meeting.m4a NAMES=1

Most clusters stay anonymous, which is intended. On a 39-cluster recording,
naming eight or so is a good result, and that usually covers most of the
speaking time because a few people do most of the talking.

The check confirms a name was said. It can't confirm it was matched to the
right voice, so each name keeps its cluster number beside it and the sidecar
records the evidence.

## Correcting spellings

Whisper spells unfamiliar names phonetically, and does it the same way every
time, so a wrong place name looks deliberate. Nothing detects this
automatically. If your recordings involve names it keeps getting wrong, list
them in `local/glossary.txt`:

    Wren Ashby: Ren Ashbee, Wren Ashbee
    Thornbury Cove: Thornberry Cove, Thorn Bury Cove

The correct spelling goes on the left, what the transcript actually says on the
right. Matching ignores case and respects word boundaries.

`make readable` picks the file up automatically. Use `GLOSSARY=` to skip it for
one run, or `GLOSSARY=<file>` to point elsewhere.

To check a glossary before relying on it:

    .venv/bin/python glossary.py local/glossary.txt --against output/meeting.timestamped.txt

That prints what it would change and, more usefully, which entries never
matched anything. An entry that never fires might be a spelling Whisper never
produced, or might be a typo, and they look the same until you check.

Corrections are applied when the document is rendered. The transcript files
keep whatever Whisper wrote, so they stay usable as a reference against the
audio, and the document notes that a glossary was applied and which words it
changed.

Keep the glossary in `local/`, which is gitignored. It's a list of real names.

## How long it takes

Transcription is the slow part, and how slow depends heavily on the machine.

On Apple Silicon with the mlx backend, a 2½-hour recording takes a couple of
hours. On the CPU backend, whether that's an Intel Mac or Linux, it's roughly
5–10 times slower again, so plan an overnight run or use a smaller model for a
first look.

The automatic repair pass at the end is comparatively cheap: on that same 2½-
hour recording it was 12 windows and about three minutes of transcription.

Two things worth knowing before you start a long run:

- **The model downloads on the first transcription**, not during setup. The run
  appears to stall right after `Split into N chunks` while that happens. It's
  cached afterwards.
- **There's no resume.** Results are written after the last chunk finishes, so
  interrupting a run loses it. On macOS, `caffeinate -i make transcribe ...`
  stops the machine sleeping partway through.

`make check` and `make fix DRY=1` don't transcribe anything and finish in
seconds.

## Commands

`make help` lists everything. The common ones:

| command | what it does |
|---|---|
| `make transcribe` | transcribe and auto-repair |
| `make check` | report what's still wrong |
| `make fix` | re-transcribe specific windows |
| `make readable` | build the summary and document |
| `make diarize` | group the audio by voice (optional install) |
| `make speakers` | render the speaker view on its own |
| `make names` | match names to voices |
| `make analyze` | open a Claude session with the transcript |
| `make pipeline` | all of the above in order |
| `make test` | run the test suite |
| `make clean` | delete this recording's outputs |

Useful variables:

| variable | effect |
|---|---|
| `INPUT` | the recording. Defaults to `local/input.*` if present |
| `TRANSCRIPT` | work on a specific transcript file |
| `ARGS` | flags for `transcribe.py` |
| `FIX_ARGS` | flags for `repair.py` |
| `WINDOWS` | limit `fix` to given times, e.g. `-w 20:47-21:09` |
| `DRY=1` | preview a fix without transcribing |
| `SPEAKERS=1` / `NAMES=1` | label the document |
| `NO_SUMMARY=1` | build the document without calling Claude |
| `GAPS=1` | treat missing speech as repairable |

`ARGS` and `FIX_ARGS` **replace** the defaults rather than adding to them. The
default for `ARGS` is `--model large-v2 -c 5 -l en`, so
`make transcribe ARGS="--backend openai"` will also drop you back to the
default model and automatic language detection. List every flag you want.

## Where files go

    local/     recordings (gitignored)
    output/    everything produced (gitignored)

Both directories are ignored by git. `.gitignore` also matches by file type,
so audio, transcripts and the speaker sidecars stay out of commits even if they
end up somewhere else.

Files are named after the recording, so `local/meeting.m4a` produces
`output/meeting.timestamped.txt` and so on. You can pass a bare filename to the
scripts and they'll look in the right directory.

Two files are worth handling carefully:

- `meeting.names.json` maps voices to real people.
- `meeting.names-candidates.json` contains every name mentioned along with the
  conversation around it, which is a larger disclosure than the transcript in a
  much smaller file.

## When something goes wrong

**Setup won't finish and mentions ffmpeg.** It's required on every run, so
setup checks for it rather than letting a long transcription fail partway.
Install it and re-run.

**Setup rejects your Python version.** Point it at another interpreter:
`PYTHON=/usr/bin/python3.12 ./setup.sh`. To try an untested version anyway, set
`ALLOW_UNTESTED_PYTHON=1`.

**It seems to hang after `Split into N chunks`.** The model is downloading. It
only happens once.

**`no local/input.* found`.** With no `INPUT`, make looks for a file called
`local/input.*`. Pass `INPUT=local/yourfile.m4a`.

**`make check` exits non-zero.** That's how it reports outstanding findings.
Read the list.

**`claude: command not found`.** Only the summary, `make names` and `make
analyze` need it. Use `NO_SUMMARY=1`, or set `CLAUDE=/path/to/claude`.

**Diarization returns a 401.** All three Hugging Face steps are needed and they
fail identically. See [Who was speaking](#who-was-speaking).

**A name in the document is wrong.** Remove it from `output/meeting.names.json`
and re-render; the voice reverts to a number. A wrong *spelling* is different:
put it in the glossary, otherwise the next render loses your edit.

**Your flags seem to have been ignored.** `ARGS` and `FIX_ARGS` replace the
defaults. See [Commands](#commands).

## Tests

    make test

813 checks across seven suites. Transcription is stubbed, so the tests need no
model, no network and no GPU, and finish in seconds. The speaker tests don't
need the optional diarization install either.

Nothing in the suite depends on a real recording. The fixtures are generated:
a synthetic transcript with a known loop, rewind and gap, and a short
ffmpeg-generated audio file for the gap classifier.

## How this project is documented

- **`spec/`** — what each part is supposed to do, as numbered statements with
  stable IDs, along with the measurements behind the defaults and the
  approaches that were tried and rejected. [`spec/README.md`](spec/README.md)
  lists every feature and its status. This is the place to look before changing
  behaviour.
- **`CLAUDE.md`** — orientation for Claude Code or another agent working in the
  repo: the constraints, the layout, and which spec covers what.
- **`.claude/skills/transcribe/`** — the running order as a skill, for driving
  the pipeline through an agent. The `make` targets do the same thing.
- **`analyze.md`, `summarize.md`, `naming.md`** — the prompts used for the
  three steps that ask Claude for a judgement.

## License

MIT. See [LICENSE](LICENSE).

That covers this project's own code. The models it downloads at runtime have
their own terms, which are not affected by it: Whisper is MIT, and pyannote's
diarization models are MIT but gated behind user conditions you accept on your
own Hugging Face account.
