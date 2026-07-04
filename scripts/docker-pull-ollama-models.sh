#!/bin/sh
set -eu

MODELS="${OLLAMA_PULL_MODELS:-qwen2.5:7b-instruct,mxbai-embed-large,minicpm-v}"
HOST="${OLLAMA_HOST:-http://ollama:11434}"

echo "Waiting for Ollama at $HOST ..."
until ollama list >/dev/null 2>&1; do
  sleep 2
done

echo "Pulling models: $MODELS"
IFS=,
for model in $MODELS; do
  model=$(echo "$model" | tr -d ' ')
  [ -z "$model" ] && continue
  echo "-> ollama pull $model"
  ollama pull "$model"
done

echo "Ollama models ready:"
ollama list
