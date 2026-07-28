You are given a JSON file of name-like mentions pulled from a meeting
transcript, together with the shape of each acoustic speaker cluster the
diarizer found. Decide which clusters can be given a name.

Output **only** a JSON object, no prose, no code fence, no preamble:

    {"names": {
      "<cluster id, exactly as the input spells it>": {
        "name": "<the name, spelled as the transcript spells it>",
        "role": "<the role the transcript assigns, or null>",
        "confidence": "<high | medium | low>",
        "basis": "<how you know: which kinds of evidence, and how many>",
        "evidence": [{"at": 0.0,
                      "quote": "<the words that say so, copied from the input>"}]
      }
    }}

**Every value above is a placeholder describing what belongs there — none of
them is an answer.** This block is the shape to fill in, and a real answer has
none of these strings in it. Copying one through is the failure this warning
exists to prevent: it happened, an example name reached a finished document,
and it was read as a real person for 164 paragraphs before anyone noticed. If
your answer still contains a `<…>`, you have described the format rather than
used it.

`name` or `role` may be null, but not both. `confidence` is `high`, `medium`
or `low`. `evidence` must hold at least one `{at, quote}` taken verbatim from
the input. A cluster you cannot identify is simply absent from the object.

Both halves are checked before anything is written: a cluster the recording
does not have is refused, and so is a quote that does not appear in the
transcript word for word. Neither check can tell you a name is *right* — only
that it is not invented outright.

## The one rule that matters

**Returning almost nothing is the correct answer.** On the recording this was
built for, 2 of 39 clusters introduce themselves, and mechanically following
"a name refers to whoever speaks next" named 2 clusters with one of them
wrong. Expect to name somewhere between three and ten clusters out of thirty
or forty. A wrong name is far worse than no name: a reader cannot tell that a
name was guessed, and they will quote it. An anonymous "Speaker 7" costs them
almost nothing.

If you find yourself reasoning "it is probably X because they were talking
about Y", stop. That is the reasoning that produces confident wrong answers.

## Weighing the evidence

**Self-introduction** (`kind: "self"`) is the strongest. Someone saying "my
name is X" is the cluster that said it — no adjacency reasoning needed. But
check the regex has not misfired: "I'm sorry", "I'm not sure" and "this is
ridiculous" all match the pattern and name nobody.

**Being addressed** (`kind: "addressed"`) is common and much weaker. Roughly
half of these are not people at all — "Thankfully,", "Secondly,",
"Apparently,", "Anyhow,", "Essentially," — and no word list can separate them,
because real first names are often ordinary English words too. Judge each one
from the sentence it sits in.

**Adjacency is the weakest link in the chain.** `next_speaker` records who
spoke after a name was said. It is *suggestive only*: the diarizer's turn
boundaries are a median 6.5 seconds from the truth, which is longer than most
turns, so "who spoke next" is frequently wrong. Never name a cluster on a
single adjacency. Two or more independent moments pointing the same name at
the same cluster is real evidence; the same exchange recurring is not.

**Corroboration must come from different kinds of evidence**, not more of the
same kind. A name confirmed by a self-introduction *and* by being addressed at
a hand-off is solid. The same vocative appearing four times is one piece of
evidence repeated four times — the same misattributed hand-off produces the
same wrong pointer every time it recurs.

**What a cluster says is evidence about who it is.** If the room is told a
lawyer is present and one cluster answers every question about bylaws and
liability, that is genuine support for identifying that cluster as the lawyer
— as a *role*, and as a name only if the transcript states one.

## Roles

Record a `role` whenever the transcript assigns one ("Treasurer's Report,
X"), even where the name is unclear. "The Treasurer" is useful to a reader
and claims far less than a name does. A cluster may have a role and no name.

## Clusters that are not people

The `clusters` object gives each cluster's total speech, mean turn length,
concentration (what fraction of its speech falls in its densest five-minute
window) and time spread. Some clusters are not voices at all — they are what
is left over when short interjections cannot be matched to anyone, and their
signature is a mean turn well under a second, low concentration, and turns
scattered across the whole recording.

Do not name these. There is no person there to name. Be careful, though: a
real person who spoke once briefly also has little speech and short turns —
what separates them is that the real one's speech is *concentrated* in one
stretch, while the leftover cluster's is smeared across the entire meeting.
This judgement is yours because no reliable automatic test for it exists yet.

## Confidence

- `high` — a self-introduction, or two independent kinds of evidence agreeing.
- `medium` — addressed by name at a clear hand-off, consistent with what the
  cluster goes on to say, and nothing contradicting it.
- `low` — a single suggestive mention. Prefer omitting the cluster entirely
  over recording a low-confidence name; include one only when the name would
  genuinely help a reader and the basis states plainly how thin it is.

## Before you answer

Check each entry against these:

1. Is the quote in `evidence` actually present in the input, word for word?
2. Would this survive someone listening to the recording at that timestamp?
3. Am I naming this cluster on one adjacency alone? If so, drop it.
4. Is this cluster a person at all, or scattered leftovers?
5. Have I confused two people who were both addressed near the same hand-off?

Names in a private meeting are the most consequential thing in this pipeline.
When in doubt, leave the cluster anonymous.
