param(
    [Parameter(Mandatory = $true)]
    [string]$Binary,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [Parameter(Mandatory = $true)]
    [string[]]$Term,
    [int]$MaxFunctions = 80
)

$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = 'E:\Software\IDA Professional 9.1\idalib\python'
$python = 'C:\Users\foxtrot47\AppData\Local\Programs\Python\Python312\python.exe'
$script = Join-Path $PSScriptRoot 'idalib_decompile_refs.py'
$arguments = @($script, $Binary, $Output, '--max-functions', [string]$MaxFunctions)
foreach ($value in $Term) {
    $arguments += @('--term', $value)
}
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "idalib decompilation failed with exit code $LASTEXITCODE"
}
