VENV   := .venv
PYTHON := $(VENV)/bin/python
STAMP  := $(VENV)/.setup-complete

# ── Quoting ────────────────────────────────────────────────────────────────────
# Recording names arrive from wherever the audio came from — a phone, a
# download, an AirDrop, a sync folder — so every path expanded into a recipe is
# untrusted text. $(call sq,VALUE) wraps it in single quotes and escapes any
# quote it already contains, which makes it exactly one shell word no matter
# what is in it: "Bob's standup.m4a" is a filename, not four arguments and a
# syntax error.
#
# ARGS, FIX_ARGS and WINDOWS are the deliberate exceptions further down: they
# are several options in one variable and must stay unquoted, so they are
# trusted input — typed by whoever ran make, never derived from a filename.
sq = '$(subst ','\'',$(1))'

# Audio lives in local/, everything written lands in output/. Both are
# gitignored, so no recording and no transcript ever reaches the repo.
INPUT  ?= $(firstword $(wildcard local/input.*))

# The transcript keeps the recording's name: local/2026-07-25.m4a writes
# output/2026-07-25.txt, .timestamped.txt and .srt.
# Derived with the shell rather than $(notdir)/$(basename) because make's
# functions split their argument on spaces, and "team sync.m4a" is a normal
# name for a recording.
STEM = $(if $(INPUT),$(shell f=$(call sq,$(INPUT)); f=$${f\#\#*/}; \
                            printf 'output/%s' "$${f%.*}"),)

# The transcript check/fix/readable operate on. `repair.py repair` writes a
# ".repaired" stem (repair.py:624 → transcribe.save_output), so once a repair
# has run, output/NAME.repaired.timestamped.txt is the current transcript and
# the unrepaired one still sitting beside it is not. Preferring it here is what
# stops `make check` re-reporting the defects `make fix` just repaired, and
# stops `make readable` paying Claude to summarise the pre-repair text.
#
# `make fix` repairs whatever TRANSCRIPT names, so a second `make fix` repairs
# the repair. Pass TRANSCRIPT=output/NAME.timestamped.txt to go back to the
# original.
REPAIRED = $(STEM).repaired.timestamped.txt
TRANSCRIPT ?= $(if $(STEM),$(shell test -f $(call sq,$(REPAIRED)) \
                             && printf '%s' $(call sq,$(REPAIRED)) \
                             || printf '%s' $(call sq,$(STEM).timestamped.txt)),)

# Where this recording's outputs are written. With no INPUT — `make readable
# TRANSCRIPT=output/NAME.timestamped.txt` is a normal way to run it — it comes
# from the transcript instead, so the summary lands next to the transcript
# rather than in the hidden file output/.summary.md.
# Stripped in the shell for the same reason as STEM: $(patsubst) works word by
# word, so it would quietly rewrite the spacing of a name it is only supposed
# to be taking an extension off. Same three extensions as transcribe.output_stem.
# (No parentheses in here: make counts them when it looks for the end of
# $(shell ...), so a `case` would close the function early.)
OUTPUT ?= $(if $(STEM),$(STEM),$(shell t=$(call sq,$(TRANSCRIPT)); \
	for e in .timestamped.txt .srt .txt; do \
		if [ x"$${t%$$e}" != x"$$t" ]; then t=$${t%$$e}; break; fi; \
	done; printf '%s' "$$t"))

# Extra flags: make ARGS="--model large-v3 --backend openai"
# These REPLACE the defaults rather than adding to them (?=), so anything you
# still want has to be repeated.
# -c 1 keeps every decode down to about a minute, which is what stops Whisper
# looping. transcribe passes it on to its own repair pass; `fix` sets the same
# thing explicitly so a standalone repair slices its windows identically.
ARGS     ?= --model large-v2 -c 1 -l en
FIX_ARGS ?= --model large-v2 -c 1 -l en

CLAUDE ?= claude
# Prompts are files rather than here-docs so they can be read, reviewed and
# edited like anything else in the repo. @AUDIO@/@TRANSCRIPT@ are filled in by
# prompt.py, which reads their values from the environment — see the analyze
# recipe for why that is not a stylistic preference.
PROMPT         ?= analyze.md
SUMMARY_PROMPT ?= summarize.md

.PHONY: help all transcribe check fix analyze readable test setup clean distclean

# A bare `make` used to mean `all: transcribe`, which on a fresh clone spent
# several minutes and several hundred megabytes on setup before announcing that
# it had no audio to work on.
.DEFAULT_GOAL := help

help:
	@printf '%s\n' \
	'meeting-notes — transcribe a recording, then repair what Whisper got wrong.' \
	'' \
	'  make transcribe INPUT=local/audio.m4a   transcribe, then diagnose, repair and re-check' \
	'  make check      INPUT=local/audio.m4a   report what is still wrong; nonzero if anything is' \
	'  make fix        INPUT=local/audio.m4a   re-decode the defective stretches only' \
	'  make analyze    INPUT=local/audio.m4a   hand the transcript to Claude for the judgement calls' \
	'  make readable   INPUT=local/audio.m4a   the document a person reads: summary + transcript' \
	'  make test                               run the four test suites, decoding stubbed' \
	'  make setup                              build the venv and install the models' \
	'  make clean      INPUT=local/audio.m4a   delete this recording'"'"'s outputs, nothing else' \
	'  make distclean  CONFIRM=1               delete the venv and EVERY transcript in output/' \
	'' \
	'Variables:' \
	'  INPUT       the recording. Defaults to the first local/input.* if there is one.' \
	'  TRANSCRIPT  the transcript to work on. Defaults to this recording'"'"'s repaired' \
	'              transcript if one exists, otherwise its plain one.' \
	'  OUTPUT      output stem. Derived from INPUT, or from TRANSCRIPT if INPUT is unset.' \
	'  ARGS        flags for transcribe.py    (REPLACES the default $(ARGS))' \
	'  FIX_ARGS    flags for repair.py repair (REPLACES the default $(FIX_ARGS))' \
	'  WINDOWS     restrict fix to given stretches, e.g. WINDOWS="-w 20:47-21:09"' \
	'  GAPS=1      also treat dropped speech as a defect, in check and fix alike' \
	'  DRY=1       fix previews its windows and decodes nothing' \
	'  IN_PLACE=1  fix overwrites TRANSCRIPT, keeping a .bak' \
	'  NO_REPAIR=1 transcribe stops after the raw transcription' \
	'  PRINT=1     analyze runs one-shot and prints its findings instead of opening a session' \
	'  NO_SUMMARY=1 readable assembles the transcript only — no Claude, no cost' \
	'  CONFIRM=1   required by distclean, which is otherwise unrecoverable' \
	'' \
	'ARGS and FIX_ARGS replace rather than append: `make fix FIX_ARGS="--strict"`' \
	'drops the -c 1 -l en that keeps each decode short. Pass them again.'

all: transcribe

# A path is only allowed to look like a path. Quoting alone would be enough for
# the recipes below, but local/ is a folder things get dropped into, and a file
# called `input.a;id>/tmp/OWNED.m4a` becoming this Makefile's INPUT is not a
# mistake somebody made — so it is refused rather than carefully handled.
# An apostrophe is fine: real meetings are called things like "Bob's standup".
define refuse_unsafe
@printf '%s' $(call sq,$(2)) | LC_ALL=C grep -q '[;&|<>$$`"\\*?!{}~^[:cntrl:]]' \
	&& { echo "Error: $(1) contains a character this Makefile will not hand to a shell:"; \
	     printf '  %s\n' $(call sq,$(2)); exit 1; } || true
endef

# The value is never interpolated into the message either: an error message is
# shell text like any other, and `echo "no transcript at $(TRANSCRIPT)"` hands a
# name containing a double quote exactly the escape it needs. printf takes it as
# an argument instead.
define need_input
@test -n $(call sq,$(INPUT)) || { echo "Error: no local/input.* found — pass INPUT=local/<file>"; exit 1; }
$(call refuse_unsafe,INPUT,$(INPUT))
endef

define need_transcript
@test -f $(call sq,$(TRANSCRIPT)) || { \
	echo "Error: no transcript here — pass INPUT=local/<audio> or TRANSCRIPT=<file>:"; \
	printf '  %s\n' $(call sq,$(TRANSCRIPT)); exit 1; }
$(call refuse_unsafe,TRANSCRIPT,$(TRANSCRIPT))
endef

# Everything written is named after OUTPUT, so a bare "output/" would quietly
# write the deliverables to output/.summary.md and output/.readable.md — paid
# for, and invisible to ls.
define need_output
@case $(call sq,$(OUTPUT)) in "" | */) \
	echo "Error: no output stem — pass INPUT=local/<audio> or TRANSCRIPT=<file>"; exit 1;; esac
