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

## Pitch and level alone — measured, and they do not work

The obvious cheap answer to SPEAKER-3 is to skip the model and mark turns from
features the repo can already measure: audio level, and pitch. This was tried
against a 150-minute single-microphone recording with nine identifiable
speakers. Frame-level F0 (autocorrelation, 40 ms frames at a 20 ms hop), RMS
level, spectral centroid and 85% rolloff over the whole file extract in about
8 seconds, so cost is not what rules the approach out. The results are.

## SPEAKER-5

Pitch is stable for one voice when the window holds only that voice. The
moderator, sampled at eight verified single-speaker points spread over 128
minutes, measured 138–162 Hz — a 24 Hz spread, standard deviation 8 Hz. There
is real speaker information in F0 and this is it.

## SPEAKER-6

It is nowhere near enough to separate people. Split-half measurement noise on
a single turn's F0 is ±12 Hz. Against that, eight of the nine speakers were
indistinguishable from at least one other, and four of them sat inside a 20 Hz
band. Pitch resolves "low voice" from "high voice" and essentially nothing
finer, which on a board that skews to one vocal range is close to no
information at all.

## SPEAKER-7

Level is a proxy for geometry, not identity. It scores deceptively well in
isolation, because a speaker giving a report stands in a fixed spot and each
report is therefore level-fingerprinted. The same person moves several dB
between sitting and standing to address the room, two people at the same
distance read the same, and the median voiced level of the recording drifts
across 10-minute blocks with no speaker pattern. Any detector trained on it
learns where someone stood.

## SPEAKER-8

Both features blend at exactly the moment worth detecting. Two of the ten
sampled moderator spans returned 213 Hz and 291 Hz, which is not his voice
moving: 35% and 56% of their frames sat above 250 Hz, because the window
contained the incoming speaker as well. The hand-off is where the window holds
two voices, so the feature is a weighted average of the pair precisely where
a change detector needs a step.

## SPEAKER-9

Real turns are mostly too short to measure. Median transcript segment carries
1.14 s of voiced audio; 43% carry under 1 s and 37% of segments are shorter
than 2 s. The rapid question-and-answer stretches — where attribution would
help a reader most — run 0.5–1 s per turn, which is below where any of these
features stabilise.

## SPEAKER-10

The arithmetic settles it. Across six verified hand-offs the F0 jump was 28 Hz
median, while one speaker's own window-to-window jitter was 12 Hz median and
41 Hz at the 90th percentile. A threshold placed at the median real boundary
fires on 20% of non-boundaries: in 17 minutes of single-speaker monologue that
is roughly 90 false turn marks against 6 real ones. The false alarms are not
randomly placed either — they land on emphasis and on the rising pitch that
ends a question, so the transcript is mismarked hardest in the passages a
reader is working hardest to follow. Marking fifteen turns per real turn makes
the document worse than leaving it unmarked, which is what SPEAKER-2 already
does honestly.

## SPEAKER-11

Unsupervised clustering over all four features, handed the true number of
speakers, reached 0.59 purity against 0.25 chance. A pairwise figure of 0.89
is reachable but only as an oracle: threshold fitted on the data it is scored
on, with the candidate pair of speakers given in advance. A transcript never
knows either. Treat the gap between 0.89 and 0.59 as the cost of not knowing
the answer beforehand, and do not quote the oracle number as a capability.

## SPEAKER-12

The labels behind SPEAKER-5 … SPEAKER-11 are section-level, assuming one
dominant speaker per report, with only the six hand-offs individually
verified; interjections from the floor contaminate the section spans. The
within-speaker measurements are solid, the between-speaker ones indicative.
The conclusion does not rest on the weaker half: SPEAKER-9's turn lengths and
SPEAKER-8's blending are properties of the recording, not of the labelling.

## SPEAKER-13

What would work instead is a learned speaker embedding — an x-vector or ECAPA
model, 192 dimensions of timbre and formant structure — clustered
agglomeratively, which is what `pyannote.audio` packages. It succeeds where
the above fails because it does not reduce a voice to two scalars, and because
its segmentation model is trained on overlapping speech rather than defeated
by it. On single-channel far-field audio expect a diarization error rate
around 15–25%: imperfect, and still a large improvement.

