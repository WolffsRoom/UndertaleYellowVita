param(
    [string]$SourceRoot,
    [string]$OutputRoot,
    [string]$RebuiltDataWin,
    [string]$CacheRoot
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $SourceRoot) { $SourceRoot = Join-Path $root 'Undertale Yellow v-1-3-1' }
if (-not $OutputRoot) { $OutputRoot = Join-Path $root 'data\prepared\undertale-yellow' }
if (-not $RebuiltDataWin) { $RebuiltDataWin = Join-Path $root 'tools\rebuild\rebuild\undertale-yellow\data.win' }
if (-not $CacheRoot) { $CacheRoot = Join-Path $root 'tools\cache\prepared\chapter1' }

$required = @('data.win', 'options.ini', 'mus', 'snd')
foreach ($name in $required) {
    $path = Join-Path $SourceRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Arquivo ou pasta obrigatoria ausente: $path"
    }
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$selectedDataWin = if (Test-Path -LiteralPath $RebuiltDataWin) {
    $RebuiltDataWin
} else {
    Join-Path $SourceRoot 'data.win'
}
Copy-Item -LiteralPath $selectedDataWin -Destination (Join-Path $OutputRoot 'data.win') -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'options.ini') -Destination $OutputRoot -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'mus') -Destination $OutputRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $SourceRoot 'snd') -Destination $OutputRoot -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $CacheRoot 'texture-cache')) {
    Copy-Item -LiteralPath (Join-Path $CacheRoot 'texture-cache') -Destination $OutputRoot -Recurse -Force
}
if (Test-Path -LiteralPath (Join-Path $CacheRoot 'pvr')) {
    Copy-Item -LiteralPath (Join-Path $CacheRoot 'pvr') -Destination $OutputRoot -Recurse -Force
}

Get-ChildItem -LiteralPath $OutputRoot -Recurse -File |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "{0}  {1}" -f $_.Hash, $_.Path.Substring($OutputRoot.Length + 1) } |
    Set-Content -LiteralPath (Join-Path $OutputRoot 'manifest-sha256.txt') -Encoding ascii

Write-Host "Dados preparados em: $OutputRoot"
Write-Host 'Copie o conteudo para ux0:data/undertale-yellow/ no PS Vita.'
