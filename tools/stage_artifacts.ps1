$ErrorActionPreference = 'Stop'

$sourceRoot = 'C:\Program Files\Electronic Arts\EA Desktop\EA Desktop'
$artifactRoot = Join-Path $PSScriptRoot '..\artifacts'
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

$names = @(
    'EADesktop.exe',
    'EABackgroundService.exe',
    'EALocalHostSvc.exe',
    'EALauncher.exe',
    'EALaunchHelper.exe',
    'GetGameToken.exe',
    'EASteamAuthHelper.exe',
    'EASteamLauncher.exe',
    'EASteamProxy.exe',
    'EAEgsLauncher.exe',
    'EAEgsProxy.exe',
    'Link2EA.exe',
    'EAConnect_microsoft.exe'
)

$manifest = foreach ($name in $names) {
    $source = Join-Path $sourceRoot $name
    $destination = Join-Path $artifactRoot $name
    Copy-Item -LiteralPath $source -Destination $destination -Force
    $item = Get-Item -LiteralPath $destination
    $version = $item.VersionInfo
    $signature = Get-AuthenticodeSignature -LiteralPath $source
    [ordered]@{
        name = $name
        installed_path = $source
        staged_path = $destination
        size = $item.Length
        sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
        product_version = $version.ProductVersion
        file_version = $version.FileVersion
        signature_status = [string]$signature.Status
        signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    }
}

$output = [ordered]@{
    schema = 1
    build = (Get-Content -Raw -LiteralPath (Join-Path $sourceRoot 'version.properties')).Trim()
    source_root = $sourceRoot
    captured_at = (Get-Date).ToUniversalTime().ToString('o')
    artifacts = $manifest
}

$output | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $artifactRoot 'manifest.json') -Encoding utf8
Write-Host "Staged $($names.Count) artifacts in $artifactRoot"
