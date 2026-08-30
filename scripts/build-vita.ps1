param([ValidateSet('Debug','Release')][string]$Configuration = 'Debug')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'src\vita'
$sourceMount = (Join-Path $root 'src').Replace('\', '/')
$thirdPartyMount = (Join-Path $root 'third_party').Replace('\', '/')
$assetsMount = (Join-Path $root 'data\assets').Replace('\', '/')

docker run --rm `
    -v "${sourceMount}:/project/src" `
    -v "${thirdPartyMount}:/project/third_party:ro" `
    -v "${assetsMount}:/project/data/assets:ro" `
    -w /project/src/vita `
    atamanenko/vitasdk-softfp:latest sh -lc `
    "cmake -S . -B build -DCMAKE_BUILD_TYPE=$Configuration && cmake --build build -j2"

if ($LASTEXITCODE -ne 0) { throw "Build falhou com codigo $LASTEXITCODE." }
Write-Host "VPK: $project\build\UndertaleYellow.vpk"
