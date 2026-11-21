# Builds the Windows zip of BioForgeSDL and smoke-tests it. Run it in the Visual Studio developer PowerShell (native/WINDOWS_CHECK.md),
# with SDL3 set up as there (native\ThirdParty\SDL3 or SDL3_DIR):
#   native\package-windows.ps1 -Data C:\path\to\Bioforge      # the folder with BIOFORGE.EXE, for the smoke run only
#   native\package-windows.ps1 -NoSmoke
# Output: native\dist\BioForge-<commit>-windows-x64.zip (native\dist is ignored by git), one folder with BioForgeSDL.exe, SDL3.dll, the
# Swift runtime DLLs it needs (found by walking `dumpbin /dependents`), the Visual C++ runtime DLLs from the Build Tools' redist folder,
# README.txt, NOTICES.txt and licenses\. No game data. The program is built for the Windows subsystem, so no console window opens.
param([string]$Data = $env:BIOFORGE_DATA, [switch]$NoSmoke)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$smokeLine = 'smoke: level TITLE tick 900 camera NONE frame 50e055142d28b295'
$native = $PSScriptRoot

foreach ($tool in 'swift', 'dumpbin', 'rc', 'git') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool not found: run this in the Visual Studio developer PowerShell (native/WINDOWS_CHECK.md)" }
}
if (-not $env:VCToolsRedistDir -or -not (Test-Path $env:VCToolsRedistDir)) {
    throw 'no Visual C++ redist folder (VCToolsRedistDir): run this in the Visual Studio developer PowerShell, and add the Build Tools component Microsoft.VisualStudio.Component.VC.Redist.14.Latest if it is missing (native/WINDOWS_CHECK.md)'
}
if (-not $NoSmoke -and -not (Test-Path (Join-Path $Data 'BIOFORGE.EXE'))) { throw "no BIOFORGE.EXE in '$Data': pass -Data <the folder with BIOFORGE.EXE>, or -NoSmoke" }
$sdlDir = if ($env:SDL3_DIR) { $env:SDL3_DIR } else { Join-Path $native 'ThirdParty\SDL3' }
$sdlBin = Join-Path $sdlDir 'lib\x64'
if (-not (Test-Path (Join-Path $sdlBin 'SDL3.dll'))) { throw "no SDL3.dll in $sdlBin (native/WINDOWS_CHECK.md, Setup step 2)" }

$commit = (git -C $native rev-parse --short HEAD).Trim()
git -C $native diff --quiet HEAD -- .
if ($LASTEXITCODE -ne 0) { $commit += '-dirty' }
$name = "BioForge-$commit-windows-x64"
$dist = Join-Path $native 'dist'
$work = Join-Path $dist 'windows-work'
New-Item -ItemType Directory -Force $work | Out-Null

Write-Host '== icon and version resource'
Push-Location (Join-Path $native 'package\windows')
try { rc /nologo /fo (Join-Path $work 'BioForge.res') BioForge.rc; if ($LASTEXITCODE -ne 0) { throw 'rc failed' } }
finally { Pop-Location }

Write-Host '== swift build -c release'
Push-Location $native
try {
    swift build -c release --product BioForgeSDL -Xlinker /SUBSYSTEM:WINDOWS -Xlinker /ENTRY:mainCRTStartup -Xlinker (Join-Path $work 'BioForge.res')
    if ($LASTEXITCODE -ne 0) { throw 'swift build failed' }
    $bin = (swift build -c release --show-bin-path).Trim()
} finally { Pop-Location }
$exe = Join-Path $bin 'BioForgeSDL.exe'