$(call refuse_unsafe,OUTPUT,$(OUTPUT))
endef

# GAPS=1 widens every target from "the repetitions Whisper produced" to "those
# plus the stretches it produced nothing for". It means the same thing to all
# three targets below, so the check keeps agreeing with the repair.
GAPS_FLAG = $(if $(GAPS),--include-gaps,)

# Transcribe, then automatically diagnose → repair → re-check.
# Pass NO_REPAIR=1 to stop after the raw transcription.
transcribe: $(STAMP)
	$(need_input)
	$(need_output)
	$(PYTHON) transcribe.py $(call sq,$(INPUT)) --output $(call sq,$(OUTPUT)) \
		$(ARGS) $(GAPS_FLAG) $(if $(NO_REPAIR),--no-repair,)

# Report loops (and with GAPS=1, gaps) in an existing transcript.
# Exits nonzero if any remain.
check: $(STAMP)
	$(need_transcript)
	$(PYTHON) repair.py verify $(call sq,$(TRANSCRIPT)) \
		$(if $(INPUT),--audio $(call sq,$(INPUT)),) $(GAPS_FLAG)

# Run the repair pass on its own, against an existing transcript.
#   make fix                                  re-decode the repetitions it finds
#   make fix GAPS=1                           re-decode dropped speech as well
#   make fix WINDOWS="-w 20:47-21:09"         repair only these stretches
#   make fix DRY=1                            preview, decode nothing
#   make fix IN_PLACE=1                       overwrite $(TRANSCRIPT), keeps a .bak
# FIX_ARGS and WINDOWS are several arguments in one variable, so they are the
# two expansions here that are deliberately unquoted. They come from whoever
# ran make, never from a filename.
fix: $(STAMP)
	$(need_input)
	$(need_transcript)
	$(PYTHON) repair.py repair $(call sq,$(INPUT)) $(call sq,$(TRANSCRIPT)) \
		$(FIX_ARGS) $(WINDOWS) $(GAPS_FLAG) \
		$(if $(IN_PLACE),--in-place,) $(if $(DRY),--dry-run,)

