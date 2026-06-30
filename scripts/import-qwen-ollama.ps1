# Import local Qwen 2.5 7B GGUF into Ollama
# Prerequisite: merged single file at C:\Users\dienh\Downloads\qwen2.5-7b-instruct-q4_k_m.gguf
# If you only have split files, run merge first (see merge-qwen-gguf.ps1)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Modelfile = Join-Path $ProjectRoot "models\qwen2.5-7b-instruct\Modelfile"
$Merged = "C:\Users\dienh\Downloads\qwen2.5-7b-instruct-q4_k_m.gguf"

if (-not (Test-Path $Merged)) {
    Write-Host "Merged model not found: $Merged" -ForegroundColor Red
    Write-Host "Run: .\scripts\merge-qwen-gguf.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "Creating Ollama model: qwen2.5-7b-instruct" -ForegroundColor Cyan
ollama create qwen2.5-7b-instruct -f $Modelfile

Write-Host "Pulling embedding model..." -ForegroundColor Cyan
ollama pull mxbai-embed-large

Write-Host ""
Write-Host "Models ready:" -ForegroundColor Green
ollama list

Write-Host ""
Write-Host "Test chat:" -ForegroundColor Yellow
Write-Host '  ollama run qwen2.5-7b-instruct "Hello"'
