# PNGtuber Studio installer (M7 S2). Started by install.bat; Windows PowerShell 5.1.
# Safe to run again: every step checks whether it is already done and skips it.
# No admin rights needed. Everything goes inside the app folder except the uv cache
# and uv's Python (in %LOCALAPPDATA%\uv) and the desktop shortcut.
# Keep this file ASCII only (Windows PowerShell 5.1 reads files without a BOM as ANSI).

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# ---- Pins (change together with PROJECT_STATE.md, "How to run / test") ----
$UvVersion = '0.13.0'
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
$UvSha256 = '088962f9e7b7bd9ea740c04c650b2a21c8928c345bd99ac24350dc924dba656c'

$NodeVersion = '24.21.0'
$NodeUrl = "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip"
$NodeSha256 = '158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541'

# BtbN 8.1 release-branch build, month-end tag (month-end builds are kept long term).
# Never master or 9.0: they need NVIDIA driver 610+ (M0 decision).
$FfmpegVersion = 'n8.1.3-27-g8dca1586f4'
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/ffmpeg-$FfmpegVersion-win64-gpl-8.1.zip"
$FfmpegSha256 = '401dffcf14c301082e1fc03b0bc876b92ea676bfc521fc56e80a1537d137034f'
# Used only when the pinned build is gone: newest 8.1 build, no checksum to compare.
$FfmpegFallbackUrl = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-win64-gpl-8.1.zip'

$MinDriver = [version]'570.0'   # ffmpeg 8.1 NVENC API 13.0; CUDA 12.6 needs 560+
$MinFreeGB = 15

# ---- Paths ----
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Tools = Join-Path $Root 'tools'
$UvDir = Join-Path $Tools 'uv'
$UvExe = Join-Path $UvDir 'uv.exe'
$NodeDir = Join-Path $Tools 'node'
$NodeExe = Join-Path $NodeDir 'node.exe'
$NpmCmd = Join-Path $NodeDir 'npm.cmd'
$Bin = Join-Path $Root 'bin'
$Frontend = Join-Path $Root 'frontend'
$Downloads = Join-Path $Tools 'downloads'
$LogPath = Join-Path $Root 'install.log'

$script:Warnings = New-Object System.Collections.Generic.List[string]

function Fail([string]$message) {
    # An expected stop with a message for the user (told apart from bugs in the catch below).
    $e = New-Object System.Exception $message
    $e.Data['PngtuberInstall'] = $true
    throw $e
}

function Step([string]$title) {
    Write-Host ''
    Write-Host "== $title" -ForegroundColor Cyan
}

function Info([string]$text) { Write-Host "   $text" }
function Ok([string]$text) { Write-Host "   OK  $text" -ForegroundColor Green }
function Skip([string]$text) { Write-Host "   --  $text (already done)" -ForegroundColor DarkGray }

function Warn([string]$text) {
    Write-Host "   !!  $text" -ForegroundColor Yellow
    $script:Warnings.Add($text) | Out-Null
}

function Invoke-Native([string]$exe, [string[]]$arguments, [string]$what) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit code $LASTEXITCODE). See the messages above." }
}

function Get-Download([string]$url, [string]$dest, [string]$sha256) {
    # Returns $true when the file matches $sha256 (or $sha256 is empty).
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    if ((Test-Path $dest) -and $sha256 -and ((Get-FileHash $dest -Algorithm SHA256).Hash -eq $sha256.ToUpper())) {
        Info "Using the earlier download $(Split-Path $dest -Leaf)"
        return $true
    }
    $part = "$dest.part"
    if (Test-Path $part) { Remove-Item $part -Force }
    Info "Downloading $url"
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $curl) {
        & $curl -L --fail --retry 3 --progress-bar -o $part $url
        if ($LASTEXITCODE -ne 0) {
            if (Test-Path $part) { Remove-Item $part -Force }
            return $false
        }
    } else {
        try { Invoke-WebRequest -Uri $url -OutFile $part -UseBasicParsing }
        catch {
            if (Test-Path $part) { Remove-Item $part -Force }
            return $false
        }
    }
    if ($sha256) {
        $hash = (Get-FileHash $part -Algorithm SHA256).Hash
        if ($hash -ne $sha256.ToUpper()) {
            Remove-Item $part -Force
            Fail "The download from $url is damaged or not the pinned file (SHA-256 $hash). Run install.bat again."
        }
    }
    Move-Item $part $dest -Force
    return $true
}