# Hand the transcript to Claude with the reasoning needed to review it: what the
# chunked merge does to timestamps, which side of a seam is lying, and which
# defects are worth a decode. `check` and `fix` apply the rules; this is for the
# judgement calls they can't make — whether a gap is really dropped speech,
# whether a repair came back worse, what to do about it.
#
#   make analyze                       interactive session, seeded with the prompt
#   make analyze PRINT=1               one-shot, prints its findings and exits
#   make analyze PROMPT=<file>         ask something else entirely
#
# The filenames reach prompt.py through MN_AUDIO/MN_TRANSCRIPT — as data in the
# environment, not as text inside a program. This recipe used to fill the
# placeholders in with `sed -e 's|@AUDIO@|$(INPUT)|g'`, which put the recording's
# name inside a sed script inside a $( ) inside double quotes: an apostrophe or
# a semicolon in the name ended the expression and the rest of the name ran as
# a command. The $( ) that is left substitutes the *rendered prompt*, and its
# result is never re-parsed by the shell.
#
# The assignments sit inside the $( ), not in front of $(CLAUDE): a shell
# performs the assignments of a command only after it has expanded that
# command's arguments, so prompt.py would run without them.
analyze: $(STAMP)
	$(need_input)
	$(need_transcript)
	@test -f $(call sq,$(PROMPT)) || { echo "Error: no prompt at:"; \
		printf '  %s\n' $(call sq,$(PROMPT)); exit 1; }
	@command -v $(CLAUDE) >/dev/null || { echo "Error: '$(CLAUDE)' not on PATH — see https://claude.com/claude-code"; exit 1; }
	$(CLAUDE) $(if $(PRINT),-p,) \
		"$$(MN_AUDIO=$(call sq,$(INPUT)) MN_TRANSCRIPT=$(call sq,$(TRANSCRIPT)) \
		    $(PYTHON) prompt.py $(call sq,$(PROMPT)))"

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
	$(need_output)
