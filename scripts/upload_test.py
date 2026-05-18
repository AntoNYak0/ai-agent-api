#!/usr/bin/env python3
"""Upload test script to VPS and execute it using SSH with password auth."""
import subprocess
import sys
import os

HOST = "77.239.107.30"
USER = "root"
PASSWORD = "zW8rW6eU3rgZ"
REMOTE_PATH = "/opt/agent-api/test_full.sh"
SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

def run_ssh(remote_cmd, timeout=60):
    """Run a command on the VPS via SSH, handling password prompt."""
    cmd = [
        "ssh", SSH_OPTS.split()[0], SSH_OPTS.split()[1],
        SSH_OPTS.split()[2], SSH_OPTS.split()[3],
        f"{USER}@{HOST}",
        remote_cmd
    ]
    # Flatten: some opts have = sign so split might not work perfectly
    cmd = f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -tt {USER}@{HOST} "{remote_cmd}"'

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )

    stdout_data = []
    stderr_data = []
    password_sent = False

    def read_output():
        """Read all available output."""
        import select
        import time
        nonlocal password_sent

        start = time.time()
        while time.time() - start < timeout:
            # Check if process is done
            ret = proc.poll()
            # Read from stdout/stderr
            out_line = proc.stdout.readline() if proc.stdout else ''
            err_line = proc.stderr.readline() if proc.stderr else ''

            if out_line:
                stdout_data.append(out_line)
                sys.stdout.write(out_line)
                sys.stdout.flush()
                # Check for password prompt
                if not password_sent and ('password:' in out_line.lower() or 'assword:' in out_line.lower()):
                    proc.stdin.write(PASSWORD + '\n')
                    proc.stdin.flush()
                    password_sent = True

            if err_line:
                stderr_data.append(err_line)
                sys.stderr.write(err_line)
                sys.stderr.flush()
                if not password_sent and ('password:' in err_line.lower() or 'assword:' in err_line.lower()):
                    proc.stdin.write(PASSWORD + '\n')
                    proc.stdin.flush()
                    password_sent = True

            if ret is not None:
                # Drain remaining output
                for line in proc.stdout or []:
                    stdout_data.append(line)
                    sys.stdout.write(line)
                for line in proc.stderr or []:
                    stderr_data.append(line)
                    sys.stderr.write(line)
                break

            time.sleep(0.1)

        # If still running after timeout, kill it
        if proc.poll() is None:
            proc.kill()

        return '\n'.join(stdout_data), '\n'.join(stderr_data)

    return read_output()


# Read the local test script
with open(r"C:\Users\Admin\Desktop\test_full.sh", "r", encoding="utf-8") as f:
    script_content = f.read()

# Escape single quotes for the remote shell
# Use a different heredoc approach - write via base64
import base64
encoded = base64.b64encode(script_content.encode()).decode()
# On remote, decode and write
write_cmd = f"echo {encoded} | base64 -d > {REMOTE_PATH} && chmod +x {REMOTE_PATH} && echo 'Uploaded OK'"

print("=" * 60)
print("STEP 1: Uploading test script to VPS...")
print("=" * 60)
stdout1, stderr1 = run_ssh(write_cmd, timeout=30)
print(stdout1)
if stderr1.strip():
    print("STDERR:", stderr1)

print("\n" + "=" * 60)
print("STEP 2: Running test script...")
print("=" * 60)
stdout2, stderr2 = run_ssh(f"cd /opt/agent-api && bash {REMOTE_PATH}", timeout=180)
print(stdout2)
if stderr2.strip():
    print("STDERR:", stderr2)

print("\n" + "=" * 60)
print("ALL DONE.")
print("=" * 60)