#!/bin/sh
set -u

MODELS="${OLLAMA_PULL_MODELS:-qwen2.5:7b-instruct,mxbai-embed-large,minicpm-v}"
HOST="${OLLAMA_HOST:-http://ollama:11434}"
MAX_RETRIES="${OLLAMA_PULL_RETRIES:-5}"

echo "Waiting for Ollama at $HOST ..."
until ollama list >/dev/null 2>&1; do
  sleep 2
done

model_present() {
  ollama show "$1" >/dev/null 2>&1
}

pull_with_retry() {
  model="$1"
  attempt=1
  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if ollama pull "$model"; then
      return 0
    fi
    echo "Pull failed for $model (attempt $attempt/$MAX_RETRIES), retrying in 15s ..."
    sleep 15
    attempt=$((attempt + 1))
  done
  return 1
}

echo "Pulling models: $MODELS"
failed=""
IFS=,
for model in $MODELS; do
  model=$(echo "$model" | tr -d ' ')
  [ -z "$model" ] && continue

  if model_present "$model"; then
    echo "-> $model already present, skipping"
    continue
  fi

  echo "-> ollama pull $model"
  if ! pull_with_retry "$model"; then
    failed="$failed $model"
  fi
done

echo ""
echo "Ollama models:"
ollama list

missing=""
IFS=,
for model in $MODELS; do
  model=$(echo "$model" | tr -d ' ')
  [ -z "$model" ] && continue
  if ! model_present "$model"; then
    missing="$missing $model"
  fi
done

if [ -n "$missing" ]; then
  echo "ERROR: missing models:$missing"
  exit 1
fi

if [ -n "$failed" ]; then
  echo "Recovered after retries; all required models are present."
fi

# Force GPU-only layer offload on every pulled model (num_gpu 999 in Modelfile).
if [ -f /patch-gpu.sh ]; then
  sh /patch-gpu.sh || exit 1
fi

# Refuse to start the stack if Ollama falls back to CPU.
if [ -f /verify-gpu.sh ]; then
  sh /verify-gpu.sh || exit 1
fi

echo "All models ready."
