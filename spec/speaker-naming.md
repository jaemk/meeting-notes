# Speaker naming

**Status: done, with two parts deliberately unbuilt** — NAME-10's automatic
smear exclusion (blocked on
[smear-cluster-identification.md](smear-cluster-identification.md)) and
NAME-11's per-segment threshold (see NAME-17). Built as `names.py`, `naming.md`
and `make names`, on top of the clusters
[speaker-attribution.md](speaker-attribution.md) produces.

Diarization answers "how many different voices, and which segments are the
same one". It cannot answer "who". The names are in the transcript — people
introduce themselves, and they address each other by name all meeting — so
the question is whether they can be attached to clusters without inventing
anything. This spec says how, and what it will and will not manage.

## NAME-1

The output is a **names sidecar**, `output/<recording>.names.json`, mapping
cluster to name with the evidence that produced it:

Every name in this spec is invented — the measurements come from a real
private recording and nothing from `output/` belongs in a committed file:

    {"SPEAKER_02": {"name": "Wren Ashby", "confidence": "high",
                    "basis": "self-introduction",
                    "evidence": [{"at": 34.2, "quote": "my name is Wren Ashby"}]},
     "SPEAKER_16": {"name": "Robin", "role": "Treasurer", "confidence": "medium",
                    "basis": "addressed by name at a hand-off", ...}}

Same reasoning as SPEAKER-20: a third sidecar rather than a column in
`.timestamped.txt`, so deleting the file un-ships the feature and nothing else
notices. It is keyed by cluster, not by segment, because a name belongs to a
voice and the mapping from voice to segment already exists.

## NAME-2

Every entry carries its evidence, and the evidence is a timestamp and a quote
from the transcript. A reader who doubts a name must be able to go to the
recording and settle it in one jump. A name without a checkable basis is a
guess wearing a fact's clothing, which is SPEAKER-4's failure with a nicer
presentation.

## What the transcript actually offers

Measured on the 150-minute recording behind SPEAKER-16, whose 39 clusters are
described in SPEAKER-29 … SPEAKER-31.

## NAME-3

**Self-introduction is the strongest evidence and the rarest.** "my name is
…", spoken by the cluster it names, needs no adjacency reasoning and no
judgement about who was being addressed. There are exactly **two** in 150
minutes. One of them is the moderator, who holds 26.1% of all speech, so two
mentions is not as thin as it sounds — but a design that relies on
self-introduction names two clusters out of 39 and stops.

## NAME-4

**Being addressed by name is plentiful and much weaker.** A regex for a
capitalised word against a comma finds 108 mentions, and roughly half are
sentence adverbs, not people: "Thankfully,", "Secondly,", "Apparently,",
"Anyhow,", "Essentially,", "Unfortunately,". This cannot be fixed with a
stop-list, because the collision runs the other way too — several of the first
names actually used in this recording are themselves ordinary English words
(among them a virtue, a shortening that is also a preposition, and a common
given name that doubles as a noun). Deciding that "<Name>, do you have any
comments?" addresses a person while "Thankfully, that's a zoning issue" does
not is a semantic judgement, and it is the reason this feature belongs with
`make analyze` rather than in a rule (see NAME-8).

## NAME-5

**Adjacency is weaker still.** The natural rule — a name in this turn refers
to whoever speaks next — was tried against the mentions that really are
people. Of ten names with any support, two reach agreement from two or more
independent mentions, and one of those two points at a cluster holding 16
seconds of speech. Two further names each split one-and-one between two
different clusters, which is no evidence at all. **Mechanical adjacency names
2 of 39 clusters, and one of them is probably wrong.** This is the
load-bearing measurement in this spec: it rules out shipping the cheap
version. It fails for the reason SPEAKER-17 already established — cluster
onset is the unreliable half of the signal, and "who speaks next" is a
question about onsets.

## NAME-6

**Roles are stated more reliably than names, and are worth capturing.** The
strongest hand-offs in this recording name an office and a person in one
breath — the pattern is "…, Treasurer's Report, <Name>" — and the office is
the half that recurs. A cluster identified only as "the Treasurer" is still
useful to a reader and commits to less than a name does, so `name` and `role`
are separate fields and either may be absent.

## NAME-7

Expect **5–10 of 39 clusters** to be nameable, and expect them to be the ones
that matter: the ten largest clusters hold 79% of all speech, and they are the
moderator, the officers and the report-givers — the people the transcript
names, because they are the people who get handed the floor. The long tail of
one-question residents from SPEAKER-29 will stay anonymous, which is the
correct outcome and not a shortfall. State it as coverage of *speech*, never
as a fraction of clusters.

## How it should work

## NAME-8

