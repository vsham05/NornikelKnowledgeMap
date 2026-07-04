# Pull Ollama models for Scientific Tangle (tiered for ~90% Yandex parity)
param(
    [ValidateSet("premium", "standard", "light", "all")]
    [string]$Tier = "standard"
)

function Pull-Model($name) {
    Write-Host "Pulling $name ..." -ForegroundColor Cyan
    ollama pull $name
}

Write-Host "Scientific Tangle — Ollama model setup" -ForegroundColor Green
Write-Host "  premium  = qwen2.5:32b-instruct (~88% Yandex context, 24GB+ VRAM)" -ForegroundColor DarkGray
Write-Host "  standard = qwen2.5:14b-instruct (~44% context, 16GB VRAM) [default]" -ForegroundColor DarkGray
Write-Host "  light    = qwen2.5:7b-instruct (fast, lower recall)" -ForegroundColor DarkGray
Write-Host ""

switch ($Tier) {
    "premium" {
        Pull-Model "qwen2.5:32b-instruct"
    }
    "standard" {
        Pull-Model "qwen2.5:14b-instruct"
    }
    "light" {
        Pull-Model "qwen2.5:7b-instruct"
    }
    "all" {
        Pull-Model "qwen2.5:32b-instruct"
        Pull-Model "qwen2.5:14b-instruct"
        Pull-Model "qwen2.5:7b-instruct"
    }
}

Write-Host "Pulling embeddings: mxbai-embed-large" -ForegroundColor Cyan
ollama pull mxbai-embed-large

Write-Host "Pulling vision model for image tables: minicpm-v" -ForegroundColor Cyan
ollama pull minicpm-v

Write-Host ""
Write-Host "Installed models:" -ForegroundColor Green
ollama list

Write-Host ""
Write-Host "Set in nornikel-backend/.env:" -ForegroundColor Yellow
Write-Host "  VLM_MODEL=minicpm-v   (image table OCR during ingest)"
switch ($Tier) {
    "premium" { Write-Host "  LLM_MODEL=qwen2.5:32b-instruct" }
    "standard" { Write-Host "  LLM_MODEL=qwen2.5:14b-instruct" }
    "light" { Write-Host "  LLM_MODEL=qwen2.5:7b-instruct" }
    default { Write-Host "  LLM_MODEL=qwen2.5:14b-instruct  (or :32b for best parity)" }
}
