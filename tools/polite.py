"""
Rate-limiting and back-off policy for every fetch in this project.

Goal: never get this project's IP blocked by a government service portal.
These are public-service sites with modest infrastructure; a blocked IP also
means a citizen-facing tool that silently stops updating.

Policy:
  * >=6s between requests to the SAME host, plus random jitter, so the request
    pattern is not a metronome.
  * Per-host request budget per run. When it is spent, the host is done.
  * Honour Retry-After. On 429/503, exponential back-off, then park the host.
  * Two hard blocks (403/429) parks the host for the rest of the session -
    retrying into a block is exactly how a temporary throttle becomes a ban.
  * A parked host raises HostParked; callers report it rather than retry.

Nothing here tries to look like a browser or evade bot management. If a site
challenges automated access, the answer is to stop, not to disguise.
"""
import random
import time
import urllib.parse

MIN_DELAY = 6.0            # seconds between hits on one host
JITTER = 3.0               # + up to this, so timing is not perfectly regular
MAX_PER_HOST = 25          # request budget per host per run
BACKOFF_BASE = 20.0        # first back-off after a throttle response
MAX_BACKOFF = 180.0
BLOCK_LIMIT = 2            # consecutive blocks before parking a host

_last_hit = {}
_count = {}
_blocks = {}
_parked = {}


class HostParked(Exception):
    """Raised instead of sending a request that policy says must not be sent."""


def host_of(url):
    return urllib.parse.urlparse(url).netloc.lower()


def before(url):
    """Block until it is polite to hit this host. Raises HostParked if it is not."""
    h = host_of(url)
    if h in _parked:
        raise HostParked(f"{h} parked this session: {_parked[h]}")
    if _count.get(h, 0) >= MAX_PER_HOST:
        park(h, f"per-host budget of {MAX_PER_HOST} requests reached")
        raise HostParked(f"{h} parked: request budget reached")

    prev = _last_hit.get(h)
    wait = MIN_DELAY + random.uniform(0, JITTER)
    if prev is not None:
        gap = wait - (time.time() - prev)
        if gap > 0:
            time.sleep(gap)
    _last_hit[h] = time.time()
    _count[h] = _count.get(h, 0) + 1


def after(url, status, headers=None):
    """Record the outcome. Returns seconds to sleep before any retry, or None."""
    h = host_of(url)
    headers = headers or {}

    if status in (429, 503):
        n = _blocks.get(h, 0) + 1
        _blocks[h] = n
        ra = headers.get("Retry-After")
        delay = None
        if ra:
            try:
                delay = float(ra)
            except (TypeError, ValueError):
                delay = None
        if delay is None:
            delay = min(BACKOFF_BASE * (2 ** (n - 1)), MAX_BACKOFF)
        if n >= BLOCK_LIMIT:
            park(h, f"{n} throttle responses (HTTP {status})")
            return None
        return delay

    if status == 403:
        n = _blocks.get(h, 0) + 1
        _blocks[h] = n
        if n >= BLOCK_LIMIT:
            park(h, "repeated HTTP 403 - access is being refused, not throttled")
        return None

    if 200 <= status < 400:
        _blocks[h] = 0
    return None


def park(host, why):
    if host not in _parked:
        _parked[host] = why
        print(f"    [polite] PARKED {host}: {why}", flush=True)


def is_parked(url):
    return host_of(url) in _parked


def report():
    lines = [f"  {h:<26} {_count.get(h,0):>3} requests" + (f"  PARKED: {_parked[h]}" if h in _parked else "")
             for h in sorted(set(_count) | set(_parked))]
    return "\n".join(lines) if lines else "  (no requests)"
