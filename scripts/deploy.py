"""Deploy updated files to VPS via SFTP and restart agent-api."""
import os
import sys
import paramiko

HOST = "77.239.107.30"
USER = "root"
BASE = "/opt/agent-api"

files = [
    "app/services/replay_guard.py",
    "app/services/credits.py",
    "app/services/analytics.py",
    "app/services/rate_limiter.py",
    "app/services/deepseek.py",
    "app/services/cache.py",
    "app/services/blockchain_listener.py",
    "app/models.py",
    "app/main.py",
    "app/well_known.py",
    "app/mcp_server.py",
    "app/x402_setup.py",
    "app/facilitator.py",
    "app/config.py",
    "app/cdp_auth.py",
    "app/pricing.py",
    ".env",
    "requirements.txt",
    "app/routes/__init__.py",
    "app/routes/billing.py",
    "app/routes/audit.py",
    "app/routes/refactor.py",
    "app/routes/docs.py",
    "app/routes/defi.py",
    "app/routes/trading.py",
    "app/routes/micro.py",
    "app/routes/solidity_scan.py",
    "app/routes/stream.py",
    "app/routes/security.py",
    "app/routes/defi_signals.py",
    "app/routes/data_feed.py",
    "app/prompts/__init__.py",
    "app/prompts/audit.py",
    "app/prompts/refactor.py",
    "app/prompts/docs.py",
    "app/prompts/defi.py",
    "app/prompts/trading.py",
    "app/prompts/solidity_scan.py",
    "app/prompts/micro.py",
    "app/prompts/security.py",
    "app/prompts/defi_signals.py",
    "app/prompts/data_feed.py",
    "scripts/setup_https.sh",
    "scripts/monitor.sh",
    "scripts/backup.sh",
    "scripts/integration_test.py",
]

local_base = os.environ.get("AGENT_API_SRC", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

password = os.environ.get("VPS_PASSWORD")
ssh_key_path = os.path.expanduser("~/.ssh/id_rsa")

if password:
    ssh.connect(HOST, username=USER, password=password, timeout=15)
elif os.path.exists(ssh_key_path):
    ssh.connect(HOST, username=USER, key_filename=ssh_key_path, timeout=15)
else:
    print("ERROR: No authentication method available.")
    print("Set VPS_PASSWORD environment variable or ensure ~/.ssh/id_rsa exists.")
    sys.exit(1)
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
out = stdout.read().decode(errors='replace')
err = stderr.read().decode(errors='replace')
print(out.encode('ascii', errors='replace').decode())
if err:
    print("STDERR:", err.encode("ascii", errors="replace").decode())

# Check logs for errors
stdin, stdout, stderr = ssh.exec_command(
    "journalctl -u agent-api --no-pager -n 5"
)
print("\nRecent logs:")
print(stdout.read().decode(errors='replace').encode('ascii', errors='replace').decode())

ssh.close()
print("\nDone.")