ifndef NO_SUMMARY
	@test -f $(call sq,$(SUMMARY_PROMPT)) || { echo "Error: no prompt at:"; \
		printf '  %s\n' $(call sq,$(SUMMARY_PROMPT)); exit 1; }
	@command -v $(CLAUDE) >/dev/null || { echo "Error: '$(CLAUDE)' not on PATH — see https://claude.com/claude-code"; exit 1; }
	@printf 'Summarising %s with $(CLAUDE) …\n' $(call sq,$(TRANSCRIPT))
# Written beside the summary and moved into place only once it is non-empty.
# Redirecting straight onto the summary truncates it before Claude has said
# anything, so an error, a timeout or a ^C destroyed the previous good summary —
# the one file here that costs money and can be worth hand-editing.
	@$(CLAUDE) -p "$$(cat $(call sq,$(SUMMARY_PROMPT)))" \
		< $(call sq,$(TRANSCRIPT)) > $(call sq,$(OUTPUT).summary.md.tmp)
	@test -s $(call sq,$(OUTPUT).summary.md.tmp) || { \
		rm -f $(call sq,$(OUTPUT).summary.md.tmp); \
		printf 'Error: the summary came back empty — %s is unchanged\n' \
			$(call sq,$(OUTPUT).summary.md); exit 1; }
	@mv $(call sq,$(OUTPUT).summary.md.tmp) $(call sq,$(OUTPUT).summary.md)
	@printf 'Saved: %s\n' $(call sq,$(OUTPUT).summary.md)
endif
	$(PYTHON) readable.py $(call sq,$(TRANSCRIPT)) \
		--output $(call sq,$(OUTPUT).readable.md) \
		$(if $(NO_SUMMARY),,--summary $(call sq,$(OUTPUT).summary.md))

test: $(STAMP)
	$(PYTHON) test_transcribe.py
	$(PYTHON) test_repair.py
	$(PYTHON) test_readable.py
	$(PYTHON) test_prompt.py

# setup.sh owns every install step; the Makefile only decides when to call it.
$(STAMP): setup.sh
	./setup.sh

setup:
	./setup.sh

# Only this recording's outputs — other transcripts in output/ are left alone.
# The globs stay outside the quotes so they are still globs; only the stem,
# which is the part that came from a filename, is quoted.
clean:
	$(need_input)
	$(need_output)
	rm -f $(call sq,$(OUTPUT).txt) $(call sq,$(OUTPUT).timestamped.txt) \
	      $(call sq,$(OUTPUT).srt) $(call sq,$(OUTPUT).summary.md) \
	      $(call sq,$(OUTPUT).readable.md) \
	      $(call sq,$(OUTPUT)).repaired.* $(call sq,$(OUTPUT)).*.bak

# Not "remove build products": this deletes every transcript of every recording,
# each of which cost minutes to hours of decoding and none of which can be
# regenerated without the audio. Hence CONFIRM=1.
distclean:
	@test "$(CONFIRM)" = "1" || { \
	  printf '%s\n' "Refusing: distclean deletes the venv and EVERY transcript in output/," \
	    "including recordings other than this one, each of which cost minutes to" \
	    "hours of decoding. Re-run with CONFIRM=1 if that is really what you want," \
	    "or use 'make clean' for one recording."; exit 1; }
	@case $(call sq,$(VENV)) in "" | / | . | .. | /* | *..*) \
	  printf 'Error: refusing to rm -rf VENV=%s\n' $(call sq,$(VENV)); exit 1;; esac
	rm -rf $(call sq,$(VENV))
	find output -type f ! -name .gitkeep -delete
