param(
    [Parameter(Mandatory = $false)]
    [string]$SensorHostDirectory = (Join-Path $PSScriptRoot "sensorhost")
)

$ErrorActionPreference = "Stop"

function Test-SensorHostExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$Executable
    )

    # 真实的自包含 SensorHost 远大于 1 MB，Git LFS 指针通常只有几百字节。
    if ($Executable.Length -lt 1MB) {
        $preview = [System.IO.File]::ReadAllText($Executable.FullName)
        if ($preview.StartsWith("version https://git-lfs.github.com/spec/")) {
            throw "SensorHost 仍是 Git LFS 指针，未拉取真实 EXE：$($Executable.FullName)"
        }
        throw "SensorHost 文件过小，可能下载或检出不完整：$($Executable.FullName) ($($Executable.Length) bytes)"
    }

    $stream = [System.IO.File]::OpenRead($Executable.FullName)
    $reader = [System.IO.BinaryReader]::new($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5A4D) {
            throw "SensorHost 缺少 MZ 文件头：$($Executable.FullName)"
        }

        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        if ($peOffset -lt 0 -or $peOffset -gt ($stream.Length - 6)) {
            throw "SensorHost PE 文件头偏移无效：$($Executable.FullName)"
        }

        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            throw "SensorHost 缺少 PE 签名：$($Executable.FullName)"
        }

        $machine = $reader.ReadUInt16()
        if ($machine -ne 0x8664) {
            throw ("SensorHost 不是 Windows x64 可执行文件：machine=0x{0:X4}, path={1}" -f $machine, $Executable.FullName)
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $SensorHostDirectory -PathType Container)) {
    throw "SensorHost 目录不存在：$SensorHostDirectory"
}

$executables = @(Get-ChildItem -LiteralPath $SensorHostDirectory -Filter "OmniWatch.SensorHost-v*.exe" -File)
if ($executables.Count -eq 0) {
    throw "SensorHost 目录中未找到版本化 EXE：$SensorHostDirectory"
}

foreach ($executable in $executables) {
    Test-SensorHostExecutable -Executable $executable
    Write-Host "SensorHost 校验通过：$($executable.Name) ($($executable.Length) bytes, Windows x64)"
}