Two commands, mirroring `diarize.py` and for the same reason: gather cheaply,
judge expensively, and let the cheap half re-run free.

`names.py gather` reads the transcript and the speaker sidecar and writes
**candidates** — every name-like mention with its cluster, its timestamp, the
surrounding turns and which cluster speaks next. No judgement, no cost, and
deliberately over-inclusive: recall here is free and precision is NAME-9's
job.

The judging half is `make names`: Claude reads those candidates with a prompt
(`naming.md`, alongside `analyze.md` and `summarize.md`), and `names.py
ingest` validates the answer into the sidecar. This is the step that decides
whether a matched word is a person at all, which cluster they are, and whether
the evidence is good enough to say so. It shipped as `ingest` rather than the
`resolve` named here because the validation, not the asking, is the part worth
having a command for — see NAME-18.

## NAME-9

The prompt's instructions matter more than the gathering does. It must be told
to prefer self-introduction over being-addressed over adjacency; to require
corroboration from more than one moment before naming a cluster on adjacency
alone; to weigh what a cluster *says* against the name — a cluster that
answers the bylaws questions is evidence about which cluster is the lawyer the
room was told is present — and, above all, that **returning no name is a
correct and expected answer**. A prompt that implies every cluster should be
resolved will resolve every cluster.

## NAME-10

Clusters that are smears rather than voices must be excluded from the
candidate set before Claude sees them. They are not people, and no evidence
about them can be right. Excluding them in `gather` rather than asking
`resolve` to reject them keeps a judgement call out of a decision measurement
should settle.

**Blocked on [smear-cluster-identification.md](smear-cluster-identification.md).**
SPEAKER-42 measured the rule this depended on and it does not work: the stated
cut points miss the two clearest smears in the recording and select a real
recurring participant, and tuning them until they do not is fitting to a
single file. That spec sets out what a second recording makes possible and how
to validate a rule against it; until then `gather` cannot exclude
automatically. The fallback is to hand the
cluster's shape — total speech, mean turn, concentration, time spread — to
`resolve` alongside the evidence, and let the same judgement that decides
whether a name is real also decide whether the thing being named is a person.
That is weaker than a measured exclusion and must not be described as one.

## NAME-11

The contested threshold becomes **a property of the segment, not of the run**.
SPEAKER-26 chose 0.7 by weighing two errors: marking a segment unclear when the
winner was right, against attributing it when the winner was wrong. Naming
changes only the second of those. The cost of an unnecessary "unclear" is a
broken paragraph either way; the cost of a wrong attribution goes from a
misleading cluster number to a real person shown saying words another real
person said. One side of the trade moves and the other does not, so the
threshold tightens — but only where a name is actually at stake.

A single global drop to 0.4 would be wrong, because only 5–10 of 39 clusters
are expected to carry names (NAME-7). On segments between two anonymous
clusters nothing has changed and 0.7 still applies; paying the caution premium
there buys nothing. So the ratio is chosen per segment, by how many of the
clusters involved are named:

| winner | runner-up | ratio | what an error costs |
|---|---|---|---|
| unnamed | unnamed | 0.7 | a wrong cluster number, as today |
| named | unnamed | tighter | a named person credited with an anonymous voice's words |
| unnamed | named | tighter | a named person's words hidden under a cluster number |
| named | named | tightest | one identified person's words attributed to another |

The bottom row is the only case where the document actively misquotes one
known person as another, and it is the one worth the most caution.

## NAME-11a

The specific numbers behind "tighter" and "tightest" are **not yet derived**.
0.4 is where the ratio used to sit and is a placeholder, not a result. Setting
them properly means repeating SPEAKER-26's exercise — sample the segments each
value disagrees about and read them — against the changed question: not "is
this the right cluster" but "would I be comfortable seeing this sentence
quoted under this person's name". Do that before shipping a number, and record
it as a new ID rather than editing this one.

## NAME-12

An unnamed cluster renders exactly as it does today — "Speaker 7", not
"Unknown" and not omitted. A named one renders as the name with the cluster
retained: **"Robin (Speaker 16)"**. Keeping the cluster visible means a reader
who spots one wrong attribution can see the whole extent of what that error
covers, and it stops the document from claiming more identification than was
performed. The header's existing "labels are acoustic clusters, not names"
note must change when names are present, to say that names come from the
transcript's own words, are inferred, and carry the confidence recorded in the
sidecar.

## NAME-13

Names in a transcript of a private meeting are the most sensitive thing this
repo produces. The names sidecar goes in `output/`, which is gitignored and
stays that way (see the hard constraints in `CLAUDE.md`), and no fixture, test
or comment carries a real name from a real recording. `test_names.py` uses
synthetic names from `testlib.py`, as every other suite does.

