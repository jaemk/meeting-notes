#!/usr/bin/env bash
#
# The single place the environment is built. `make setup` calls this; the
# Makefile does not install anything itself.
#
#   ./setup.sh            create/refresh .venv
#   ./setup.sh --force    recreate it from scratch
#
# Environment:
#   PYTHON=/path/to/python3.12   build the venv from a specific interpreter
#   ALLOW_UNTESTED_PYTHON=1      proceed on a Python newer than this was tested on
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

# openai-whisper needs 3.9+, and pulls in numba, whose wheels lag new Python
# releases by months. Both ends are checked here so a bad interpreter is a
# sentence rather than a compiler error thirty seconds into a pip install.
MIN_PY_MINOR=9
MAX_TESTED_PY_MINOR=13

die() { printf 'Error: %s\n' "$1" >&2; exit 1; }

usage() {
    cat <<'EOF'
usage: ./setup.sh [--force]

  --force     delete .venv and rebuild it from scratch
  -h, --help  show this message

Environment:
  PYTHON=<interpreter>       build the venv from a specific python3
  ALLOW_UNTESTED_PYTHON=1    proceed on a Python newer than this was tested on
EOF
}

# One optional argument, and a typo is an error rather than a silent non-force
# run: `./setup.sh --froce` used to look like it had rebuilt the venv.
FORCE=0
case "${1:-}" in
    "")         ;;
    --force)    FORCE=1 ;;
    -h|--help)  usage; exit 0 ;;
    *)          printf 'Error: unknown option %s\n\n' "$1" >&2; usage >&2; exit 1 ;;
esac
[ "$#" -le 1 ] || die "expected at most one argument, got $#"

echo "=== Whisper transcription setup ==="

# ── Prerequisites, before anything is installed ────────────────────────────────
# Both checks are up front on purpose: each of them otherwise surfaces minutes
# later, as a numba build failure or as a bare FileNotFoundError in the middle
# of a decode.

PYTHON="${PYTHON:-}"
[ -n "$PYTHON" ] || PYTHON=$(command -v python3 || command -v python || true)
[ -n "$PYTHON" ] || die "no python3 found on PATH — install Python ${MIN_PY_MINOR}+ or set PYTHON=<interpreter>"

read -r PY_MAJOR PY_MINOR <<<"$("$PYTHON" -c 'import sys; print(sys.version_info.major, sys.version_info.minor)')"
PY_VERSION="$PY_MAJOR.$PY_MINOR"
echo "Python:   $PYTHON ($PY_VERSION)"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt "$MIN_PY_MINOR" ]; }; then
    die "Python $PY_VERSION is too old — openai-whisper needs 3.$MIN_PY_MINOR or newer.
       Install a newer Python, or point this at one: PYTHON=/path/to/python3 ./setup.sh"
fi

if [ "$PY_MAJOR" -gt 3 ] || [ "$PY_MINOR" -gt "$MAX_TESTED_PY_MINOR" ]; then
    if [ "${ALLOW_UNTESTED_PYTHON:-0}" != 1 ]; then
        die "Python $PY_VERSION is newer than this was tested on (3.$MIN_PY_MINOR–3.$MAX_TESTED_PY_MINOR).
       openai-whisper pulls in numba, whose wheels appear months after a Python
       release; without one, pip tries to compile it and fails.
       Use an older interpreter:  PYTHON=/path/to/python3.$MAX_TESTED_PY_MINOR ./setup.sh
       Or try anyway:             ALLOW_UNTESTED_PYTHON=1 ./setup.sh"
    fi
    echo "Warning:  Python $PY_VERSION is newer than tested (3.$MIN_PY_MINOR–3.$MAX_TESTED_PY_MINOR) — continuing on request."
fi

# ffmpeg and ffprobe are not optional. transcribe.py measures the recording
# with ffprobe, cuts every chunk and every repair window with ffmpeg, and
# repair.py measures the audio under a gap with it. A missing binary is not a
# degraded mode — it is a FileNotFoundError partway into a run.
MISSING=""
for tool in ffmpeg ffprobe; do
    command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
    cat >&2 <<EOF
