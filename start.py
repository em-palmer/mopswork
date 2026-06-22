"""Start both the backend (port 8003) and frontend (port 8000)."""
import subprocess
import sys
import os
import time
import signal

BASE = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE, ".venv", "Scripts", "python.exe")

# ── Kill stale processes on both ports ──
def kill_processes_on_port(port):
    if sys.platform == "win32":
        result = subprocess.run(
            f"for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{port}') do @echo %a",
            capture_output=True, text=True, shell=True
        )
        for pid in result.stdout.strip().splitlines():
            pid = pid.strip()
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except:
                    pass
    else:
        subprocess.run(["pkill", "-f", f"uvicorn.*:{port}"], capture_output=True)
        subprocess.run(["pkill", "-f", f"http.server.*{port}"], capture_output=True)

for p in [8000, 8003]:
    kill_processes_on_port(p)
time.sleep(1)

# ── Start backend (FastAPI on 8003) ──
backend = subprocess.Popen(
    [VENV_PYTHON, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8003"],
    cwd=BASE,
)

# ── Start frontend (static server on 8000) ──
frontend = subprocess.Popen(
    [VENV_PYTHON, "-m", "http.server", "8000", "--directory", BASE],
    cwd=BASE,
)

print("")
print("  MOpsWork — running at:")
print("  ────────────────────────")
print("  Frontend  →  http://localhost:8000/jobs.html")
print("  Backend   →  http://localhost:8003/health")
print("")
print("  Press Ctrl+C to stop both servers.")
print("")

try:
    backend.wait()
except KeyboardInterrupt:
    print("\nShutting down...")
    backend.terminate()
    frontend.terminate()