## SPEAKER-14

Compute is not the obstacle, but it is larger than a benchmark suggests.
`pyannote/speaker-diarization-3.1` over the 150-minute recording took **12.8
minutes** on the Metal backend of this machine (Apple M4, 10 cores, 16 GB),
peak RSS about 0.8 GB. The split is lopsided and worth knowing before tuning
anything: segmentation 36 s, speaker counting and discrete diarization under a
second each, and **embeddings 11 min 57 s** — 93% of the run. Anything that
changes the number of embedding windows changes the wall clock; nothing else
does. A prior estimate here of 3–5 minutes, extrapolated from shape-equivalent
stand-in models, was wrong by 3x because the stand-in assumed far fewer
embedding extractions than the pipeline actually performs. Treat model-shape
benchmarks as a floor, not a forecast. On CPU expect roughly an hour. Note
also that CPU threads past the four performance cores measured *slower* than
four, so do not raise the thread count to match the core count.

## SPEAKER-16

Measured against the section labels and verified hand-offs described in
SPEAKER-12, on one recording: mean per-section purity **0.85** across nine
report sections, four of them at 0.93 or better and two at 1.00. The moderator,
sampled at the eight verified spans of SPEAKER-5 spanning 128 minutes, landed
**88%** of his speech in a single cluster — the test that matters most, since
it is the one pitch and level fail outright. Of 3220 transcript segments,
87.7% are cleanly attributable, 10.0% are contested (a second cluster holds
more than 40% of the segment), and 2.3% carry no diarized speech at all. This
is a different order of usefulness from SPEAKER-10's fifteen-false-marks-per-
real-one, and it is what justifies the dependency.

## SPEAKER-17

Two cautions on those numbers. The apparent merge — one cluster covering both
the opening and the roads report — is most likely the labelling being wrong
rather than the diarization: that report is read aloud on an absent member's
behalf, and the moderator reading it himself is the simpler explanation. Do not
"fix" a diarizer against a label that was inferred rather than heard.
Separately, boundary timing is only approximate: at the six verified hand-offs
the nearest cluster change sat a median 6.5 s away, with two of six inside
2 s. Cluster identity is far more trustworthy than cluster onset, so
attribution should be assigned by majority overlap across a transcript
segment, never by trusting a turn boundary to the second.

## SPEAKER-18

The run produced 39 clusters. That is not self-evidently too many for a
community meeting whose floor discussion involves a long tail of residents
asking a single question each, and the distribution is consistent with it: the
top three clusters hold 52% of all speech and roughly twenty-five clusters
hold under 90 seconds apiece. Before treating the tail as over-segmentation,
check it against the recording — `max_speakers` and `num_speakers` are
available to constrain it, but constraining to a wrong count merges real
people, which is the failure SPEAKER-4 cares about. A long tail of
one-question speakers is a property of the meeting, not necessarily an error.

## SPEAKER-15

Diarization output is cluster labels, not names, which satisfies SPEAKER-4 by
construction: "Speaker 3" invents nothing. Mapping a cluster to a name is a
separate and optional judgement, and belongs with `make analyze` where the
transcript states a name aloud, leaving every unmapped cluster anonymous
rather than guessed.

## What was built

`diarize.py`, in two commands, plus `make diarize` and `make speakers`.

## SPEAKER-19

`diarize.py run` is the expensive half: it needs the audio, the model weights,
the optional install and a Hugging Face login, and it writes
`output/<stem>.speakers.json` — model, audio name, duration, device, elapsed
seconds, the cluster list, and every turn as `{start, end, speaker}`.
`diarize.py apply` is the cheap half: it reads that sidecar and a transcript,
needs neither pyannote nor the network, and can be re-run against different
thresholds for free. The split exists because only one of the two costs
anything, and because a threshold is worth changing more often than a
13-minute decode is worth repeating.

## SPEAKER-20

The sidecar is a separate file and not a column in `.timestamped.txt`. That
format is parsed by `transcribe.py`, `repair.py`, `readable.py` and every test
suite; reshaping it for a feature this new would put the established pipeline
at risk for an unestablished gain. Deleting the sidecar un-ships the feature
and nothing else notices.

