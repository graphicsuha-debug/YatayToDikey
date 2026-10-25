param(
    [string]$PythonPath = '',
    [string]$FFmpegDir = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Build Python was not found. Create .venv and install requirements.txt first.'
}
if (-not $FFmpegDir) {
    $FFmpegDir = $env:DIKEY_FFMPEG_DIR
}
if (-not $FFmpegDir) {
    $LocalFFmpeg = Join-Path $ProjectRoot 'build\ffmpeg'
    if ((Test-Path -LiteralPath (Join-Path $LocalFFmpeg 'ffmpeg.exe')) -and (Test-Path -LiteralPath (Join-Path $LocalFFmpeg 'ffprobe.exe'))) {
        $FFmpegDir = $LocalFFmpeg
    }
}
if (-not $FFmpegDir) {
    $FFmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $FFmpegCommand) { throw 'FFmpeg is required on the build machine.' }
    $FFmpegDir = Split-Path -Parent $FFmpegCommand.Source
}
$FFmpegSource = Join-Path $FFmpegDir 'ffmpeg.exe'
$FFprobeSource = Join-Path $FFmpegDir 'ffprobe.exe'
foreach ($RequiredBinary in @($FFmpegSource, $FFprobeSource)) {
    if (-not (Test-Path -LiteralPath $RequiredBinary -PathType Leaf)) {
        throw "Required build binary was not found: $RequiredBinary"
    }
}

Push-Location $ProjectRoot
try {
    & $PythonPath -m pip install -r requirements.txt -r backend/requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & $PythonPath -m PyInstaller --noconfirm --clean --distpath build/backend --workpath build/pyinstaller packaging/backend.spec
    if ($LASTEXITCODE -ne 0) { throw 'Backend executable build failed.' }

    $BundledFFmpeg = Join-Path $ProjectRoot 'build\backend\ffmpeg'
    New-Item -ItemType Directory -Force -Path $BundledFFmpeg | Out-Null
    Copy-Item -LiteralPath $FFmpegSource -Destination (Join-Path $BundledFFmpeg 'ffmpeg.exe') -Force
    Copy-Item -LiteralPath $FFprobeSource -Destination (Join-Path $BundledFFmpeg 'ffprobe.exe') -Force
    if (Test-Path -LiteralPath (Join-Path $FFmpegDir 'SOURCE-SHA256SUMS.txt') -PathType Leaf) {
        # The reproducible minimal distribution carries its complete build and
        # license records alongside the two binaries. Preserve every record.
        Get-ChildItem -LiteralPath $FFmpegDir | Where-Object { $_.Name -notin @('ffmpeg.exe', 'ffprobe.exe') } | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $BundledFFmpeg -Recurse -Force
        }
    }
    $DistributionRoot = $FFmpegDir
    if (-not (Test-Path -LiteralPath (Join-Path $DistributionRoot 'LICENSE') -PathType Leaf)) {
        $DistributionRoot = Split-Path -Parent $FFmpegDir
    }
    foreach ($LicenseFile in @('LICENSE', 'README.txt')) {
        $SourceFile = Join-Path $DistributionRoot $LicenseFile
        if (Test-Path -LiteralPath $SourceFile -PathType Leaf) {
            Copy-Item -LiteralPath $SourceFile -Destination (Join-Path $BundledFFmpeg $LicenseFile) -Force
        }
    }
    & $FFmpegSource -version | Set-Content -LiteralPath (Join-Path $BundledFFmpeg 'FFMPEG-VERSION.txt') -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'Bundled FFmpeg validation failed.' }
    & $FFprobeSource -version | Set-Content -LiteralPath (Join-Path $BundledFFmpeg 'FFPROBE-VERSION.txt') -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'Bundled ffprobe validation failed.' }
    Write-Host 'Offline backend ready: build/backend/dikey-backend/dikey-backend.exe'
}
finally {
    Pop-Location
}
