#!/bin/sh
# Re-create each Ollama model with PARAMETER num_gpu 999 so layers never spill to CPU.
set -u

MODELS="${OLLAMA_PULL_MODELS:-qwen3:8b,mxbai-embed-large,minicpm-v}"

patch_one() {
  model="$1"
  safe=$(echo "$model" | tr ':/' '__')
  tmp="/tmp/modelfile-${safe}"
  staging="${model}-gpu"

  if ! ollama show "$model" >/dev/null 2>&1; then
    echo "WARN: cannot patch $model (not present)"
    return 0
  fi

  {
    echo "FROM ${model}"
    echo "# GPU-only: all transformer layers on GPU (no CPU fallback)"
    echo "PARAMETER num_gpu 999"
  } >"$tmp"

  echo "-> patching $model (num_gpu 999)"
  if ! ollama create "$staging" -f "$tmp"; then
    echo "ERROR: failed to stage GPU patch for $model"
    return 1
  fi
  if ! ollama cp "$staging" "$model"; then
    echo "ERROR: failed to apply GPU patch to $model"
    ollama rm "$staging" 2>/dev/null || true
    return 1
  fi
  ollama rm "$staging" 2>/dev/null || true
  rm -f "$tmp"
  return 0
}

echo "Patching models for GPU-only inference ..."
IFS=,
for model in $MODELS; do
  model=$(echo "$model" | tr -d ' ')
  [ -z "$model" ] && continue
  patch_one "$model" || exit 1
done

echo "GPU-only model patch complete."
