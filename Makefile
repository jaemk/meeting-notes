VENV   := .venv
PYTHON := $(VENV)/bin/python
STAMP  := $(VENV)/.setup-complete

# Input audio. Override with INPUT=<file> or an env var.
INPUT  ?= $(firstword $(wildcard input.*) $(wildcard local/input.*))
# OUTPUT is the stem — the script appends .txt / .srt / .timestamped.txt
OUTPUT ?= transcript
# The transcript that check/fix operate on
TRANSCRIPT ?= $(OUTPUT).timestamped.txt

# Extra flags: make ARGS="--model large-v3 --backend openai"
ARGS     ?= --model large-v2 -c 1 -l en
# repair.py takes no --chunk-size, so `fix` gets its own defaults
FIX_ARGS ?= --model large-v2 -l en

.PHONY: all transcribe check fix test setup clean distclean

all: transcribe

define need_input
@test -n "$(INPUT)" || { echo "Error: no file matching 'input.*' found — pass INPUT=<file>"; exit 1; }
endef

# Transcribe, then automatically diagnose → repair → re-check.
# Pass NO_REPAIR=1 to stop after the raw transcription.
transcribe: $(STAMP)
	$(need_input)
	$(PYTHON) transcribe.py $(INPUT) --output $(OUTPUT) $(ARGS) \
		$(if $(NO_REPAIR),--no-repair,)

# Report loops/gaps in an existing transcript. Exits nonzero if any remain.
check: $(STAMP)
	$(PYTHON) repair.py verify $(TRANSCRIPT) $(if $(INPUT),--audio $(INPUT),)

# Run the repair pass on its own, against an existing transcript.
#   make fix                                  repair every defect it finds
#   make fix WINDOWS="-w 20:47-21:09"         repair only these stretches
#   make fix DRY=1                            preview, decode nothing
#   make fix IN_PLACE=1                       overwrite $(TRANSCRIPT), keeps a .bak
fix: $(STAMP)
	$(need_input)
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

clean:
	rm -f $(OUTPUT).txt $(OUTPUT).timestamped.txt $(OUTPUT).srt \
	      $(OUTPUT).repaired.* $(OUTPUT).*.bak

distclean: clean
	rm -rf $(VENV)
