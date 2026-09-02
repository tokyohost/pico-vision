# 下载并校验固定版本的 PawnIO 官方安装程序，避免构建过程使用未经校验的可变制品。
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$pawnIoVersion = "2.2.0"
$pawnIoSha256 = "1F519A22E47187F70A1379A48CA604981C4FCF694F4E65B734AAA74A9FBA3032"
$pawnIoUrl = "https://github.com/namazso/PawnIO.Setup/releases/download/$pawnIoVersion/PawnIO_setup.exe"
$resolvedOutputPath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutputPath

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
Invoke-WebRequest -Uri $pawnIoUrl -OutFile $resolvedOutputPath

$actualSha256 = (Get-FileHash -LiteralPath $resolvedOutputPath -Algorithm SHA256).Hash
if ($actualSha256 -ne $pawnIoSha256) {
    Remove-Item -LiteralPath $resolvedOutputPath -Force -ErrorAction SilentlyContinue
    throw "PawnIO 安装程序 SHA256 校验失败：expected=$pawnIoSha256 actual=$actualSha256"
}

Write-Host "PawnIO $pawnIoVersion 安装程序已下载并通过 SHA256 校验：$resolvedOutputPath"