## SPEAKER-21

Attribution is by majority overlap across the whole segment, never by turn
onset. SPEAKER-17 measured onsets a median 6.5 s from the truth while cluster
identity held up, so the assignment uses the reliable half of the signal and
ignores the unreliable half.

## SPEAKER-22

A segment is left unattributed when diarized speech covers less than
`--min-overlap` (0.25) of it, and marked unclear when the runner-up cluster
holds at least `--contested-ratio` (0.4) of the winner's share. Whisper cuts
segments on silence, not on turns, so a segment routinely spans a hand-off;
naming only the louder half of one would be a confident wrong answer, which
SPEAKER-4 rules out. Both are flags rather than constants because the right
value is a judgement about a particular recording.

## SPEAKER-23

An unclear segment breaks a speaker run rather than joining either side of
it. Folding it into a neighbour would print one person's words under another
person's name, which is the exact failure the whole feature is constrained to
avoid.

## SPEAKER-24

Rendered labels are cluster numbers — `SPEAKER_07` reads as "Speaker 7" — and
the document says in its own header that the labels are acoustic clusters and
not names, so a reader is never invited to believe a person has been
identified. An unclear turn is labelled as spanning a hand-off and does not
show a speaker number at all.

## SPEAKER-25

On the recording behind SPEAKER-16, `apply` attributes 86.2% of 3220
segments, marks 9.9% unclear and leaves 3.9% unattributed. `test_diarize.py`
covers the overlap arithmetic, the two thresholds, grouping, labelling, the
counts and the CLI's refusals; it stubs the pipeline entirely and never
touches the network, so `make test` stays free. The `run` path itself —
loading pyannote and calling it — is verified by reading and by having been
run, not by a test.

## Choosing the contested ratio by reading, not by argument

SPEAKER-22 set `--contested-ratio` to 0.4 on reasoning alone. Sweeping it and
reading the segments each value disagrees about says 0.4 was too strict.

## SPEAKER-26

The default is **0.7**. Across 0.2–0.9 the count marked unclear falls from 480
segments to 75, and the words under an unclear label from 10.9% of the
transcript to 1.3%. Moving 0.4 → 0.7 attributes 180 more segments, 971 words,
4.2% of the transcript. Of those 180, 155 (86%) land on a speaker at least one
neighbouring segment already holds, which is corroboration the threshold
itself does not use; reading all 25 that do not, four or five look wrong. That
is roughly 3% of the segments moved and about 0.1% of the transcript's words,
against 180 fewer interruptions in the document. The share landing on a
speaker neither neighbour holds is flat at 14–16% right across 0.5–0.9, so
there is no knee in the curve to find — the number is a judgement about how
much unclear-marking is worth paying, and this is where the reading put it.

## SPEAKER-27

What makes that trade cheap is that a wrong answer here is a wrong *cluster
number*. Nobody is misquoted by name; a reader sees "Speaker 24" where
"Speaker 2" belonged and loses a little continuity. The moment cluster labels
become names — see [speaker-naming.md](speaker-naming.md) — the cost of the
same error changes completely, and the ratio should come back down toward 0.4.
The threshold is priced on the anonymity of the label, so anything that
removes the anonymity invalidates the price.

## SPEAKER-28

Contested segments are short: median 4 words against 7 for attributed ones,
and 38% of them are three words or fewer, against 13%. Marking them unclear
therefore costs little content and a great deal of continuity — at 0.4, 48 of
the 320 unclear segments sat between two segments of the *same* speaker, so
they broke a run without marking any real boundary at all.

## What the 39 clusters turned out to be

SPEAKER-18 asked for the cluster tail to be checked against the recording
before treating it as over-segmentation. It has been. The answer is that the
tail is not one thing, and neither the "real long tail" reading nor the
"over-segmentation" reading was right on its own.

## SPEAKER-29

