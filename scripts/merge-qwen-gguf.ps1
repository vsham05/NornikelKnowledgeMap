# Merge split Qwen GGUF shards into one file (required before Ollama import)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$SplitTool = Join-Path $ProjectRoot "tools\llama\llama-gguf-split.exe"
$Downloads = "C:\Users\dienh\Downloads"
$Part1 = Join-Path $Downloads "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
$Part2 = Join-Path $Downloads "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf"
$Out = Join-Path $Downloads "qwen2.5-7b-instruct-q4_k_m.gguf"

if (-not (Test-Path $SplitTool)) {
    Write-Host "Downloading llama-gguf-split..." -ForegroundColor Cyan
    $toolsDir = Join-Path $ProjectRoot "tools"
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $zip = Join-Path $toolsDir "llama-bins.zip"
    Invoke-WebRequest -Uri "https://github.com/ggml-org/llama.cpp/releases/download/b9562/llama-b9562-bin-win-cpu-x64.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath (Join-Path $toolsDir "llama") -Force
}

if (-not (Test-Path $Part1) -or -not (Test-Path $Part2)) {
    Write-Host "Missing shard files in Downloads." -ForegroundColor Red
    exit 1
}

if (Test-Path $Out) {
    Write-Host "Merged file already exists: $Out" -ForegroundColor Green
    exit 0
}

Write-Host "Merging GGUF shards (may take a few minutes)..." -ForegroundColor Cyan
Set-Location $Downloads
& $SplitTool --merge $Part1 $Out
Write-Host "Done: $Out" -ForegroundColor Green
