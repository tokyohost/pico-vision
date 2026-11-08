"""通过 PowerShell 命令替身验证 PawnIO 下载重试与校验行为。"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


POWERSHELL = shutil.which("pwsh")
SCRIPT = Path(__file__).resolve().parents[1] / "prepare-pawnio-installer.ps1"


@unittest.skipUnless(POWERSHELL, "需要 PowerShell 7 执行下载脚本行为测试")
class PawnIoDownloadTests(unittest.TestCase):
    """隔离网络及等待，运行真实下载脚本并检查落盘结果。"""

    def run_download(self, failures=0, corrupt=False, existing=""):
        """模拟发布服务器故障和校验结果，返回脚本执行报告。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "PawnIO_setup.exe"
            if existing:
                output.write_text(existing, encoding="utf-8")
            harness = root / "verify.ps1"
            script_path = str(SCRIPT).replace("'", "''")
            harness.write_text("""
param([int]$Failures, [int]$Corrupt)
$ErrorActionPreference = 'Stop'
$global:pawnIoTestAttempts = 0
$global:pawnIoTestDelays = @()
function Invoke-WebRequest {
    <# 模拟下载途中产生半成品以及暂时性的 504 错误。 #>
    param($Uri, $OutFile, $TimeoutSec, $ErrorAction)
    $global:pawnIoTestAttempts++
    [IO.File]::WriteAllText($OutFile, 'partial')
    if ($global:pawnIoTestAttempts -le $Failures) { throw '504 Gateway Time-out' }
    if (-not $Corrupt) { [IO.File]::WriteAllText($OutFile, 'verified') }
}
function Start-Sleep {
    <# 记录退避时间，不让测试真实等待。 #>
    param($Seconds)
    $global:pawnIoTestDelays += $Seconds
}
function Get-FileHash {
    <# 仅将测试的完整制品映射到固定版本哈希，其余内容模拟校验失败。 #>
    param($LiteralPath, $Algorithm)
    $hash = if ([IO.File]::ReadAllText($LiteralPath) -eq 'verified') {
        '1F519A22E47187F70A1379A48CA604981C4FCF694F4E65B734AAA74A9FBA3032'
    } else { 'INVALID' }
    [pscustomobject]@{ Hash = $hash }
}
$target = Join-Path $PSScriptRoot 'PawnIO_setup.exe'
$failure = ''
try { & '__SCRIPT__' -OutputPath $target } catch { $failure = $_.Exception.Message }
$content = if (Test-Path -LiteralPath $target) { [IO.File]::ReadAllText($target) } else { '' }
[pscustomobject]@{
    attempts = $global:pawnIoTestAttempts; delays = @($global:pawnIoTestDelays); error = $failure; content = $content
    temporary = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.download' -Force).Count
} | ConvertTo-Json -Compress
""".replace("__SCRIPT__", script_path), encoding="utf-8")
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(harness),
                 "-Failures", str(failures), "-Corrupt", str(int(corrupt))],
                capture_output=True, text=True, encoding="utf-8", timeout=30, check=True,
            )
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_transient_gateway_failure_recovers(self):
        """两次 504 后成功，并采用递增退避及清理临时文件。"""
        result = self.run_download(failures=2)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["delays"], [5, 10])
        self.assertEqual(result["content"], "verified")
        self.assertEqual(result["error"], "")
        self.assertEqual(result["temporary"], 0)

    def test_permanent_failure_is_bounded(self):
        """持续失败只尝试五次，不留下可被安装器误用的半成品。"""
        result = self.run_download(failures=99)
        self.assertEqual(result["attempts"], 5)
        self.assertEqual(result["delays"], [5, 10, 20, 40])
        self.assertIn("504", result["error"])
        self.assertEqual(result["content"], "")
        self.assertEqual(result["temporary"], 0)

    def test_hash_failure_preserves_existing_output(self):
        """校验失败立即退出，不覆盖旧输出，也不将异常内容视为成功。"""
        result = self.run_download(corrupt=True, existing="old")
        self.assertEqual(result["attempts"], 1)
        self.assertIn("SHA256", result["error"])
        self.assertEqual(result["content"], "old")
        self.assertEqual(result["temporary"], 0)

    def test_valid_existing_installer_avoids_network(self):
        """已有制品通过哈希校验后不再访问发布服务器。"""
        result = self.run_download(existing="verified")
        self.assertEqual(result["attempts"], 0)
        self.assertEqual(result["content"], "verified")
        self.assertEqual(result["error"], "")
