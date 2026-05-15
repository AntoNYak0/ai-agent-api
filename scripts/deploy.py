"""Deploy updated files to VPS via SFTP and restart agent-api."""
import os
import paramiko

HOST = "77.239.107.30"
USER = "root"
PASS = "zW8rW6eU3rgZ"
BASE = "/opt/agent-api"

files = [
    "app/services/replay_guard.py",
    "app/services/credits.py",
    "app/services/analytics.py",
    "app/services/rate_limiter.py",
    "app/models.py",
    "app/main.py",
    "app/well_known.py",
    "app/mcp_server.py",
    "app/x402_setup.py",
    "app/facilitator.py",
    "app/config.py",
    ".env",
    "app/routes/billing.py",
    "app/routes/audit.py",
    "app/routes/refactor.py",
    "app/routes/docs.py",
    "app/routes/defi.py",
    "app/routes/trading.py",
    "app/routes/micro.py",
    "app/routes/solidity_scan.py",
    "app/routes/stream.py",
    "app/services/deepseek.py",
]

local_base = r"c:\Users\Admin\Desktop\agent-api"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)
sftp = ssh.open_sftp()

for f in files:
    local = local_base + "\\" + f.replace("/", "\\")
    remote = f"{BASE}/{f}"
    # Ensure remote dir exists
    remote_dir = os.path.dirname(remote)
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        sftp.mkdir(remote_dir)
        print(f"Created dir: {remote_dir}")
    print(f"Uploading {f} ...", end=" ", flush=True)
    sftp.put(local, remote)
    print("OK")

sftp.close()

print("\nRestarting agent-api...")
stdin, stdout, stderr = ssh.exec_command(
    "systemctl restart agent-api && sleep 2 && curl -s http://localhost:8000/health"
)
out = stdout.read().decode()
err = stderr.read().decode()
print(out)
if err:
    print("STDERR:", err)

# Check logs for errors
stdin, stdout, stderr = ssh.exec_command(
    "journalctl -u agent-api --no-pager -n 5"
)
print("\nRecent logs:")
print(stdout.read().decode())

ssh.close()
print("\nDone.")
