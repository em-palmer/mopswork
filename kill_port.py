"""Kill any process on port 8003."""
import subprocess, os, signal, time

try:
    out = subprocess.check_output('netstat -ano | findstr ":8003"', shell=True, text=True)
    for line in out.strip().splitlines():
        if "LISTEN" in line:
            parts = [p for p in line.split() if p]
            pid = parts[-1]
            print(f"Killing PID {pid} on port 8003")
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            time.sleep(2)
except Exception as e:
    print(f"No process found or error: {e}")