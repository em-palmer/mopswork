"""Kill any process on port 8003 and restart the backend."""
import subprocess, sys, os, time, signal

BASE = os.path.dirname(os.path.abspath(__file__))

# Find and kill process on port 8003
try:
    out = subprocess.check_output(
        'netstat -ano | findstr ":8003"',
        shell=True, text=True
    )
    for line in out.strip().splitlines():
        if "LISTEN" in line:
            parts = line.split()
            pid = parts[-1]
            try:
                os.kill(int(pid), signal.SIGTERM)
                print(f"Killed PID {pid}")
            except: pass
            time.sleep(1)
except: pass

venv_python = os.path.join(BASE, ".venv", "Scripts", "python.exe")
p = subprocess.Popen(
    [venv_python, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8003"],
    cwd=BASE,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
)

# Wait for startup
import urllib.request
for _ in range(30):
    time.sleep(2)
    try:
        r = urllib.request.urlopen("http://localhost:8003/health", timeout=2)
        data = r.read()
        print(f"Backend is live: {data.decode()}")
        sys.exit(0)
    except: pass

print("Backend failed to start")
sys.exit(1)