Set-Location $PSScriptRoot\..

Write-Host "Starting LexusAI dashboard at http://127.0.0.1:8000"
Write-Host "Press Ctrl+C to stop."

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
