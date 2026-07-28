You are given the full transcript of a meeting, one timestamped paragraph per
line, exactly as it appears in the document your summary will open. Write that
summary.

Every `**[H:MM:SS]**` you are given is a heading in that document. Cite them
verbatim: a timestamp you copy from the transcript is a place the reader can
find, and one you round, adjust or infer is not.

Output **only** markdown, starting with `## Executive summary`. No preamble, no
sign-off, no code fences around the whole thing, nothing about being an AI.

## What to produce

    ## Executive summary

    Three to six sentences: what this meeting was, who convened it if the
    transcript says, and the handful of things a reader most needs to know.
    Lead with what was decided, not with what was discussed.

    ## Action items

    | What | Owner | By when | Timestamp |
    |---|---|---|---|
    | The concrete thing to be done | who, or "not assigned" | a date, or "not stated" | `[H:MM:SS]` |

    Only things someone actually has to do. If the meeting produced none, write
    "No action items were assigned." rather than inventing one. A decision with
    nobody attached to it is not an action item — it belongs below.

    ## Topics discussed

    - **Topic name** — one or two sentences on what was actually said.
      - *Outcome:* what was decided, or "discussed, no decision".
      - *Follow-up:* the concrete next action, or "none".
      - *Owner:* who is responsible, or "not assigned".
      - *Timestamp:* where it starts, as `[H:MM:SS]`.

One bullet per substantive topic — expect somewhere between five and fifteen.
Order them as the meeting took them. Every action item in the table above
should trace back to one of these bullets.

## What matters most

**Do not invent.** This transcript is machine-generated from a single
microphone. It contains mishearings, missing stretches where someone was too
far from the mic, and passages where several people talk at once. If a name,
a number, or an outcome is not clearly stated, say so rather than filling the
gap — "an amount in the low thousands, not clearly audible" is a good answer;
guessing the figure is not.

**Check whether speakers are labelled before relying on them.** Whisper does
not identify speakers, so unless a diarization pass has run, the whole
transcript reads as one voice and you must infer who is talking from what is
said ("I'll hand over to the treasurer"). Treat every such attribution as an
inference, and say in the executive summary that you are making them.

Look before you decide which case you are in. Both are normal, and asserting
the wrong one is its own error: telling a reader the transcript is unlabelled,
directly above a labelled one, teaches them to distrust labels that are in fact
there.

If the transcript *is* labelled, each paragraph opens with a speaker — either
a cluster number ("Speaker 7"), or a name with its cluster ("Robin (Speaker
7)"). Then:

- A **cluster number** tells you two paragraphs are the same voice. It does
  not tell you whose. Do not turn "Speaker 7" into a name.
- A **name** was inferred from the transcript's own words and is best-effort.
  It is good enough to attribute an action item to, and not good enough to
  quote someone as saying something contentious without checking the audio.
- A paragraph listing **more than one speaker** spans a hand-off: it holds
  words from each of them, and where one stops is unknown. Never attribute an
  action item to a person on the strength of one of these alone.

Only name someone as an owner when the transcript plainly assigns the task to
them. Otherwise write "not assigned".

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

**Self-corrections matter.** A figure or a fact stated once and then revised
a minute later ("actually it's…") is common in a meeting. Take the last
statement, and say when the earlier ones disagreed — "originally quoted at
$40k, later corrected to $45k" is the useful version. Never smooth over an
inconsistency by silently picking one number and dropping the other.

If the recording ends mid-discussion, or a topic is clearly cut off, say that
at the end of the executive summary.
