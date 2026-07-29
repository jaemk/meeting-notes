# Run cost and durability

A transcription is measured in hours, and the cost is invisible from the
command line: the same command that takes ninety seconds on a voice memo takes
most of a day on a conference recording, on the wrong machine. What a run
costs, and what happens when it is interrupted, are part of the contract —
users plan around them and are misled by silence.

## COST-1

Decode time is stated in units that cannot be read backwards. "6× realtime"
means six hours of compute per hour of audio; anything that could be read as
"six times faster than realtime" is written out in full instead. A reader who
budgets 25 minutes for a 2½-hour meeting has been misinformed by the
documentation, not by the tool.

## COST-2

The documentation states a realistic wall clock for a long recording *with its
assumption attached*. Apple Silicon with mlx and a CPU-only machine differ by
roughly an order of magnitude, so a single number without the machine it was
measured on is worse than no number. The published repair-pass figures (12
decode windows / 182s on a 2½-hour meeting, 29 / 391s with `--include-gaps`)
are labelled as the repair, never as the run.

## COST-3

Model weights are downloaded on the first decode that needs them, not by
`setup.sh` (`BACKEND-9`): hundreds of megabytes to a few gigabytes, into
`~/.cache/whisper` or the Hugging Face cache. The documented symptom is what
the user actually sees — a first run that appears to stall right after
`Split into N chunks` — because that is the moment they would otherwise kill it.

## COST-4

A transcription writes nothing until it finishes. Segments accumulate in memory
and `.txt`, `.timestamped.txt` and `.srt` are written after the last chunk, so
an interruption at chunk 140 of 150 loses the whole run: there is no partial
output and no resume. This is a known durability limit, and it is documented
rather than left to be discovered, because the discovery costs hours.

Anything that adds incremental output must not weaken the merge: a chunk's
segments are clamped to that chunk's own audio before they join the transcript
(`MERGE-2`, `MERGE-3`), and clamping is what makes a rewind impossible in a
fresh transcript.

## COST-5

`repair.py` against an existing transcript is the cheap, restartable half: its
input is already on disk, so a failed repair costs the decodes and not the
transcript. `--dry-run` and `verify` decode nothing at all, and are the
documented way to find out what a repair would spend before spending it.

## COST-6

`-c 1`, which `make` passes, is a stated trade rather than a tuning detail: it
is what keeps Whisper from looping, and it multiplies the number of chunk
extractions. Documentation that recommends it also says what it costs.

## COST-7

`--in-place` backs up **every file it overwrites**, not just the one named on
the command line. A repair rewrites all three renderings from one stem (`.txt`,
`.timestamped.txt`, `.srt`, per `FILES-5`), so a `.bak` of the transcript alone
leaves the other two overwritten with nothing to restore them from. What they
hold is hours of decoding, and re-running the repair does not bring it back: the
input it would need is the file that was just overwritten. The `.bak` is the
whole of the recovery story here, which is why the flag's help states what it
copies rather than promising "a .bak".

Only the siblings that exist are copied. A `.bak` of a file that was never
written is an empty file that reads as a recoverable transcript.

## COST-8

The pre-repair transcript is worth protecting from the *second* in-place run,
not only from the first.

`COST-5` calls a repair the cheap, restartable half because its input is
already on disk. That is the whole of the argument, and it holds only while the
input is still there. A repair costs a handful of windows; the transcript it
edits cost the decode — `COST-1` and `COST-2`, hours of compute on a long
recording — and the audio is the only thing it can be made from again. Once a
second `--in-place` run has copied the first one's output over the `.bak`, the
undo is not a restore, it is a re-transcription.

So a repair that would overwrite an existing backup stops, before it loads the
transcript and long before it decodes anything (`FILES-12`). A refusal raised
where the backup is actually taken — after the repair has run — would already
have spent the decodes it exists to protect, which is the same ordering
argument `AUTO-10` makes about the seam trim.

Overriding it is allowed and is reported. `--replace-backup` names the backups
it replaced and says what they held, because the danger was never the overwrite
itself: it is a command that destroys the only copy of an afternoon's decoding
and prints "Backed up original" as it goes.
