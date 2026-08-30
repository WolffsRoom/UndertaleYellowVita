param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
    [string]$Version = '0.1'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'src\vita'
$sourceMount = (Join-Path $root 'src').Replace('\', '/')
$thirdPartyMount = (Join-Path $root 'third_party').Replace('\', '/')
$assetsMount = (Join-Path $root 'data\assets').Replace('\', '/')
$artifactsDir = Join-Path $root 'artifacts'

if (-not (Test-Path $artifactsDir)) {
    New-Item -ItemType Directory -Path $artifactsDir -Force | Out-Null
}

docker run --rm `
    -v "${sourceMount}:/project/src" `
    -v "${thirdPartyMount}:/project/third_party:ro" `
    -v "${assetsMount}:/project/data/assets:ro" `
    -w /project/src/vita `
    atamanenko/vitasdk-softfp:latest sh -lc `
    "cmake -S . -B build -DCMAKE_BUILD_TYPE=$Configuration && cmake --build build -j2"

if ($LASTEXITCODE -ne 0) { throw "Build falhou com codigo $LASTEXITCODE." }

$builtVpk = Join-Path $project 'build\UndertaleYellow.vpk'
$destVpk = Join-Path $artifactsDir "UndertaleYellowVita-v$Version.vpk"

if (Test-Path $builtVpk) {
    Copy-Item $builtVpk $destVpk -Force
    Write-Host "VPK gerado com sucesso em: $destVpk"
} else {
    throw "Arquivo $builtVpk nao foi encontrado apos o build."
}
