# Transcript analysis with Claude

`check` and `fix` apply rules. This is for the judgement calls they cannot
make: whether a gap over loud audio is dropped speech or a round of applause,
whether a repaired window came back better than what it replaced, which of the
remaining findings is worth spending compute on.

## ANALYZE-1

`make analyze` substitutes the resolved audio and transcript paths into
`analyze.md` and hands the result to the `claude` CLI. The substitution is done
by `prompt.py`, not by a `sed` expression inside the recipe: `@AUDIO@` and
`@TRANSCRIPT@` are replaced with the literal paths, whatever characters those
contain, and the rendered prompt goes to stdout for the recipe to pass on.

## ANALYZE-2

`PRINT=1` runs it headless and prints its findings; the default is an
interactive session seeded with the prompt.

## ANALYZE-3

`PROMPT=<file>` asks something else entirely with the same wiring.

## ANALYZE-4

Missing prompt file or missing `claude` on `PATH` fails with a message naming
what is missing, before anything is read.

## ANALYZE-5

The prompt is a file in the repo rather than a here-doc, so it can be read,
reviewed and edited like anything else. It is the part of this repo that
encodes judgement rather than rules, and it is expected to change as more is
learned about how a recording fails.

## ANALYZE-6

`analyze.md` directs the reader to measure rather than skim — importing
`transcribe` and computing over the segments beats reading 3000 lines into
context — and states explicitly what not to do, since the expensive mistakes
here are actions (re-running the pipeline, decoding every gap) rather than
omissions.

## ANALYZE-7

Because rendering is a module rather than a shell fragment, it is testable:
`test_prompt.py` covers it. A prompt that silently lost a placeholder, or that
broke on a path containing a character the shell or `sed` reads as syntax, is a
Claude session spent reasoning about the wrong file.
