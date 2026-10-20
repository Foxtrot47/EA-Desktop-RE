param(
    [Parameter(Mandatory = $true)]
    [string]$Binary,
    [Parameter(Mandatory = $true)]
    [string]$Output
)

$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'E:\Software\IDA Professional 9.1\idalib\python'
$python = 'C:\Users\foxtrot47\AppData\Local\Programs\Python\Python312\python.exe'
$script = Join-Path $PSScriptRoot 'idalib_index.py'
& $python $script $Binary $Output
if ($LASTEXITCODE -ne 0) {
    throw "idalib indexing failed with exit code $LASTEXITCODE"
}
