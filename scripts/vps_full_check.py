#!/usr/bin/env python3
"""Upload test script to VPS and run all system checks via paramiko SSH."""
import paramiko
import os
import sys

# Handle encoding for Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() in ('cp1252', 'cp1251', 'windows-1252'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def sp(text):
    """Print text safely, replacing unencodable characters."""
    try:
        sys.stdout.buffer.write(str(text).encode('utf-8', errors='replace') + b'\n')
        sys.stdout.buffer.flush()
    except:
        pass

HOST = "77.239.107.30"
USER = "root"
PASSWORD = "zW8rW6eU3rgZ"
REMOTE_SCRIPT_PATH = "/opt/agent-api/test_full.sh"
LOCAL_SCRIPT_PATH = r"C:\Users\Admin\Desktop\test_full.sh"

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sp(f"Connecting to {HOST}...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    sp("Connected!")
    return client

def upload_file(client, local_path, remote_path):
    sftp = client.open_sftp()
    try:
        remote_dir = os.path.dirname(remote_path)
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            sp(f"Creating remote directory: {remote_dir}")
            path_parts = remote_dir.split('/')
            current = ''
            for part in path_parts:
                if part:
                    current += '/' + part
                    try:
                        sftp.stat(current)
                    except FileNotFoundError:
                        sftp.mkdir(current)

        sp(f"Uploading {local_path} -> {remote_path}...")
        sftp.put(local_path, remote_path)
        sp("Upload complete!")
        client.exec_command(f"chmod +x {remote_path}")
        sp("Made executable.")
    finally:
        sftp.close()

def run_cmd(client, command, timeout=30):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout, get_pty=True)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    return out, err, exit_code

def print_section(title):
    sp("")
    sp("=" * 70)
    sp(title)
    sp("=" * 70)

def main():
    client = None
    try:
        client = ssh_connect()

        # Step 1: Upload the test script
        print_section("STEP 1: Uploading test script")
        upload_file(client, LOCAL_SCRIPT_PATH, REMOTE_SCRIPT_PATH)

        # Step 2: Run the test script
        print_section("STEP 2: Running API endpoint tests from VPS")
        out, err, code = run_cmd(client, f"cd /opt/agent-api && bash {REMOTE_SCRIPT_PATH}", timeout=180)
        sp(out)
        if err.strip():
            sp(f"STDERR: {err[:500]}")

        # Step 3: Blockchain listener check
        print_section("STEP 3: Blockchain Listener Check")
        out, _, _ = run_cmd(client,
            r"""journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i -E "listener|started|blockchain" || echo "LISTENER_NOT_FOUND" """,
            timeout=15)
        if "LISTENER_NOT_FOUND" not in out and out.strip():
            sp("FOUND in logs:")
            sp(out)
        else:
            sp("Listener status not found in journalctl grep, trying broader search...")
            out2, _, _ = run_cmd(client,
                r"""journalctl -u agent-api --no-pager -n 100 2>/dev/null || echo "NO_JOURNALCTL" """,
                timeout=15)
            sp(out2[:2000])

        # Step 4: Recent logs
        print_section("STEP 4: Recent Logs (last 30 lines)")
        out, _, _ = run_cmd(client,
            r"""journalctl -u agent-api --no-pager -n 30 2>/dev/null || echo "NO_LOGS" """,
            timeout=15)
        sp(out)

        # Step 5: Error check
        print_section("STEP 5: Error Check")
        out, _, _ = run_cmd(client,
            r"""journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i -E "error|critical|exception|traceback|failed" | head -10 || echo "NO_ERRORS_FOUND" """,
            timeout=15)
        if "NO_ERRORS_FOUND" in out:
            sp("No errors found in recent logs.")
        else:
            sp("ERRORS FOUND:")
            sp(out)

        # Step 6: Service status
        print_section("STEP 6: Service Status")
        out, _, _ = run_cmd(client,
            r"""systemctl status agent-api --no-pager 2>/dev/null | head -20 || echo "NO_SYSTEMCTL" """,
            timeout=10)
        sp(out)

        # Step 7: Process check
        print_section("STEP 7: Process Check")
        out, _, _ = run_cmd(client,
            r"""ps aux | grep -E "agent-api|python3|node" | grep -v grep | head -15 || echo "NO_PROCESSES" """,
            timeout=10)
        sp(out)

        # Step 8: System resources
        print_section("STEP 8: System Resources")
        out, _, _ = run_cmd(client,
            r"""echo "--- DISK ---" && df -h / 2>/dev/null && echo "--- MEMORY ---" && free -h 2>/dev/null && echo "--- UPTIME ---" && uptime && echo "--- DOCKER ---" && docker ps 2>/dev/null || echo "NO_DOCKER" """,
            timeout=15)
        sp(out)

        # Step 9: Config and Deployment Info
        print_section("STEP 9: Config and Deployment Info")
        out, _, _ = run_cmd(client,
            r"""ls -la /opt/agent-api/ 2>/dev/null | head -20 && echo "---" && ls -la /etc/agent-api/ 2>/dev/null | head -10 || echo "NO_ETC_CONFIG" """,
            timeout=10)
        sp(out)

        # Step 10: Verify 402 response from VPS
        print_section("STEP 10: Verify 402 response from VPS")
        out, _, _ = run_cmd(client,
            r"""curl -s -X POST --max-time 10 https://agent-api-ai.duckdns.org/api/audit 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
d.pop('detail',None)
print(json.dumps(d, indent=2))
" 2>/dev/null || curl -s -X POST --max-time 10 https://agent-api-ai.duckdns.org/api/audit | head -3""",
            timeout=15)
        sp(out)

        # Step 11: Check /health/deep from VPS
        print_section("STEP 11: Check /health/deep from VPS")
        out, _, _ = run_cmd(client,
            r"""curl -sv --max-time 10 https://agent-api-ai.duckdns.org/health/deep 2>&1 | tail -20 || echo "CURL_FAILED" """,
            timeout=20)
        sp(out)

    except Exception as e:
        sp(f"\nERROR: {e}")
        import traceback
        sp(traceback.format_exc())
    finally:
        if client:
            client.close()
            sp("\nSSH connection closed.")

    sp("")
    sp("=" * 70)
    sp("VPS CHECKS COMPLETE")
    sp("=" * 70)

if __name__ == "__main__":
    main()