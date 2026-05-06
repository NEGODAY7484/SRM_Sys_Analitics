Param(
  [string]$Python = "python",
  [string]$VenvDir = ".venv"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $root "..")
Set-Location $repo

if (-not (Test-Path $VenvDir)) {
  & $Python -m venv $VenvDir
}

$py = Join-Path $VenvDir "Scripts\\python.exe"

& $py -m pip install -U pip

if (Test-Path "requirements.txt") {
  & $py -m pip install -r "requirements.txt"
} else {
  & $py -m pip install -e ".[dev,api,report]"
}

New-Item -ItemType Directory -Force -Path "data","uploads","outputs","outputs\\logs" | Out-Null

if (-not (Test-Path ".env")) {
  Write-Host "WARN: .env not found. Copy .env.example -> .env and edit for your server."
}

$hostVal = if ($env:HOST) { $env:HOST } else { "0.0.0.0" }
$portVal = if ($env:PORT) { $env:PORT } else { "8000" }

& $py -m uvicorn srm.api.app:app --host $hostVal --port $portVal

