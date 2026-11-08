# 下载并校验固定版本的 PawnIO 官方安装程序，避免构建过程使用未经校验的可变制品。
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$pawnIoVersion = "2.2.0"
$pawnIoSha256 = "1F519A22E47187F70A1379A48CA604981C4FCF694F4E65B734AAA74A9FBA3032"
$pawnIoUrl = "https://github.com/namazso/PawnIO.Setup/releases/download/$pawnIoVersion/PawnIO_setup.exe"
$resolvedOutputPath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutputPath

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
# 重跑构建时仅复用哈希匹配的固定版本，避免重复请求发布服务器。
if ((Test-Path -LiteralPath $resolvedOutputPath -PathType Leaf) -and
    ((Get-FileHash -LiteralPath $resolvedOutputPath -Algorithm SHA256).Hash -eq $pawnIoSha256)) {
    Write-Host "PawnIO $pawnIoVersion 安装程序已存在并通过 SHA256 校验：$resolvedOutputPath"
    return
}

$temporaryPath = Join-Path $outputDirectory (".pawnio-{0}.download" -f [Guid]::NewGuid().ToString("N"))
$maximumAttempts = 5
try {
    # 下载失败只清理本次临时文件，避免半成品覆盖正式安装程序。
    for ($attempt = 1; $attempt -le $maximumAttempts; $attempt++) {
        try {
            Write-Host "正在下载 PawnIO $pawnIoVersion（第 $attempt/$maximumAttempts 次）..."
            Invoke-WebRequest -Uri $pawnIoUrl -OutFile $temporaryPath -TimeoutSec 120 -ErrorAction Stop
        }
        catch {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
            if ($attempt -eq $maximumAttempts) {
                throw "PawnIO 下载失败，已尝试 $maximumAttempts 次：$($_.Exception.Message)；地址：$pawnIoUrl"
            }
            $delaySeconds = [int][Math]::Min(40, 5 * [Math]::Pow(2, $attempt - 1))
            Write-Warning "PawnIO 下载失败：$($_.Exception.Message)；将在 $delaySeconds 秒后重试。"
            Start-Sleep -Seconds $delaySeconds
            continue
        }

        # 校验失败立即终止，不能把错误页面或异常制品交给安装包构建步骤。
        $actualSha256 = (Get-FileHash -LiteralPath $temporaryPath -Algorithm SHA256).Hash
        if ($actualSha256 -ne $pawnIoSha256) {
            throw "PawnIO 安装程序 SHA256 校验失败：expected=$pawnIoSha256 actual=$actualSha256"
        }
        Move-Item -LiteralPath $temporaryPath -Destination $resolvedOutputPath -Force
        Write-Host "PawnIO $pawnIoVersion 安装程序已下载并通过 SHA256 校验：$resolvedOutputPath"
        return
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}
