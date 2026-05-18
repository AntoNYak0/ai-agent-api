# PowerShell script to run VPS checks
# Uses SSH with password authentication via sshpass-like approach

$hostname = "77.239.107.30"
$user = "root"
$password = "zW8rW6eU3rgZ"
$sshPath = "C:\Windows\System32\OpenSSH\ssh.exe"

if (-not (Test-Path $sshPath)) {
    Write-Host "Windows SSH not found at $sshPath" -ForegroundColor Red
    exit 1
}

function Run-SSH {
    param([string]$Command)

    # Create a temporary VBScript to handle SSH password
    $vbscript = @"
Dim WshShell, oExec
Set WshShell = CreateObject("WScript.Shell")
Set oExec = WshShell.Exec("$sshPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PreferredAuthentications=password $user@$hostname $Command")
Do While oExec.Status = 0
    WScript.Sleep 100
    If Not oExec.StdErr.AtEndOfStream Then
        errLine = oExec.StdErr.ReadLine()
        If InStr(LCase(errLine), "password") Then
            oExec.StdIn.WriteLine "$password"
        End If
    End If
Loop
WScript.Echo oExec.StdOut.ReadAll()
WScript.Echo oExec.StdErr.ReadAll()
"@

    $vbsFile = [System.IO.Path]::GetTempFileName() + ".vbs"
    Set-Content -Path $vbsFile -Value $vbscript -Force
    $result = & cscript //nologo $vbsFile
    Remove-Item $vbsFile -Force
    return $result
}

Write-Host "=== VPS System Checks ===" -ForegroundColor Cyan

Write-Host "`n--- Blockchain Listener ---" -ForegroundColor Yellow
$out = Run-SSH "journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i 'listener\|started\|blockchain' || echo 'NOT_FOUND'"
Write-Host $out

Write-Host "`n--- Recent Logs (30 lines) ---" -ForegroundColor Yellow
$out = Run-SSH "journalctl -u agent-api --no-pager -n 30 2>/dev/null || echo 'NO_JOURNAL'"
Write-Host $out

Write-Host "`n--- Error Check ---" -ForegroundColor Yellow
$out = Run-SSH "journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i 'error\|critical\|exception\|traceback' | head -10 || echo 'NO_ERRORS'"
Write-Host $out

Write-Host "`n--- Service Status ---" -ForegroundColor Yellow
$out = Run-SSH "systemctl status agent-api 2>/dev/null | head -15 || echo 'NO_SYSTEMCTL'"
Write-Host $out

Write-Host "`n--- Process Check ---" -ForegroundColor Yellow
$out = Run-SSH "ps aux | grep agent-api | grep -v grep || echo 'NOT_RUNNING'"
Write-Host $out

Write-Host "`n--- Disk / Memory ---" -ForegroundColor Yellow
$out = Run-SSH "df -h / 2>/dev/null; echo '---'; free -h 2>/dev/null; echo '---'; uptime"
Write-Host $out

Write-Host "`n=== DONE ===" -ForegroundColor Cyan