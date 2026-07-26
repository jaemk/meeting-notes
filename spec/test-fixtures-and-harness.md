# Test fixtures and harness

The suite must run on a fresh clone, with no recording present and nothing
private committed.

## TEST-1

Both fixtures are synthetic and built by `testlib.py` into `output/`: a
transcript with a known loop, rewind and gap planted in neutral filler, and
thirty seconds of ffmpeg-generated tone and silence for the gap classifier.

## TEST-2

Every number the tests assert is a property of the fixture generator, not of
anybody's meeting. Real output is never checked in as a fixture.

## TEST-3

Decoding is stubbed throughout, so the suite finishes in seconds.

## TEST-4

The only thing that may skip is audio-backed gap classification, when `ffmpeg`
is unavailable.

## TEST-5

The transcript fixture's rewind deliberately encodes the *inverse* of the
real-world seam case: there the loop buries speech that was transcribed
correctly, so the text after the jump is the real one. Any change that starts
trimming it is wrong, and the fixture exists to catch exactly that.

## TEST-6

Check names read as sentences about behaviour rather than as function names,
because the failure output is the first thing read when something breaks.

## TEST-7

`make test` runs `test_transcribe.py`, `test_repair.py` and `test_readable.py`.

## TEST-8

A bug that turns out to be an ordering or interaction problem gets a regression
test that fails under the old order. Those are the ones that come back.