Write-Host '== DLLs'
# The Visual C++ runtime comes from the redist folder (app-local), even when System32 has a copy, since a player's PC may not.
$crtDir = Get-ChildItem (Join-Path $env:VCToolsRedistDir 'x64') -Directory -Filter 'Microsoft.VC14*.CRT' | Select-Object -First 1
if (-not $crtDir) { throw "no Microsoft.VC14*.CRT folder in $env:VCToolsRedistDir\x64" }
# SDL's folder, then the Swift runtime (Swift\Runtimes\<version>\usr\bin), then the rest of PATH.
$pathDirs = @($env:Path -split ';' | Where-Object { $_ -and (Test-Path $_) })
$searchDirs = @($sdlBin) + @($pathDirs | Where-Object { $_ -match '\\Swift\\Runtimes\\' }) + @($pathDirs | Where-Object { $_ -notmatch '\\Swift\\Runtimes\\' })
function Get-Dependents([string]$file) {
    foreach ($line in (dumpbin /nologo /dependents $file)) { if ($line -match '^\s+(\S+\.dll)\s*$') { $Matches[1] } }
}
function Find-Dll([string]$dll) {
    if ($dll -match '^(vcruntime|msvcp|concrt|vccorlib)\d') {
        $p = Join-Path $crtDir.FullName $dll
        if (Test-Path $p) { return $p }
    }
    foreach ($d in $searchDirs) { $p = Join-Path $d $dll; if (Test-Path $p) { return $p } }
    return $null
}
$bundle = [ordered]@{}            # file name -> path
$missing = @()
$queue = [System.Collections.Generic.Queue[string]]::new()
$queue.Enqueue($exe)
while ($queue.Count -gt 0) {
    foreach ($dll in (Get-Dependents $queue.Dequeue())) {
        $key = $dll.ToLowerInvariant()
        if ($bundle.Contains($key) -or $key -match '^(api|ext)-ms-') { continue }
        $path = Find-Dll $dll
        if (-not $path) { $missing += $dll; continue }
        if ($path.StartsWith($env:SystemRoot, [StringComparison]::OrdinalIgnoreCase)) { continue }      # part of Windows (ucrtbase, kernel32, ...)
        $bundle[$key] = $path
        $queue.Enqueue($path)
    }
}
if ($missing) { throw "DLLs not found: $($missing | Sort-Object -Unique)" }
$bundle.Values | ForEach-Object { Write-Host "  $_" }

Write-Host "== $name.zip"
$stage = Join-Path $dist $name
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory $stage | Out-Null
Copy-Item $exe $stage
$bundle.Values | ForEach-Object { Copy-Item $_ $stage }
Copy-Item (Join-Path $native 'package\README.txt'), (Join-Path $native 'package\NOTICES.txt') $stage
Copy-Item -Recurse (Join-Path $native 'package\licenses') (Join-Path $stage 'licenses')
Set-Content (Join-Path $stage 'VERSION') $commit
$zip = "$stage.zip"
Compress-Archive -Path $stage -DestinationPath $zip -Force
Get-Item $zip | ForEach-Object { Write-Host "  $($_.FullName) ($([math]::Round($_.Length / 1MB, 1)) MB)" }

if ($NoSmoke) { return }
Write-Host '== smoke run of the unzipped package'
# A fresh folder, PATH cut down to Windows' own folders (so a DLL missing from the zip fails here) and a throwaway %APPDATA%.
$tmp = Join-Path ([IO.Path]::GetTempPath()) "bioforge-smoke-$([guid]::NewGuid())"
Expand-Archive $zip $tmp
$vars = 'Path', 'APPDATA', 'SDL_VIDEO_DRIVER', 'SDL_AUDIO_DRIVER', 'BIOFORGE_SDL_SMOKE', 'BIOFORGE_SDL_SHOT', 'BIOFORGE_DATA'
$saved = @{}; foreach ($v in $vars) { $saved[$v] = [Environment]::GetEnvironmentVariable($v) }
try {
    $env:Path = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:APPDATA = Join-Path $tmp 'AppData'
    New-Item -ItemType Directory $env:APPDATA | Out-Null
    $env:SDL_VIDEO_DRIVER = 'offscreen'; $env:SDL_AUDIO_DRIVER = 'dummy'
    $env:BIOFORGE_SDL_SMOKE = '900'; $env:BIOFORGE_SDL_SHOT = Join-Path $tmp 'shot.bmp'; $env:BIOFORGE_DATA = $Data
    # .NET's Process, not Start-Process: it waits for a Windows-subsystem program and reports its exit code reliably with redirection.
    $psi = [System.Diagnostics.ProcessStartInfo]::new((Join-Path $tmp "$name\BioForgeSDL.exe"))
    $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.WorkingDirectory = $tmp
    $proc = [System.Diagnostics.Process]::Start($psi)
    $outTask = $proc.StandardOutput.ReadToEndAsync(); $errTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $got = $outTask.Result.Trim(); $errText = $errTask.Result
    $exitCode = $proc.ExitCode
} finally { foreach ($v in $vars) { [Environment]::SetEnvironmentVariable($v, $saved[$v]) } }
Write-Host "  $got (exit code $exitCode)"
if ($exitCode -ne 0 -or $got -ne $smokeLine) {
    if ($errText) { Write-Host $errText }
    throw "smoke run failed: expected '$smokeLine' and exit code 0 (files in $tmp)"
}
Write-Host "  shot: $tmp\shot.bmp"
Write-Host "== done: $zip"
