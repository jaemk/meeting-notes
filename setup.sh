#!/usr/bin/env bash
#
# The single place the environment is built. `make setup` calls this; the
# Makefile does not install anything itself.
#
#   ./setup.sh            create/refresh .venv
#   ./setup.sh --force    recreate it from scratch
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

echo "=== Whisper transcription setup ==="

PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python:   $PYTHON ($PY_VERSION)"

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

echo "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

echo "Installing openai-whisper (CPU backend)..."
"$PIP" install --quiet openai-whisper

if [ "$APPLE_SILICON" = 1 ]; then
    echo "Apple Silicon detected — installing mlx-whisper (GPU backend)..."
    "$PIP" install --quiet mlx-whisper
    BACKEND="mlx (Apple Silicon GPU, ~5-10x faster than CPU)"
else
    echo "Not Apple Silicon — skipping mlx-whisper, openai/CPU backend will be used."
    BACKEND="openai (CPU)"
fi

# Record what was installed so `make` knows the venv is current.
"$VENV/bin/python" -c "import whisper" >/dev/null
touch "$VENV/.setup-complete"

cat <<EOF

=== Setup complete ===

Default backend: $BACKEND

Usage:
  make transcribe INPUT=recording.m4a    transcribe, then auto-repair defects
  make check TRANSCRIPT=transcript.timestamped.txt
  make fix INPUT=recording.m4a           re-run the repair pass on its own
  make test

Or directly:
  .venv/bin/python transcribe.py recording.m4a
  .venv/bin/python transcribe.py recording.m4a --model large-v3 -l en
  .venv/bin/python repair.py diagnose recording.m4a transcript.timestamped.txt

Models (fastest -> most accurate):
  tiny   ~1x realtime    good for quick drafts
  base   ~2x realtime    decent accuracy
  small  ~4x realtime    solid general purpose
  medium ~6x realtime    high accuracy
  large-v3               best accuracy, slowest
EOF
