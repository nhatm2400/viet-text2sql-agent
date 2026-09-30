# Explicit opt-in setup. Downloads official portable runtime + qwen3:4b; no paid API.
# All runtime/model files stay in git-ignored data/ollama_local; no system PATH changes.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$installRoot = Join-Path $projectRoot 'data/ollama_local'
if (Test-Path -LiteralPath $installRoot) {
    throw 'Setup directory already exists. Inspect the existing runtime instead of overwriting it.'
}
$existing = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if ($existing) { throw 'Port 11434 already in use; reuse or inspect the existing server first.' }
$release = Invoke-RestMethod 'https://api.github.com/repos/ollama/ollama/releases/latest'
$asset = $release.assets | Where-Object { $_.name -eq 'ollama-windows-amd64.zip' }
if (-not $asset -or -not $asset.digest -or -not $asset.digest.StartsWith('sha256:')) {
    throw 'Official release has no usable SHA256 digest; stop for manual verification.'
}
New-Item -ItemType Directory -Path $installRoot | Out-Null
$archive = Join-Path $installRoot 'runtime.zip'
$runtime = Join-Path $installRoot 'runtime'
$modelPath = Join-Path $installRoot 'models'
Write-Output "Downloading $($release.tag_name), $([math]::Round($asset.size / 1GB, 2)) GB runtime archive"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive
$actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $asset.digest.Substring(7).ToLowerInvariant()) { throw 'Runtime hash mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath $runtime
$exePath = Join-Path $runtime 'ollama.exe'
$env:OLLAMA_MODELS = $modelPath
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$server = Start-Process -FilePath $exePath -ArgumentList 'serve' -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $installRoot 'server.out.log') -RedirectStandardError (Join-Path $installRoot 'server.err.log')
@{version=$release.tag_name; sha256=$actualHash; server_pid=$server.Id; model='qwen3:4b'; model_path=$modelPath} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installRoot 'installation.json') -Encoding utf8
$ready = $false
for ($i=0; $i -lt 30; $i++) {
    try {
        $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version'
        $ready = $true
        break
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw 'Ollama did not start; inspect server.err.log' }
Write-Output 'Pulling qwen3:4b (approximately 2.5 GB); progress is in pull.log'
& $exePath pull 'qwen3:4b' *> (Join-Path $installRoot 'pull.log')
if ($LASTEXITCODE -ne 0) { throw 'Model download failed; inspect pull.log' }
Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' | ConvertTo-Json -Depth 6
