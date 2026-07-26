#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "=== Whisper Transcription Setup ==="
echo

# Check for Python 3.9+
PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PYTHON ($PY_VERSION)"

# Create venv
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"

echo "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

echo "Installing mlx-whisper (Apple Silicon GPU backend)..."
"$PIP" install --quiet mlx-whisper

echo "Installing openai-whisper (CPU fallback)..."
"$PIP" install --quiet openai-whisper

echo
echo "=== Setup complete ==="
echo
echo "Usage:"
echo "  .venv/bin/python transcribe.py <audio_file>"
echo "  .venv/bin/python transcribe.py <audio_file> --model large-v3"
echo "  .venv/bin/python transcribe.py <audio_file> --backend openai --model small"
echo "  .venv/bin/python transcribe.py <audio_file> --timestamps"
echo
echo "Models (fastest → most accurate):"
echo "  tiny   ~1x realtime    good for quick drafts"
echo "  base   ~2x realtime    decent accuracy"
echo "  small  ~4x realtime    solid general purpose"
echo "  medium ~6x realtime    high accuracy"
echo "  large-v3               best accuracy, slowest"
echo
echo "Tip: mlx backend (default) uses your M-series GPU and is ~5-10x faster than CPU."
