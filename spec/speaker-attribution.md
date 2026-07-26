# Speaker attribution

**Status: research.** Needs design before it can be built, and may not be
worth building for a single-microphone recording.

## SPEAKER-1

Whisper does not identify speakers. Every transcript this repo produces reads
as one continuous voice, which is the single largest gap between what it emits
and what a reader of a meeting transcript wants.

## SPEAKER-2

Paragraph breaks in the readable document approximate turns because people
pause when they hand off. They land on a turn boundary often and never
reliably, and nothing downstream should treat them as more than that.

## SPEAKER-3

Open questions: whether to run a separate diarization model over the same
audio and align its turns to segment timestamps; whether a single far-field
microphone in a room carries enough separation for that to work at all; and
how attribution would be represented in the `.timestamped.txt`, which is
currently a flat list every other tool parses.

## SPEAKER-4

Whatever is built must not invent attributions. A confident wrong name against
a quote is worse than no name, because a reader cannot tell it was guessed. An
unattributed turn is an acceptable output; a fabricated one is not.