Error: required tool(s) not on PATH:$MISSING

  ffprobe  reads the recording's duration
  ffmpeg   finds the silences chunks are cut at, extracts every chunk and
           repair window, and measures the audio under a gap so a pause is
           not mistaken for dropped speech

Install them and run this again:

  macOS:          brew install ffmpeg
  Debian/Ubuntu:  sudo apt install ffmpeg
  Fedora:         sudo dnf install ffmpeg
EOF
    exit 1
fi
echo "Audio:    $(command -v ffmpeg), $(command -v ffprobe)"

OS=$(uname -s)
ARCH=$(uname -m)
echo "Platform: $OS/$ARCH"

# mlx is Apple's Metal framework — it only builds and runs on M-series Macs.
# Everywhere else openai-whisper on the CPU is the only option, and installing
# mlx-whisper would either fail outright or pull a package that can never load.
APPLE_SILICON=0
if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
    APPLE_SILICON=1
fi

if [ "$FORCE" = 1 ] && [ -d "$VENV" ]; then
    echo "Removing existing venv (--force)..."
    rm -rf "$VENV"
fi

if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
[ -f "$REQUIREMENTS" ] || die "requirements.txt not found next to setup.sh"

echo "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

# requirements.txt pins openai-whisper unconditionally and mlx-whisper behind
# a PEP 508 environment marker (Apple Silicon only), so one install command
# is correct everywhere — pip silently skips the mlx-whisper line wherever
# the marker doesn't match rather than failing.
echo "Installing pinned dependencies from requirements.txt..."
"$PIP" install --quiet -r "$REQUIREMENTS"

if [ "$APPLE_SILICON" = 1 ]; then
    echo "Apple Silicon detected — mlx-whisper (GPU backend) installed."
    BACKEND="mlx (Apple Silicon GPU, ~5-10x faster than CPU)"
else
    echo "Not Apple Silicon — mlx-whisper skipped, openai/CPU backend will be used."
    BACKEND="openai (CPU)"
fi

# Record what was installed so `make` knows the venv is current.
"$VENV/bin/python" -c "import whisper" >/dev/null
touch "$VENV/.setup-complete"

cat <<EOF

=== Setup complete ===

Default backend: $BACKEND

No model weights were downloaded here. The first decode fetches them — a few
hundred MB for a small model, a couple of GB for large — so the first run
pauses after "Split into N chunks" while the download runs. It is cached
afterwards.

Speaker diarization is NOT installed — it is optional and costs 1-2 GB. The
transcription pipeline does not need it. To add it later, see the header of
requirements-diarize.txt, which also covers the Hugging Face steps pip cannot
do for you:
  .venv/bin/pip install -r requirements-diarize.txt

Usage:
  make transcribe INPUT=local/audio.m4a  transcribe, then auto-repair defects
  make check INPUT=local/audio.m4a       what is left in the transcript
  make fix INPUT=local/audio.m4a         re-run the repair pass on its own
  make readable INPUT=local/audio.m4a    the document a person actually reads
  make test
  make help                              every target and its options

Or directly:
  .venv/bin/python transcribe.py audio.m4a
  .venv/bin/python transcribe.py audio.m4a --model large-v3 -l en
  .venv/bin/python repair.py diagnose audio.m4a audio.timestamped.txt

Models (fastest -> most accurate). The multiplier is decode time against the
length of the recording on the CPU backend, so "6x" means about six hours of
compute for a one-hour recording — slower than realtime, not faster. Apple
Silicon with mlx is roughly 5-10x quicker than these.

  tiny      ~1x the recording's length   good for quick drafts
  base      ~2x                          decent accuracy
  small     ~4x                          solid general purpose
  medium    ~6x                          high accuracy (transcribe.py default)
  large-v3  slower still                 best accuracy (what make uses: large-v2)

Read README.md's "What a run costs" before starting a long recording.
EOF
