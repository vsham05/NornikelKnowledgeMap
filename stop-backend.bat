@echo off
echo Stopping backend on port 8000...

powershell -NoProfile -Command ^
  "$killed = @(); " ^
  "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { " ^
  "  Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; $killed += $_.OwningProcess " ^
  "}; " ^
  "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" -ErrorAction SilentlyContinue | " ^
  "  Where-Object { $_.CommandLine -match 'run\.py|uvicorn|nornikel-backend' } | ForEach-Object { " ^
  "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $killed += $_.ProcessId " ^
  "}; " ^
  "if ($killed.Count) { $killed | Select-Object -Unique | ForEach-Object { Write-Host ('Killed PID ' + $_) } } " ^
  "else { Write-Host 'No backend process found.' }"

powershell -NoProfile -Command "Start-Sleep -Seconds 2"

netstat -ano | findstr "LISTENING" | findstr ":8000" >nul
if errorlevel 1 (
  echo Port 8000 is free.
) else (
  echo WARNING: port 8000 still in use.
  echo Close any terminal still running the backend, then run stop-backend.bat again.
  exit /b 1
)
