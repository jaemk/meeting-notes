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
# Prompts are files rather than here-docs so they can be read, reviewed and
# edited like anything else in the repo. @AUDIO@/@TRANSCRIPT@ are filled in.
PROMPT         ?= analyze.md
SUMMARY_PROMPT ?= summarize.md

.PHONY: all transcribe check fix analyze readable test setup clean distclean

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

# The document a person actually reads: an executive summary and a topic-by-
# topic list of outcomes, follow-ups and owners, written by Claude from the
# transcript, with the paragraphed transcript underneath it.
#
# Two explicit steps, and the summary is the one that costs anything. It is
# kept as its own file so it can be re-read, edited by hand, or regenerated
# without rebuilding the document — and so a bad summary is obvious rather than
# buried in the middle of a 23,000-word file.
#
#   make readable                    summarise, then assemble
#   make readable NO_SUMMARY=1       transcript only, no Claude, no cost
#   make readable SUMMARY_PROMPT=<f> ask for a different summary
readable: $(STAMP)
	$(need_transcript)
ifndef NO_SUMMARY
	@test -f "$(SUMMARY_PROMPT)" || { echo "Error: no prompt at '$(SUMMARY_PROMPT)'"; exit 1; }
	@command -v $(CLAUDE) >/dev/null || { echo "Error: '$(CLAUDE)' not on PATH — see https://claude.com/claude-code"; exit 1; }
	@echo "Summarising $(TRANSCRIPT) with $(CLAUDE) …"
	@$(CLAUDE) -p "$$(cat $(SUMMARY_PROMPT))" < $(TRANSCRIPT) > $(OUTPUT).summary.md
	@test -s $(OUTPUT).summary.md || { echo "Error: the summary came back empty"; exit 1; }
	@echo "Saved: $(OUTPUT).summary.md"
endif
	$(PYTHON) readable.py $(TRANSCRIPT) --output $(OUTPUT).readable.md \
		$(if $(NO_SUMMARY),,--summary $(OUTPUT).summary.md)

test: $(STAMP)
	$(PYTHON) test_transcribe.py
	$(PYTHON) test_repair.py
	$(PYTHON) test_readable.py

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
