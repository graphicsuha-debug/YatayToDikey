$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDirectory = Join-Path $projectRoot 'data'
$venvDirectory = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
$appUrl = 'http://127.0.0.1:4318'
$healthUrl = "$appUrl/api/health"

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Get-DependencyFingerprint {
    param([string[]] $Paths)
    $hashes = foreach ($dependencyPath in $Paths) {
        if (Test-Path -LiteralPath $dependencyPath) {
            (Get-FileHash -LiteralPath $dependencyPath -Algorithm SHA256).Hash
        }
    }
    return ($hashes -join ':')
}

function Test-SavedFingerprint {
    param([string] $StampPath, [string] $Fingerprint)
    return ((Test-Path -LiteralPath $StampPath) -and ((Get-Content -LiteralPath $StampPath -Raw).Trim() -eq $Fingerprint))
}

try {
    Set-Location -LiteralPath $projectRoot

    if (Test-AppReady) {
        Write-Host 'Uygulama zaten calisiyor. Tarayici aciliyor...' -ForegroundColor Cyan
        Start-Process $appUrl
        exit 0
    }

    foreach ($toolName in @('ffmpeg', 'ffprobe')) {
        if (-not (Get-Command $toolName -ErrorAction SilentlyContinue)) {
            throw "FFmpeg bulunamadi. Once 'winget install --id Gyan.FFmpeg --exact' komutunu calistirin, sonra bu pencereyi kapatip Baslat.bat dosyasini yeniden acin."
        }
    }

    $npmCommand = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        throw 'Node.js ve npm bulunamadi. Node.js LTS kurun ve Baslat.bat dosyasini yeniden acin.'
    }

    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host 'Ilk acilis: Python ortami hazirlaniyor...' -ForegroundColor Cyan
        $pyCommand = Get-Command 'py.exe' -ErrorAction SilentlyContinue
        $pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
        if ($pyCommand) {
            & $pyCommand.Source -3 -m venv $venvDirectory
        }
        elseif ($pythonCommand) {
            & $pythonCommand.Source -m venv $venvDirectory
        }
        else {
            throw 'Python bulunamadi. Python 3.11 veya daha yeni bir surum kurun.'
        }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
            throw 'Python ortami olusturulamadi. Python 3.11 veya daha yeni bir surumun kurulu oldugunu kontrol edin.'
        }
    }

    $requirementsPath = Join-Path $projectRoot 'requirements.txt'
    $pythonStamp = Join-Path $dataDirectory 'python-dependencies.sha256'
    $pythonFingerprint = Get-DependencyFingerprint -Paths @($requirementsPath)
    if (-not (Test-SavedFingerprint -StampPath $pythonStamp -Fingerprint $pythonFingerprint)) {
        Write-Host 'Video isleme bilesenleri kuruluyor...' -ForegroundColor Cyan
        & $venvPython -m pip install -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw 'Python bagimliliklari kurulamadi. Internet baglantisini ve yukaridaki hata mesajini kontrol edin.'
        }
        Set-Content -LiteralPath $pythonStamp -Value $pythonFingerprint -Encoding Ascii
    }

    $packagePaths = @((Join-Path $projectRoot 'package.json'), (Join-Path $projectRoot 'package-lock.json'))
    $nodeStamp = Join-Path $dataDirectory 'node-dependencies.sha256'
    $nodeFingerprint = Get-DependencyFingerprint -Paths $packagePaths
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules')) -or -not (Test-SavedFingerprint -StampPath $nodeStamp -Fingerprint $nodeFingerprint)) {
        Write-Host 'Arayuz bilesenleri kuruluyor...' -ForegroundColor Cyan
        & $npmCommand.Source install
        if ($LASTEXITCODE -ne 0) {
            throw 'Arayuz bagimliliklari kurulamadi. Internet baglantisini ve yukaridaki hata mesajini kontrol edin.'
        }
        $nodeFingerprint = Get-DependencyFingerprint -Paths $packagePaths
        Set-Content -LiteralPath $nodeStamp -Value $nodeFingerprint -Encoding Ascii
    }

    Write-Host 'Arayuz hazirlaniyor...' -ForegroundColor Cyan
    & $npmCommand.Source run build
    if ($LASTEXITCODE -ne 0) {
        throw 'Arayuz hazirlanamadi. Yukaridaki hata mesajini kontrol edin.'
    }

    $stdoutPath = Join-Path $dataDirectory 'server.log'
    $stderrPath = Join-Path $dataDirectory 'server-error.log'
    Write-Host 'Uygulama baslatiliyor...' -ForegroundColor Cyan
    $serverProcess = Start-Process -FilePath $venvPython -ArgumentList @('-m', 'backend.app') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru

    $started = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (Test-AppReady) {
            $started = $true
            break
        }
        $serverProcess.Refresh()
        if ($serverProcess.HasExited) {
            if (Test-Path -LiteralPath $stderrPath) {
                Get-Content -LiteralPath $stderrPath -Tail 20 | Write-Host
            }
            throw "Uygulama baslatilamadi. Ayrintilar: $stderrPath"
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $started) {
        throw "Uygulama zamaninda yanit vermedi. Ayrintilar: $stderrPath"
    }

    Set-Content -LiteralPath (Join-Path $dataDirectory 'server.pid') -Value $serverProcess.Id -Encoding Ascii
    Start-Process $appUrl
    Write-Host "Hazir: $appUrl" -ForegroundColor Green
    Write-Host 'Tarayici sekmesi kapansa da video islemleri arka planda devam eder.'
}
catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
