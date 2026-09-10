from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
import time

WINDOW_SECONDS = 15 * 60
MAX_ANALYSES_PER_WINDOW = 6
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TEMP_MAX_AGE_SECONDS = 45 * 60

_requests = defaultdict(deque)
_lock = Lock()


def client_ip(request):
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def check_analysis_rate_limit(ip):
    now = time.time()
    with _lock:
        q = _requests[ip]
        while q and now - q[0] > WINDOW_SECONDS:
            q.popleft()
        if len(q) >= MAX_ANALYSES_PER_WINDOW:
            retry = max(1, int(WINDOW_SECONDS - (now - q[0])))
            return False, retry
        q.append(now)
    return True, 0


def cleanup_old_files(*directories):
    cutoff = time.time() - TEMP_MAX_AGE_SECONDS
    for directory in directories:
        path = Path(directory)
        if not path.exists():
            continue
        for item in path.iterdir():
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink(missing_ok=True)
            except Exception:
                pass
