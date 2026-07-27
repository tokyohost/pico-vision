<# 下载并校验 Microsoft Edge WebView2 Evergreen Bootstrapper。 #>

[CmdletBinding()]
param(
    [string]$OutputPath = "$PSScriptRoot\dist\MicrosoftEdgeWebview2Setup.exe",
    [string]$DownloadUrl = "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
    [switch]$InstallIfMissing
)

$ErrorActionPreference = "Stop"

function Get-WebView2RuntimeVersion {
    <# 按用户级、64 位机器级和 32 位机器级位置读取 Evergreen Runtime 版本。 #>
    $registryPaths = @(
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    foreach ($registryPath in $registryPaths) {
        try {
            $version = (Get-ItemProperty -LiteralPath $registryPath -Name "pv" -ErrorAction Stop).pv
            if (($version -is [string]) -and
                (-not [string]::IsNullOrWhiteSpace($version)) -and
                ($version -ne "0.0.0.0")) {
                return $version.Trim()
            }
        }
        catch {
            continue
        }
    }
    return $null
}

if ($InstallIfMissing) {
    $installedVersion = Get-WebView2RuntimeVersion
    if ($null -ne $installedVersion) {
        Write-Host "已检测到 Microsoft Edge WebView2 Runtime：$installedVersion"
        return
    }
}

$resolvedOutputPath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$temporaryPath = Join-Path $outputDirectory (
    ".webview2-{0}.download" -f [Guid]::NewGuid().ToString("N")
)

try {
    Write-Host "正在从 Microsoft 下载 WebView2 Evergreen Bootstrapper..."
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $temporaryPath -UseBasicParsing

    $stream = [IO.File]::OpenRead($temporaryPath)
    try {
        if (($stream.ReadByte() -ne 0x4D) -or ($stream.ReadByte() -ne 0x5A)) {
            throw "下载内容不是有效的 Windows PE 文件"
        }
    }
    finally {
        $stream.Dispose()
    }

    $signature = Get-AuthenticodeSignature -FilePath $temporaryPath
    if (($signature.Status -ne "Valid") -or
        ($signature.SignerCertificate.Subject -notmatch "Microsoft Corporation")) {
        throw "WebView2 Bootstrapper 的 Microsoft 数字签名校验失败：$($signature.Status)"
    }

    Move-Item -LiteralPath $temporaryPath -Destination $resolvedOutputPath -Force
    Write-Host "WebView2 Bootstrapper 已准备完成：$resolvedOutputPath"

    if ($InstallIfMissing) {
        Write-Host "正在静默安装 Microsoft Edge WebView2 Runtime..."
        $installer = Start-Process -FilePath $resolvedOutputPath `
            -ArgumentList "/silent", "/install" -Wait -PassThru
        if ($installer.ExitCode -ne 0) {
            throw "WebView2 Runtime 安装失败，退出代码：$($installer.ExitCode)"
        }
        $installedVersion = Get-WebView2RuntimeVersion
        if ($null -eq $installedVersion) {
            throw "WebView2 Runtime 安装完成，但注册表中仍未检测到有效版本"
        }
        Write-Host "Microsoft Edge WebView2 Runtime 已就绪：$installedVersion"
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}