Ten clusters hold at least 80% of their speech inside a single five-minute
window. Reading them confirms the SPEAKER-18 hypothesis for these: each is one
resident making one contribution and then falling silent — one raising a
fairness objection over four minutes, one thanking a committee over 1.6
minutes, one reporting a right-of-way problem. Each reads as a single coherent
person on a single topic. These are real people, they are correctly separated,
and they hold 7.4% of the speech between them. Capping `max_speakers` would
merge them into whoever they sound nearest, which is the SPEAKER-4 failure
exactly.

## SPEAKER-30

A handful at the other end are not people. `SPEAKER_37` holds 27 seconds over
67 turns — 0.41 s each — scattered across the full 149 minutes with no core
anywhere; `SPEAKER_36` and `SPEAKER_38` are the same shape at 0.69 s and
0.85 s per turn. What lands in them is one- and two-word backchannel —
agreement noises, acknowledgements, half-audible asides — from no consistent
direction. They are what is left over when short interjections cannot be
matched to anyone, not a voice. Note the convergence
with SPEAKER-26: the handful of attributions that reading suggests are wrong
land disproportionately on exactly these clusters.

## SPEAKER-31

So the count is inflated, but not by an amount `max_speakers` can remove.
Constraining the count merges the *nearest* clusters, and a smear cluster is
not near anything — it is near everything. Both failure modes coexist and a
single number cannot separate them. Leave the count unconstrained. The
tractable fix is downstream, at naming time: a cluster with sub-second mean
turns and no temporal core must never be given a name, because it is not a
person to name. Concentration alone does not identify these — the moderator
scores 11.6% because he genuinely recurs all meeting — so the test needs low
concentration *and* a short mean turn. **See SPEAKER-42: stated as a rule with
numbers in it, this does not work, and the cut points here are not
established.**

## Naming both voices instead of neither

SPEAKER-22 and SPEAKER-24 discard the speaker entirely on a contested segment,
printing "unclear — spans a hand-off". That throws away a measurement in order
to avoid a guess, and the two are not the same thing.

## SPEAKER-34

A contested segment is one the diarizer says holds speech from two clusters.
That is not an inference about which of them spoke — it is what was measured.
So the honest label is **both of them**: "Speakers 2 and 24 — spans a
hand-off". Nothing is fabricated, because nothing is claimed beyond what the
overlap arithmetic already established, and a reader learns who the segment is
between instead of only that it is between someone. The previous wording was
more cautious than the evidence required, which is its own kind of inaccuracy.

## SPEAKER-35

The set is **the winner plus every cluster holding at least
`contested_ratio` of the winner's share** — exactly the clusters that made the
segment contested in the first place. Defining it this way rather than with a
second threshold means there is one number to reason about, and the label can
never disagree with the flag that produced it: if a segment is contested,
the set has at least two members, and if it is not, the question never arises.
Ordering is by share, descending.

## SPEAKER-36

This changes what the SPEAKER-26 threshold is trading. A contested segment
used to be an information hole, so the ratio was pressed upward to make fewer
of them. Now it carries the pair, and marking one costs a broken run rather
than a lost fact — which suggested tightening the ratio had become cheaper
than SPEAKER-26 priced it. SPEAKER-39 tested that and it did not hold.

## SPEAKER-37

Consecutive contested segments sharing the same set of clusters group into one
turn, as consecutive segments sharing one speaker already do. Without this a
long hand-off fragments into a row of identical "Speakers 2 and 24" turns.
SPEAKER-23 still holds: a contested run never merges into the attributed
speaker on either side of it, because that is the failure the flag exists to
prevent.

## SPEAKER-38

Clusters that SPEAKER-31 identifies as smears are still listed when they are
in the set. Suppressing them would hide the fact that the segment is contested
*by* a fragment cluster, which is exactly what a reader deciding how much to
trust the label needs to see. The exclusion in NAME-10 applies to giving a
cluster a name, not to admitting it was measured.

## The ratio was re-derived under the mixed label, and did not move

SPEAKER-36 predicted the threshold should tighten once a contested segment
named both voices instead of neither. The sampling was redone on that basis.
The prediction was wrong, and the reason is worth more than the number.

## SPEAKER-39

