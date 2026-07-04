#!/bin/sh
# Fail if Ollama runs inference on CPU (full or partial).
set -u

HOST="${OLLAMA_HOST:-http://ollama:11434}"
PROBE_MODEL="${OLLAMA_GPU_PROBE_MODEL:-qwen3:8b}"
export OLLAMA_HOST="$HOST"

echo "Verifying Ollama GPU inference (probe: $PROBE_MODEL) ..."

if ! ollama show "$PROBE_MODEL" >/dev/null 2>&1; then
  echo "ERROR: probe model $PROBE_MODEL not found"
  exit 1
fi

# Warm load — must complete on GPU
if ! ollama run "$PROBE_MODEL" "ok" >/dev/null 2>&1; then
  echo "ERROR: probe inference failed for $PROBE_MODEL"
  exit 1
fi

sleep 1
ps_out=$(ollama ps 2>/dev/null || true)
echo "$ps_out"

if [ -z "$ps_out" ] || ! echo "$ps_out" | tail -n +2 | grep -q .; then
  echo "ERROR: ollama ps shows no loaded model after probe"
  exit 1
fi

if echo "$ps_out" | grep -i CPU >/dev/null 2>&1; then
  echo "ERROR: Ollama is using CPU — this stack requires GPU-only inference."
  echo "Check Docker GPU passthrough and VRAM (RTX 3070 Ti 8GB should fit qwen3:8b)."
  exit 1
fi

if ! echo "$ps_out" | grep -i GPU >/dev/null 2>&1; then
  echo "ERROR: ollama ps does not report GPU — cannot confirm GPU-only mode."
  exit 1
fi

echo "OK: Ollama inference is GPU-only."
