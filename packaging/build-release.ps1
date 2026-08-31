$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = if ($env:TUJA_PYTHON) { $env:TUJA_PYTHON } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
$isccCandidates = @(
    $env:ISCC_PATH,
    'C:\Program Files\Inno Setup 7\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$iscc = $isccCandidates | Select-Object -First 1

if (-not $python) { throw 'Python 3 was not found. Set TUJA_PYTHON or add python to PATH.' }
if (-not $iscc) { throw 'Inno Setup was not found. Set ISCC_PATH or install Inno Setup.' }

& $python -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller is required: python -m pip install pyinstaller' }

function Get-SignTool {
    if ($env:SIGNTOOL_PATH -and (Test-Path -LiteralPath $env:SIGNTOOL_PATH)) { return $env:SIGNTOOL_PATH }
    $kits = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
        Sort-Object FullName -Descending
    return $kits[0].FullName
}

function Sign-Artifact([string]$Path) {
    if (-not $env:TUJA_SIGN_CERT_SHA1) {
        if ($env:TUJA_REQUIRE_SIGNING -eq '1') { throw 'Code-signing certificate is required. Set TUJA_SIGN_CERT_SHA1.' }
        Write-Warning "Unsigned beta artifact: $Path"
        return
    }
    $signTool = Get-SignTool
    if (-not $signTool) { throw 'signtool.exe was not found. Install the Windows SDK or set SIGNTOOL_PATH.' }
    & $signTool sign /sha1 $env:TUJA_SIGN_CERT_SHA1 /fd SHA256 /tr 'http://timestamp.digicert.com' /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) { throw "Code signing failed: $Path" }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid') { throw "Signature verification failed: $($signature.Status)" }
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --windowed --name '투자' --icon 'assets\tuja-icon.ico' --add-data 'web;web' --version-file 'packaging\version-info.txt' desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    Sign-Artifact (Join-Path $projectRoot 'dist\투자\투자.exe')
    & $iscc 'packaging\tuja.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed.' }
    Sign-Artifact (Join-Path $projectRoot 'release\Tuja-Setup-0.9.1-beta.exe')
} finally {
    Pop-Location
}