**The default stays at 0.7.** Sweeping 0.3 to 0.9 and scoring each band by how
suspect the *added* name is — either it is a smear cluster, or both
neighbouring segments are the winner, so the mark interrupts a continuous run
— gives 33–49% suspect **in every band**, with no trend and no knee. Reading
eighteen of the 180 segments that 0.4 marks and 0.7 does not is worse than the
mechanical score suggests: three or four are genuine hand-offs and the rest
are one continuous sentence with a second cluster bleeding across its edge.
Lowering the ratio does not buy better marks, only more marks of the same
mixture, plus a choppier document. Since the proportion that is noise is
constant, fewer is better, and 0.7 is where the volume is defensible without
losing the clearest hand-offs. Raising it further to 0.8 drops 34 marks of
which 41% were suspect — too marginal to justify churning the default.

## SPEAKER-40

The ratio cannot discriminate here, and SPEAKER-17 already said why: cluster
onset sits a median **6.5 s** from the truth, while a Whisper segment runs
about 2 s. The diarizer's boundary error is *larger than the thing being
measured*, so overlap at a segment edge carries almost no evidence about
whether a hand-off happened there — a 0.6 s runner-up in a 1.6 s segment is
exactly what pure onset error produces. No threshold over that overlap can
separate a real second voice from a misplaced boundary, which is why every
band scores the same. Improving this means a better boundary, not a better
threshold. Do not sweep this parameter again expecting a different answer.

## SPEAKER-41

An absolute floor on the runner-up was tried as a way out and does not escape
the same problem. Runner-up duration does rise with the ratio — median 0.13 s
below 0.2, against 0.9 s above 0.7 — so the ratio really is tracking *something*.
But onset error is itself on the order of seconds, so a runner-up of 0.5–1.5 s
is fully consistent with a boundary in the wrong place, and a duration cut
removes the same mixture the ratio does. It is not a second, independent
signal.

## SPEAKER-42

**Correction to SPEAKER-31.** That statement claims a smear cluster is
identified by a sub-two-second mean turn together with low concentration.
Computed over this recording, that rule selects `SPEAKER_22`, `SPEAKER_24` and
`SPEAKER_38` — and misses `SPEAKER_36` and `SPEAKER_37`, the two most obvious
smears in the file, whose concentration lands at 30.1% and 34.0% against a
30% cut. It also selects `SPEAKER_24`, which holds 272 s over 80 attributed
segments and reads as a real recurring participant. The *shape* described in
SPEAKER-30 is real; the cut points are not established, they sit knife-edge on
the clearest cases, and anything tuned until it selects the right five here is
fitted to one file — the oracle-threshold trap SPEAKER-11 already names. Do
not ship an automatic smear test on this evidence. NAME-10 depends on one and
must be treated as unbuilt until the rule is derived from more than one
recording. The work this needs, and why one recording cannot do it, is
[smear-cluster-identification.md](smear-cluster-identification.md) — pick it
up when a second meeting has been diarized.

## SPEAKER-43

This leaves SPEAKER-38 standing by necessity rather than by argument: smear
clusters are listed in a mix because they cannot yet be identified reliably
enough to exclude, not because listing them was shown to help. 26% of the
segments contested at 0.7 name a smear, and 14% are contested *only* by one —
those would become plain attributed segments under a working exclusion. That
is the largest single improvement available to this feature, and it is blocked
on SPEAKER-42, not on the threshold.

## Where the speaker-marked transcript lives

## SPEAKER-32

`readable.py --speakers` marks the deliverable itself, rather than the
speakers living only in `diarize.py apply`'s separate document. Two full
transcripts of one meeting differing only in markup is a worse outcome than
one document that carries both the summary and the speakers, and the reader
should not have to choose which of two files to read. Paragraphs break where
the speaker changes as well as where the room went quiet, which replaces
SPEAKER-2's approximation with a real turn boundary wherever one is known.

## SPEAKER-33

It is opt-in and degrades to exactly the old behaviour. Without `--speakers`,
`readable.py` neither imports `diarize` nor reads a sidecar, so the deliverable
still builds in a virtualenv that never installed the optional dependency —
which is most of them. With `--speakers` and no sidecar it stops and says so
rather than quietly producing an unlabelled document that looks like it
worked. `diarize.py apply` stays, because tuning a threshold should not mean
re-running the summary step.
