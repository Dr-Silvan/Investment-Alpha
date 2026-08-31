$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error 'Python 3.10 이상이 필요합니다.'
}
& $python.Source (Join-Path $root 'server.py')
