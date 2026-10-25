param(
    [switch] $SkipBackend,
    [switch] $SkipFrontend,
    [switch] $Unpacked
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

try {
    $npmCommand = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if (-not $npmCommand) { throw 'Node.js LTS ve npm gerekli.' }

    $builderPath = Join-Path $projectRoot 'node_modules\.bin\electron-builder.cmd'
    if (-not (Test-Path -LiteralPath $builderPath)) {
        Write-Host 'Masaustu derleme bilesenleri kuruluyor...' -ForegroundColor Cyan
        if (Test-Path -LiteralPath (Join-Path $projectRoot 'package-lock.json')) {
            & $npmCommand.Source ci
        }
        else {
            & $npmCommand.Source install
        }
        if ($LASTEXITCODE -ne 0) { throw 'Node bagimliliklari kurulamadi.' }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules\electron\dist\electron.exe'))) {
        Write-Host 'Masaustu calisma ortami indiriliyor...' -ForegroundColor Cyan
        & node (Join-Path $projectRoot 'node_modules\electron\install.js')
        if ($LASTEXITCODE -ne 0) { throw 'Electron calisma ortami indirilemedi.' }
    }

    if (-not $SkipFrontend) {
        Write-Host 'Arayuz derleniyor...' -ForegroundColor Cyan
        & $npmCommand.Source run build
        if ($LASTEXITCODE -ne 0) { throw 'Arayuz derlemesi basarisiz.' }
    }

    if (-not $SkipBackend) {
        Write-Host 'Bagimsiz video motoru hazirlaniyor...' -ForegroundColor Cyan
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build-backend.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Video motoru paketlenemedi.' }
    }

    $licenseCollector = Join-Path $PSScriptRoot 'collect_licenses.py'
    if (Test-Path -LiteralPath $licenseCollector) {
        Write-Host 'Ucuncu taraf lisanslari toplaniyor...' -ForegroundColor Cyan
        $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Lisans toplamak icin .venv Python ortami gerekli.' }
        & $venvPython $licenseCollector
        if ($LASTEXITCODE -ne 0) { throw 'Ucuncu taraf lisanslari toplanamadi.' }
    }

    foreach ($requiredPath in @(
        'dist\index.html',
        'public\demo.mp4',
        'build\backend\dikey-backend\dikey-backend.exe',
        'build\backend\ffmpeg\ffmpeg.exe',
        'build\backend\ffmpeg\ffprobe.exe',
        'electron\assets\icon.ico',
        'LICENSES',
        'THIRD_PARTY_NOTICES.md'
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $requiredPath))) {
            throw "Paketleme icin gerekli dosya eksik: $requiredPath"
        }
    }

    Write-Host 'Windows masaustu paketi olusturuluyor...' -ForegroundColor Cyan
    $builderArguments = @('--config', 'electron-builder.yml', '--win', '--x64', '--publish', 'never')
    if ($Unpacked) { $builderArguments += '--dir' }
    & $builderPath @builderArguments
    if ($LASTEXITCODE -ne 0) { throw 'Windows paketi olusturulamadi.' }

    Write-Host "Hazir: $(Join-Path $projectRoot 'release')" -ForegroundColor Green
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
