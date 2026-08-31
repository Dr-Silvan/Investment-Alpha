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

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --windowed --name '투자' --icon 'assets\tuja-icon.ico' --add-data 'web;web' --version-file 'packaging\version-info.txt' desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    & $iscc 'packaging\tuja.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed.' }
} finally {
    Pop-Location
}
