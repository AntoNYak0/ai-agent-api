#!/usr/bin/env python3
"""Run system checks on VPS via SSH with password authentication."""
import subprocess
import sys
import os
import threading
import time

HOST = "77.239.107.30"
USER = "root"
PASSWORD = "zW8rW6eU3rgZ"

def run_ssh_command(remote_cmd, timeout=60):
    """Run a command on the VPS, return stdout, stderr."""
    cmd = f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -tt {USER}@{HOST} "{remote_cmd}"'

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=0
    )

    password_sent = threading.Event()
    password_sent.clear()
    stdout_lines = []
    stderr_lines = []

    def read_thread(stream, lines_list, is_stderr=False):
        while True:
            try:
                line = stream.readline()
                if not line:
                    break
                lines_list.append(line)
                # Check for password prompt
                if not password_sent.is_set() and ('password:' in line.lower()):
                    password_sent.set()
            except:
                break

    def write_thread():
        # Wait for password prompt, then send password
        password_sent.wait(timeout=15)
        try:
            proc.stdin.write(PASSWORD + '\n')
            proc.stdin.flush()
        except:
            pass

    t1 = threading.Thread(target=read_thread, args=(proc.stdout, stdout_lines), daemon=True)
    t2 = threading.Thread(target=read_thread, args=(proc.stderr, stderr_lines), daemon=True)
    t3 = threading.Thread(target=write_thread, daemon=True)
    t1.start()
    t2.start()
    t3.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()

    t1.join(timeout=2)
    t2.join(timeout=2)

    return ''.join(stdout_lines), ''.join(stderr_lines)


# Commands to run on VPS
commands = {
    "Blockchain listener check": r"""journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i "listener\|started\|blockchain" || echo "NOT_FOUND" """,

    "Recent logs (last 30 lines)": r"""journalctl -u agent-api --no-pager -n 30 2>/dev/null || echo "NO_JOURNAL" """,

    "Error check": r"""journalctl -u agent-api --no-pager -n 50 2>/dev/null | grep -i "error\|critical\|exception\|traceback\|failed" | head -10 || echo "NO_ERRORS_FOUND" """,

    "Service status": r"""systemctl status agent-api 2>/dev/null | head -15 || echo "NO_SYSTEMCTL" """,

    "Process check": r"""ps aux | grep -E "agent-api|python|node" | grep -v grep | head -10 || echo "NO_PROCESS" """,

    "Disk usage": r"""df -h / 2>/dev/null || echo "NO_DF" """,

    "Memory usage": r"""free -h 2>/dev/null || echo "NO_FREE" """,

    "Uptime": r"""uptime && echo "---" && uname -a"""
}

print("=" * 70)
print("VPS SYSTEM CHECKS")
print("=" * 70)

for label, cmd in commands.items():
    print(f"\n{'=' * 70}")
    print(f"CHECK: {label}")
    print(f"{'=' * 70}")
    stdout, stderr = run_ssh_command(cmd, timeout=30)
    output = stdout + stderr
    if output.strip():
        print(output.strip())
    else:
        print("(no output)")

print(f"\n{'=' * 70}")
print("ALL CHECKS COMPLETE")
print(f"{'=' * 70}")