function Expand-Zip([string]$zip, [string]$dest) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path $tar) {
        & $tar -xf $zip -C $dest
        if ($LASTEXITCODE -eq 0) { return }
    }
    Expand-Archive -Path $zip -DestinationPath $dest -Force
}

function Get-TreeStamp([string[]]$paths) {
    # One hash over the relative names and contents of every file under $paths.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($p in $paths) {
        if (-not (Test-Path $p)) { continue }
        $items = if ((Get-Item $p).PSIsContainer) { Get-ChildItem $p -Recurse -File | Sort-Object FullName } else { @(Get-Item $p) }
        foreach ($f in $items) {
            $rel = $f.FullName.Substring($Root.Length)
            $lines.Add("$rel=$((Get-FileHash $f.FullName -Algorithm SHA256).Hash)") | Out-Null
        }
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '')
}

function Read-Stamp([string]$path) {
    if (Test-Path $path) { return (Get-Content $path -Raw).Trim() }
    return ''
}

# ---- Steps ----

function Test-System {
    Step 'Checking this PC'
    if (-not [Environment]::Is64BitOperatingSystem) { Fail 'PNGtuber Studio needs 64-bit Windows.' }
    if (-not (Test-Path (Join-Path $Root 'pyproject.toml'))) {
        Fail "install.bat must stay in the PNGtuber Studio folder (pyproject.toml not found in $Root)."
    }
    Ok "App folder: $Root"
    $drive = Get-PSDrive -Name ($Root.Substring(0, 1))
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt $MinFreeGB) {
        Warn "Only $freeGB GB free on drive $($drive.Name):. The install and the voice model need about $MinFreeGB GB."
    } else {
        Ok "$freeGB GB free on drive $($drive.Name):"
    }
}