## What not to do

## NAME-14

**Do not name from voice.** Matching a cluster to a person by their voice
requires an enrolled reference sample per person, which does not exist and
would have to be collected. SPEAKER-5 … SPEAKER-12 already measured what
acoustic features alone can do about identity on this recording.

## NAME-15

**Do not carry names between recordings.** Cluster numbers are assigned per
run and mean nothing across files; "Speaker 2" in July is not "Speaker 2" in
August. A persistent name-to-voice map is the enrolment problem in NAME-14
wearing a different hat, and getting it wrong misattributes silently and
across an archive rather than in one document.

## NAME-16

**Do not resolve a name by majority vote over many weak mentions.** NAME-5
shows the mentions are not independent enough for counting to help: the same
misattributed hand-off produces the same wrong pointer every time it recurs,
so a repeated error looks exactly like corroboration. Corroboration must come
from *different kinds* of evidence agreeing, not from more of the same kind.

## What was built

## NAME-17

**NAME-11's per-segment threshold is not implemented, and the mixed label is
why it became less urgent.** NAME-11 argued the contested ratio should tighten
where a named cluster is involved, because a wrong attribution would then
misquote a real person. SPEAKER-34 changed the premise: a contested segment
now names *every* voice it spans, so a hand-off between two named people
renders as "Wren (Speaker 2) and Robin (Speaker 7) (spans a hand-off)" and
attributes nothing to either alone. The failure NAME-11 was pricing — one
person's words appearing under another's name — is what the mixed label
already prevents.

What remains is the risk on an *uncontested* segment attributed to the wrong
named cluster, which the threshold does not govern. So the ratio stays at 0.7
for named and unnamed runs alike, and NAME-11a's undone derivation stays
undone rather than shipping a fitted number. Revisit if reading a named
transcript shows single-speaker paragraphs landing on the wrong person.

## NAME-18

`names.py gather` writes candidates and cluster shapes; Claude answers with
`naming.md`; `names.py ingest` validates before anything is written. The
validation is the point of the split: it refuses an answer that is not JSON,
that names a cluster the recording does not contain, that carries a name with
no evidence, or that uses a confidence value outside `high`/`medium`/`low`.
NAME-2 is a rule the code enforces rather than a hope about the prompt.

## NAME-19

The gather regexes are deliberately over-inclusive and are *not* the place to
improve precision. On the reference recording they return 379 mentions, of
which 2 are self-introductions and roughly half the rest are sentence adverbs
rather than people. NAME-4 established that no stop-list can fix this because
real first names are ordinary English words. Tightening the regex trades
recall — which is free here — for precision that Claude supplies better.

## NAME-20

A cluster holding under five seconds of speech is not offered as a candidate
speaker. This is a floor on triviality, not the smear test NAME-10 wants: it
excludes clusters too small to have been addressed by name, and says nothing
about whether a larger cluster is a person. Do not let it grow into a smear
test by raising the number — that rule has to come from
[smear-cluster-identification.md](smear-cluster-identification.md).

## NAME-21

A names sidecar belongs to the recording, not to a transcript of it, so it
falls back from `<stem>.repaired.names.json` to `<stem>.names.json` exactly as
the speaker sidecar does. Both use one implementation
(`diarize.find_sidecar`), because two copies of this rule would drift and the
symptom — a lookup that silently finds nothing — is one nobody notices.

## NAME-22

An evidence quote is checked against the transcript before the sidecar is
written, folding case and whitespace on both sides so a quote spanning two
segments still matches. A quote that does not occur is refused.

NAME-2 asked for evidence and got it: entries carried a `quote` key, and
nothing established that the words in it were ever spoken. That gap is not
theoretical. `naming.md` carried a worked example naming `SPEAKER_02` "Wren
Marchetti" — a plausible-looking invented name, with an invented quote to
match — and an answer that copied the example through validated cleanly,
because `SPEAKER_02` was a real cluster and a `quote` key was present. It
reached a finished deliverable and labelled 164 paragraphs with a name that
occurs nowhere in the recording, while the voice in question introduces
itself by a different name in its first sentence.

Two changes, because either alone leaves the hole open. The example in
`naming.md` is now `<…>` placeholders that describe their own contents, so a
copied template is visible on sight rather than plausible. And the check
here means invention has to at least be built from words that were actually
said. Neither makes a name *correct* — a real quote pinned to the wrong
cluster still passes, which is what NAME-5's adjacency rule is for. What they
rule out is a name resting on nothing at all.

`validate` therefore takes the transcript as a required argument rather than
an optional one. Made optional, every call site becomes a place the check can
be silently skipped, which is the same shape of bug one level up.
