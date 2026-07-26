You are given the full transcript of a meeting, one timestamped segment per
line. Write the summary that goes at the top of the document.

Output **only** markdown, starting with `## Executive summary`. No preamble, no
sign-off, no code fences around the whole thing, nothing about being an AI.

## What to produce

    ## Executive summary

    Three to six sentences: what this meeting was, who convened it if the
    transcript says, and the handful of things a reader most needs to know.
    Lead with what was decided, not with what was discussed.

    ## Topics discussed

    - **Topic name** — one or two sentences on what was actually said.
      - *Outcome:* what was decided, or "discussed, no decision".
      - *Follow-up:* the concrete next action, or "none".
      - *Owner:* who is responsible, or "not assigned".
      - *Timestamp:* where it starts, as `[H:MM:SS]`.

One bullet per substantive topic — expect somewhere between five and fifteen.
Order them as the meeting took them.

## What matters most

**Do not invent.** This transcript is machine-generated from a single
microphone. It contains mishearings, missing stretches where someone was too
far from the mic, and passages where several people talk at once. If a name,
a number, or an outcome is not clearly stated, say so rather than filling the
gap — "an amount in the low thousands, not clearly audible" is a good answer;
guessing the figure is not.

**Speakers are not labelled.** Whisper does not identify speakers, so the whole
transcript reads as one voice. You can often infer who is talking from what is
said ("my good buddy X will take over"), but treat every attribution as an
inference. Only name someone as an owner when the transcript plainly assigns
the task to them. Otherwise write "not assigned".

**Prefer the reader's questions.** Someone reads this to find out what was
decided, what it costs, what happens next and who is doing it. Procedural
mechanics — motions, seconds, votes to accept minutes — are worth one line
collectively, not one bullet each, unless the vote was contested.

**Quote sparingly and exactly.** A short direct quote is useful where the exact
wording matters, such as the terms of a motion. Never paraphrase inside
quotation marks.

**Money, dates and quantities are worth extra care.** They are what a reader
will act on, and they are also what a transcription most often gets wrong. If a
figure appears only once and sounds implausible in context, flag it as
uncertain rather than repeating it flatly.

If the recording ends mid-discussion, or a topic is clearly cut off, say that
at the end of the executive summary.