function Get-NvidiaDriver {
    # Returns @{ Name; Driver } from nvidia-smi, else from WMI, else $null.
    $smi = @(
        (Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'),
        (Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe')
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($smi) {
        $out = & $smi --query-gpu=name,driver_version --format=csv,noheader
        if ($LASTEXITCODE -eq 0 -and $out) {
            $first = @($out)[0] -split ','
            return @{ Name = $first[0].Trim(); Driver = $first[1].Trim() }
        }
    }
    $card = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' } | Select-Object -First 1
    if ($card) {
        # WMI shows e.g. 32.0.15.8142 for driver 581.42: the last five digits.
        $digits = ($card.DriverVersion -replace '\.', '')
        $tail = $digits.Substring([math]::Max(0, $digits.Length - 5))
        return @{ Name = $card.Name; Driver = "$($tail.Substring(0, 3)).$($tail.Substring(3))" }
    }
    return $null
}

function Test-Gpu {
    Step 'Checking the NVIDIA GPU and driver'
    $gpu = Get-NvidiaDriver
    if ($null -eq $gpu) {
        Fail ('No NVIDIA graphics card was found. PNGtuber Studio needs an NVIDIA GPU (6 GB VRAM or more) ' +
              'for the voice model and the video encoder. If this PC has one, install the latest driver from ' +
              'https://www.nvidia.com/Download/index.aspx and run install.bat again.')
    }
    $driver = [version]$gpu.Driver
    if ($driver -lt $MinDriver) {
        Fail ("$($gpu.Name) has driver $($gpu.Driver); version $MinDriver or newer is needed. " +
              'Update it from https://www.nvidia.com/Download/index.aspx (or the NVIDIA app), restart Windows, then run install.bat again.')
    }
    Ok "$($gpu.Name), driver $($gpu.Driver)"
}

function Install-Uv {
    Step "uv $UvVersion (Python package manager, into tools\uv)"
    if (Test-Path $UvExe) {
        $v = (& $UvExe --version) -split ' '
        if ($v[1] -eq $UvVersion) { Skip "uv $UvVersion"; return }
    }
    $zip = Join-Path $Downloads "uv-$UvVersion.zip"
    if (-not (Get-Download $UvUrl $zip $UvSha256)) { Fail "Could not download uv from $UvUrl. Check the internet connection and run install.bat again." }
    $tmp = Join-Path $Tools 'uv.tmp'
    Expand-Zip $zip $tmp
    $found = Get-ChildItem $tmp -Recurse -Filter 'uv.exe' | Select-Object -First 1
    if (-not $found) { Fail 'The uv download has no uv.exe inside.' }
    if (Test-Path $UvDir) { Remove-Item $UvDir -Recurse -Force }
    Move-Item $found.DirectoryName $UvDir
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Ok "uv $UvVersion"
}

function Install-Python {
    Step 'Python 3.11 and the Python packages (uv sync; the first time downloads about 3 GB)'
    Push-Location $Root
    try { Invoke-Native $UvExe @('sync', '--frozen') 'uv sync' }
    finally { Pop-Location }
    Ok 'Python environment in .venv'
}

function Install-Node {
    Step "Node.js $NodeVersion (only to build the window's pages, into tools\node)"
    if (Test-Path $NodeExe) {
        $v = (& $NodeExe --version).Trim()
        if ($v -eq "v$NodeVersion") { Skip "Node.js $NodeVersion"; return }
    }
    $zip = Join-Path $Downloads "node-v$NodeVersion-win-x64.zip"
    if (-not (Get-Download $NodeUrl $zip $NodeSha256)) { Fail "Could not download Node.js from $NodeUrl. Check the internet connection and run install.bat again." }
    $tmp = Join-Path $Tools 'node.tmp'
    Expand-Zip $zip $tmp
    $inner = Join-Path $tmp "node-v$NodeVersion-win-x64"
    if (-not (Test-Path (Join-Path $inner 'node.exe'))) { Fail 'The Node.js download has no node.exe inside.' }
    if (Test-Path $NodeDir) { Remove-Item $NodeDir -Recurse -Force }
    Move-Item $inner $NodeDir
    Remove-Item $tmp -Recurse -Force
    Ok "Node.js $NodeVersion"
}

function Build-Frontend {
    Step 'Building the app window (npm ci, npm run build)'
    $env:Path = "$NodeDir;$env:Path"
    $modules = Join-Path $Frontend 'node_modules'
    $modulesStampPath = Join-Path $modules '.pngtuber-install-stamp'
    $modulesStamp = "node $NodeVersion " + (Get-TreeStamp @((Join-Path $Frontend 'package-lock.json')))
    Push-Location $Frontend
    try {
        if ((Read-Stamp $modulesStampPath) -eq $modulesStamp) {
            Skip 'npm packages'
        } else {
            Invoke-Native $NpmCmd @('ci', '--no-audit', '--no-fund') 'npm ci'
            Set-Content -Path $modulesStampPath -Value $modulesStamp -Encoding ascii
            Ok 'npm packages'
        }
        $sources = @('src', 'public', 'index.html', 'package.json', 'package-lock.json',
                     'svelte.config.js', 'tsconfig.json', 'vite.config.ts') | ForEach-Object { Join-Path $Frontend $_ }
        $distStampPath = Join-Path $Frontend 'dist\.pngtuber-build-stamp'
        $distStamp = Get-TreeStamp $sources
        if ((Test-Path (Join-Path $Frontend 'dist\index.html')) -and ((Read-Stamp $distStampPath) -eq $distStamp)) {
            Skip 'frontend build'
        } else {
            Invoke-Native $NpmCmd @('run', 'build') 'npm run build'
            Set-Content -Path $distStampPath -Value $distStamp -Encoding ascii
            Ok 'frontend built into frontend\dist'
        }
    } finally { Pop-Location }
}

function Get-FfmpegVersion([string]$exe) {
    if (-not (Test-Path $exe)) { return '' }
    $first = (& $exe -hide_banner -version | Select-Object -First 1)
    if ($first -match 'version (\S+)') { return $Matches[1] }
    return ''
}

function Install-Ffmpeg {
    Step "ffmpeg 8.1 with NVENC (BtbN $FfmpegVersion, into bin)"
    $ffmpeg = Join-Path $Bin 'ffmpeg.exe'
    $ffprobe = Join-Path $Bin 'ffprobe.exe'
    $have = Get-FfmpegVersion $ffmpeg
    if ($have -like 'n8.1*' -and (Get-FfmpegVersion $ffprobe) -like 'n8.1*') {
        Skip "ffmpeg $have"
        return
    }
    if ($have) { Info "Replacing ffmpeg $have (not an 8.1 build)" }
    $zip = Join-Path $Downloads "ffmpeg-$FfmpegVersion-win64-gpl-8.1.zip"
    if (-not (Get-Download $FfmpegUrl $zip $FfmpegSha256)) {
        Warn "The pinned ffmpeg build is no longer on GitHub; using the newest 8.1 build instead (not checksum-verified)."
        $zip = Join-Path $Downloads 'ffmpeg-n8.1-latest-win64-gpl-8.1.zip'
        if (Test-Path $zip) { Remove-Item $zip -Force }
        if (-not (Get-Download $FfmpegFallbackUrl $zip '')) {
            Fail ('Could not download ffmpeg. Check the internet connection and run install.bat again, or copy ' +
                  'ffmpeg.exe and ffprobe.exe from a BtbN "win64-gpl-8.1" zip (https://github.com/BtbN/FFmpeg-Builds/releases) into the bin folder.')
        }
    }
    $tmp = Join-Path $Tools 'ffmpeg.tmp'
    Expand-Zip $zip $tmp
    $exeDir = Get-ChildItem $tmp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
    if (-not $exeDir) { Fail 'The ffmpeg download has no ffmpeg.exe inside.' }
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    Copy-Item (Join-Path $exeDir.DirectoryName 'ffmpeg.exe') $Bin -Force
    Copy-Item (Join-Path $exeDir.DirectoryName 'ffprobe.exe') $Bin -Force
    $license = Get-ChildItem $tmp -Recurse -Filter 'LICENSE.txt' | Select-Object -First 1
    if ($license) { Copy-Item $license.FullName (Join-Path $Bin 'ffmpeg-LICENSE.txt') -Force }
    Remove-Item $tmp -Recurse -Force
    Ok "ffmpeg $(Get-FfmpegVersion $ffmpeg)"
}

function Test-Install {
    Step 'Checking CUDA, the GPU, ffmpeg (NVENC) and ffprobe'
    Push-Location $Root
    try {
        # Through Write-Host so the lines also reach install.log (the transcript skips native output).
        & $UvExe run --frozen python (Join-Path $Root 'scripts\install\check_install.py') | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) { Fail 'A check failed (see the FAIL line above).' }
    } finally { Pop-Location }
}

function Write-RunBat {
    Step 'Creating run.bat and the desktop shortcut'
    $runBat = Join-Path $Root 'run.bat'
    $content = @(
        '@echo off',
        'rem Written by install.bat. Starts PNGtuber Studio. Run install.bat again to recreate it.',
        'setlocal',
        'cd /d "%~dp0"',
        'if not exist "tools\uv\uv.exe" (',
        '  echo PNGtuber Studio is not installed yet. Run install.bat first.',
        '  pause',
        '  exit /b 1',
        ')',
        '"tools\uv\uv.exe" run --frozen python -m backend.main',
        'if errorlevel 1 (',
        '  echo.',
        '  echo PNGtuber Studio stopped with an error. The messages above say why.',
        '  pause',
        ')'
    ) -join "`r`n"
    [System.IO.File]::WriteAllText($runBat, $content + "`r`n", [System.Text.Encoding]::ASCII)
    Ok "run.bat"

    try {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $link = Join-Path $desktop 'PNGtuber Studio.lnk'
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($link)
        $sc.TargetPath = $runBat
        $sc.WorkingDirectory = $Root
        $sc.IconLocation = (Join-Path $Root 'assets\app.ico') + ',0'
        $sc.WindowStyle = 7   # console minimized; the app window opens normally
        $sc.Description = 'PNGtuber Studio'
        $sc.Save()
        Ok "Desktop shortcut: $link"
    } catch {
        Warn "The desktop shortcut could not be created ($($_.Exception.Message)). Start the app with run.bat."
    }
}

# ---- Main ----

$transcript = $false
try { Start-Transcript -Path $LogPath -Force | Out-Null; $transcript = $true } catch { }

$exitCode = 0
try {
    Write-Host 'PNGtuber Studio installer' -ForegroundColor White
    Test-System
    Test-Gpu
    New-Item -ItemType Directory -Force -Path $Tools | Out-Null
    Install-Uv
    Install-Python
    Install-Node
    Build-Frontend
    Install-Ffmpeg
    Test-Install
    Write-RunBat
    Write-Host ''
    Write-Host 'Install finished.' -ForegroundColor Green
    foreach ($w in $script:Warnings) { Write-Host "   !!  $w" -ForegroundColor Yellow }
    Write-Host '   Start the app from the desktop shortcut or run.bat.'
    Write-Host '   The first time, the app downloads the voice model (several GB, once).'
} catch {
    Write-Host ''
    if ($_.Exception.Data['PngtuberInstall']) {
        Write-Host "Install stopped: $($_.Exception.Message)" -ForegroundColor Red
        $exitCode = 1
    } else {
        Write-Host "Install stopped by an unexpected error: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "   at $($_.InvocationInfo.PositionMessage)"
        $exitCode = 2
    }
} finally {
    if ($transcript) { Stop-Transcript | Out-Null; Write-Host "   Log: $LogPath" }
}
exit $exitCode
