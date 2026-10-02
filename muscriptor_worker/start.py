import os
import subprocess
import sys

port = os.getenv("PORT", "8222")
if not port.isdigit():
    print(f"Invalid PORT value: {port!r}", file=sys.stderr)
    sys.exit(2)

cmd = [
    "muscriptor",
    "serve",
    "--host",
    "0.0.0.0",
    "--port",
    port,
    "--model",
    "small",
    "--device",
    "cpu",
]

print(f"Starting MuScriptor small on CPU, port {port}", flush=True)
os.execvp(cmd[0], cmd)
