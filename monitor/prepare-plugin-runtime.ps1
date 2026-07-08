param(
    [string]$OutputDirectory = "$PSScriptRoot\dist\plugin-runtime",
    [string]$PythonVersion = "3.13.5",
    [ValidateSet("python", "pythonx86")]
    [string]$PackageId = "python"
)

$ErrorActionPreference = "Stop"

function Get-PythonRuntimePackage {
    <# 下载官方 NuGet 便携 Python 包，避免在构建机注册安装信息。 #>
    param(
        [string]$Version,
        [string]$PythonPackageId,
        [string]$Destination
    )

    $downloadUrl = "https://www.nuget.org/api/v2/package/$PythonPackageId/$Version"
    Write-Host "正在下载插件 Python Runtime：$downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $Destination
}

function Expand-PythonRuntimePackage {
    <# 解压 NuGet 包中的 tools 目录并生成可随安装包分发的 Runtime。 #>
    param(
        [string]$PackagePath,
        [string]$Destination,
        [string]$TemporaryDirectory
    )

    Expand-Archive -LiteralPath $PackagePath -DestinationPath $TemporaryDirectory -Force
    $toolsDirectory = Join-Path $TemporaryDirectory "tools"
    if (-not (Test-Path -LiteralPath (Join-Path $toolsDirectory "python.exe"))) {
        throw "NuGet Python 包缺少 tools\python.exe"
    }
    Copy-Item -Path (Join-Path $toolsDirectory "*") -Destination $Destination -Recurse -Force
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $resolvedOutput) {
    Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null

$packagePath = Join-Path $env:TEMP "omniwatch-python-$PythonVersion.nupkg.zip"
$temporaryDirectory = Join-Path $env:TEMP "omniwatch-python-runtime-$([guid]::NewGuid().ToString('N'))"
try {
    Get-PythonRuntimePackage -Version $PythonVersion -PythonPackageId $PackageId -Destination $packagePath
    Expand-PythonRuntimePackage -PackagePath $packagePath -Destination $resolvedOutput -TemporaryDirectory $temporaryDirectory
    $runtimePython = Join-Path $resolvedOutput "python.exe"
    & $runtimePython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        throw "插件 Runtime 的 ensurepip 初始化失败"
    }
    & $runtimePython -m pip --version
    if ($LASTEXITCODE -ne 0) {
        throw "插件 Runtime 中的 pip 校验失败"
    }
    $validationEnvironment = Join-Path $temporaryDirectory "venv-check"
    & $runtimePython -m venv $validationEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "插件 Runtime 创建独立虚拟环境校验失败"
    }
    Write-Host "插件 Python Runtime 已生成：$resolvedOutput"
}
finally {
    Remove-Item -LiteralPath $packagePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
