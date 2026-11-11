$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$version = '1.1'
$releaseName = "CLA_$version"
$releaseRoot = Join-Path $PSScriptRoot 'release'
$releaseFolder = Join-Path $releaseRoot $releaseName
$archive = Join-Path $releaseRoot "$releaseName.zip"
$distFolder = Join-Path $PSScriptRoot 'dist\Chaos Loss Aversion'

$required = @('main.py', 'requirements.txt', 'README.txt', 'Images\Chaos Orb.ico', 'Images\Chaos Loss Aversion Logo.png', 'Images\Tier Twolongs Banner.png')
foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath $item)) { throw "Missing build asset: $item. Import the complete production Images folder before building." }
}

py -3.12 -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python virtual environment' }
$python = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Failed to update pip' }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install requirements' }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed --name 'Chaos Loss Aversion' --icon 'Images\Chaos Orb.ico' --add-data 'Images;Images' --add-data 'Audio Clips;Audio Clips' --add-data 'README.txt;.' --collect-all dxcam main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
if (-not (Test-Path (Join-Path $distFolder 'Chaos Loss Aversion.exe'))) { throw 'Built executable not found' }

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
if (Test-Path $releaseFolder) { Remove-Item $releaseFolder -Recurse -Force }
Copy-Item -LiteralPath $distFolder -Destination $releaseFolder -Recurse
Copy-Item -LiteralPath 'README.txt' -Destination (Join-Path $releaseFolder 'README.txt') -Force
if (Test-Path $archive) { Remove-Item $archive -Force }
Compress-Archive -LiteralPath $releaseFolder -DestinationPath $archive -CompressionLevel Optimal

Write-Host "Created $archive"
Write-Host 'Extract the ZIP, open the CLA folder, and run Chaos Loss Aversion.exe. Keep the _internal folder beside it.'
