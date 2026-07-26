VENV   := .venv
PYTHON := $(VENV)/bin/python
STAMP  := $(VENV)/.setup-complete

# Audio lives in local/, everything written lands in output/. Both are
# gitignored, so no recording and no transcript ever reaches the repo.
INPUT  ?= $(firstword $(wildcard local/input.*))
# The transcript keeps the recording's name: local/2026-07-25.m4a writes
# output/2026-07-25.txt, .timestamped.txt and .srt.
OUTPUT ?= output/$(basename $(notdir $(INPUT)))
# The transcript that check/fix operate on
TRANSCRIPT ?= $(OUTPUT).timestamped.txt

# Extra flags: make ARGS="--model large-v3 --backend openai"
# -c 1 keeps every decode down to about a minute, which is what stops Whisper
# looping. transcribe passes it on to its own repair pass; `fix` sets the same
# thing explicitly so a standalone repair slices its windows identically.
ARGS     ?= --model large-v2 -c 1 -l en
FIX_ARGS ?= --model large-v2 -c 1 -l en

CLAUDE ?= claude
# The prompt is a file rather than a here-doc so it can be read, reviewed and
# edited like anything else in the repo. @AUDIO@/@TRANSCRIPT@ are filled in.
PROMPT ?= analyze.md

.PHONY: all transcribe check fix analyze test setup clean distclean

all: transcribe

define need_input
@test -n "$(INPUT)" || { echo "Error: no local/input.* found — pass INPUT=local/<file>"; exit 1; }
endef

define need_transcript
@test -f "$(TRANSCRIPT)" || { echo "Error: no transcript at '$(TRANSCRIPT)' — pass INPUT=local/<audio> or TRANSCRIPT=<file>"; exit 1; }
endef

# GAPS=1 widens every target from "the repetitions Whisper produced" to "those
# plus the stretches it produced nothing for". It means the same thing to all
# three targets below, so the check keeps agreeing with the repair.
GAPS_FLAG = $(if $(GAPS),--include-gaps,)

# Transcribe, then automatically diagnose → repair → re-check.
# Pass NO_REPAIR=1 to stop after the raw transcription.
transcribe: $(STAMP)
	$(need_input)
	$(PYTHON) transcribe.py $(INPUT) --output $(OUTPUT) $(ARGS) $(GAPS_FLAG) \
		$(if $(NO_REPAIR),--no-repair,)

# Report loops (and with GAPS=1, gaps) in an existing transcript.
# Exits nonzero if any remain.
check: $(STAMP)
	$(need_transcript)
	$(PYTHON) repair.py verify $(TRANSCRIPT) $(if $(INPUT),--audio $(INPUT),) \
		$(GAPS_FLAG)

# Run the repair pass on its own, against an existing transcript.
#   make fix                                  re-decode the repetitions it finds
#   make fix GAPS=1                           re-decode dropped speech as well
#   make fix WINDOWS="-w 20:47-21:09"         repair only these stretches
#   make fix DRY=1                            preview, decode nothing
#   make fix IN_PLACE=1                       overwrite $(TRANSCRIPT), keeps a .bak
fix: $(STAMP)
	$(need_input)
	$(need_transcript)
	$(PYTHON) repair.py repair $(INPUT) $(TRANSCRIPT) $(FIX_ARGS) $(WINDOWS) \
		$(GAPS_FLAG) $(if $(IN_PLACE),--in-place,) $(if $(DRY),--dry-run,)

# Hand the transcript to Claude with the reasoning needed to review it: what the
# chunked merge does to timestamps, which side of a seam is lying, and which
# defects are worth a decode. `check` and `fix` apply the rules; this is for the
# judgement calls they can't make — whether a gap is really dropped speech,
# whether a repair came back worse, what to do about it.
#
#   make analyze                       interactive session, seeded with the prompt
#   make analyze PRINT=1               one-shot, prints its findings and exits
#   make analyze PROMPT=<file>         ask something else entirely
analyze: $(STAMP)
	$(need_input)
	$(need_transcript)
	@test -f "$(PROMPT)" || { echo "Error: no prompt at '$(PROMPT)'"; exit 1; }
	@command -v $(CLAUDE) >/dev/null || { echo "Error: '$(CLAUDE)' not on PATH — see https://claude.com/claude-code"; exit 1; }
	$(CLAUDE) $(if $(PRINT),-p,) "$$(sed -e 's|@AUDIO@|$(INPUT)|g' \
		-e 's|@TRANSCRIPT@|$(TRANSCRIPT)|g' $(PROMPT))"

test: $(STAMP)
	$(PYTHON) test_transcribe.py
	$(PYTHON) test_repair.py

# setup.sh owns every install step; the Makefile only decides when to call it.
$(STAMP): setup.sh
	./setup.sh

setup:
	./setup.sh

# Only this recording's outputs — other transcripts in output/ are left alone.
clean:
	$(need_input)
	rm -f $(OUTPUT).txt $(OUTPUT).timestamped.txt $(OUTPUT).srt \
	      $(OUTPUT).repaired.* $(OUTPUT).*.bak

distclean:
	rm -rf $(VENV)
	find output -type f ! -name .gitkeep -delete
