# Pull required Ollama models for Scientific Tangle
Write-Host "Pulling LLM: qwen2.5:7b-instruct" -ForegroundColor Cyan
ollama pull qwen2.5:7b-instruct

Write-Host "Pulling embeddings: mxbai-embed-large" -ForegroundColor Cyan
ollama pull mxbai-embed-large

Write-Host ""
Write-Host "Installed models:" -ForegroundColor Green
ollama list

Write-Host ""
Write-Host "Test API:" -ForegroundColor Yellow
Write-Host "  curl http://localhost:11434/v1/models"
