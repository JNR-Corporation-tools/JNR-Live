$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (Get-Command py -ErrorAction SilentlyContinue) {
    py install.py
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python install.py
} else {
    throw 'Python 3.11+ was not found. Install Python and run this script again.'
}
