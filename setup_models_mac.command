#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v ollama >/dev/null 2>&1; then
  echo 'Ollama is missing. Install from https://ollama.com/download/mac, then run again.'
  exit 1
fi
if ! curl -sf --max-time 3 'http://127.0.0.1:11434/api/tags' >/dev/null 2>&1; then
  open -a Ollama >/dev/null 2>&1 || (ollama serve >/dev/null 2>&1 &)
  sleep 3
fi
RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
if [ "$RAM_GB" -ge 32 ]; then MODEL='qwen3.6:27b'; elif [ "$RAM_GB" -ge 20 ]; then MODEL='qwen3.5:9b'; else MODEL='qwen3.5:4b'; fi
if [ ! -f .env ]; then
  cp .env.example .env
  if [ "$MODEL" != 'qwen3.6:27b' ]; then
    sed -i '' "s/^ANSWER_MODEL=.*/ANSWER_MODEL=$MODEL/" .env
  fi
  echo "Created local configuration. Model: $MODEL"
else
  echo 'Existing .env retained. No user settings were overwritten.'
fi
# Install the memory-appropriate model, independent of a preserved older .env.
echo "Mac memory ${RAM_GB}GB — ensuring $MODEL is installed locally."
ollama pull "$MODEL"
ollama pull qwen3-embedding:0.6b
if ! command -v tesseract >/dev/null 2>&1; then
  echo 'Optional for scanned documents: brew install tesseract'
fi
echo 'Models ready. Launch: ./run_mac.command'
