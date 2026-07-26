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

.PHONY: all transcribe check fix test setup clean distclean

all: transcribe

define need_input
@test -n "$(INPUT)" || { echo "Error: no local/input.* found — pass INPUT=local/<file>"; exit 1; }
endef

define need_transcript
@test -f "$(TRANSCRIPT)" || { echo "Error: no transcript at '$(TRANSCRIPT)' — pass INPUT=local/<audio> or TRANSCRIPT=<file>"; exit 1; }
endef

# Transcribe, then automatically diagnose → repair → re-check.
# Pass NO_REPAIR=1 to stop after the raw transcription.
transcribe: $(STAMP)
	$(need_input)
	$(PYTHON) transcribe.py $(INPUT) --output $(OUTPUT) $(ARGS) \
		$(if $(NO_REPAIR),--no-repair,)

# Report loops/gaps in an existing transcript. Exits nonzero if any remain.
check: $(STAMP)
	$(need_transcript)
	$(PYTHON) repair.py verify $(TRANSCRIPT) $(if $(INPUT),--audio $(INPUT),)

# Run the repair pass on its own, against an existing transcript.
#   make fix                                  repair every defect it finds
#   make fix WINDOWS="-w 20:47-21:09"         repair only these stretches
#   make fix DRY=1                            preview, decode nothing
#   make fix IN_PLACE=1                       overwrite $(TRANSCRIPT), keeps a .bak
fix: $(STAMP)
	$(need_input)
	$(need_transcript)
	$(PYTHON) repair.py repair $(INPUT) $(TRANSCRIPT) $(FIX_ARGS) $(WINDOWS) \
		$(if $(IN_PLACE),--in-place,) $(if $(DRY),--dry-run,)

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
