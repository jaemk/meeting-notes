VENV   := .venv
PYTHON := $(VENV)/bin/python

# Override with INPUT=<file> or env var
INPUT  ?= $(firstword $(wildcard input.*))
# OUTPUT is the stem — script appends .txt / .srt / .timestamped.txt
# Override with OUTPUT=my_name or env var
OUTPUT ?= transcript

# Pass extra flags: make ARGS="--model large-v3 --backend openai"
ARGS   ?= --model large-v2 -c 1 -l en

.PHONY: all transcribe fix test setup clean distclean

all: transcribe

transcribe: $(PYTHON)
	@test -n "$(INPUT)" || { echo "Error: no file matching 'input.*' found — pass INPUT=<file>"; exit 1; }
	$(PYTHON) transcribe.py $(INPUT) --output $(OUTPUT) $(ARGS)

# Re-transcribe bad windows and splice them into $(OUTPUT).timestamped.txt.
#   make fix WINDOWS="-w 20:47-21:09 -w 1:49:54-1:50:21"
#   make fix WINDOWS="-w 20:47-21:09" DRY=1        # preview only
#   make fix WINDOWS="-w 20:47-21:09" IN_PLACE=1   # overwrite (keeps a .bak)
fix: $(PYTHON)
	@test -n "$(INPUT)" || { echo "Error: no file matching 'input.*' found — pass INPUT=<file>"; exit 1; }
	@test -n "$(WINDOWS)" || { echo "Error: pass WINDOWS=\"-w START-END [-w ...]\""; exit 1; }
	$(PYTHON) transcribe.py $(INPUT) --merge $(OUTPUT).timestamped.txt \
		$(WINDOWS) $(ARGS) $(if $(IN_PLACE),--in-place,) $(if $(DRY),--dry-run,)

test: $(PYTHON)
	$(PYTHON) test_transcribe.py

$(PYTHON):
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --quiet --upgrade pip
	$(PYTHON) -m pip install --quiet mlx-whisper openai-whisper

setup: $(PYTHON)

clean:
	rm -f $(OUTPUT).txt $(OUTPUT).timestamped.txt $(OUTPUT).srt

distclean: clean
	rm -rf $(VENV)
