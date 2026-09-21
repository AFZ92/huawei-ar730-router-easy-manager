# One-command Windows installer. Run with:
#   irm https://raw.githubusercontent.com/AFZ92/huawei-ar730-router-easy-manager/main/scripts/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$repo = 'AFZ92/huawei-ar730-router-easy-manager'
$release = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ Accept = 'application/vnd.github+json' }
$assetName = 'AR730Manager-Windows-x64-Setup.exe'
$asset = @($release.assets | Where-Object name -eq $assetName)[0]
$checksums = @($release.assets | Where-Object name -eq 'SHA256SUMS.txt')[0]
if (-not $asset -or -not $checksums) { throw 'The latest release is missing its Windows installer or SHA256SUMS.txt.' }
$dir = Join-Path $env:TEMP ('ar730-manager-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $dir | Out-Null
$installer = Join-Path $dir $assetName
$sumsFile = Join-Path $dir 'SHA256SUMS.txt'
Invoke-WebRequest $asset.browser_download_url -OutFile $installer
Invoke-WebRequest $checksums.browser_download_url -OutFile $sumsFile
$expected = ((Get-Content $sumsFile | Where-Object { $_ -match ([regex]::Escape($assetName) + '$') }) -split '\s+')[0].ToLower()
$actual = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
if (-not $expected -or $actual -ne $expected) { throw 'SHA-256 verification failed. The installer was not run.' }
Start-Process -FilePath $installer -Wait
