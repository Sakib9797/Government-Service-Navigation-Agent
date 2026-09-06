"""
Polite, caching fetcher shared by the audit tools and (later) the scrapers.

Every response body is written to data/raw/<host>/<slug> so that re-parsing
never costs another request. Fixes the Step 0 mistake where 20 pages were
fetched and their bodies discarded.

TLS: several gov.bd hosts have self-signed or incomplete chains (see
data/SOURCE_AUDIT.md). Verification is skipped ONLY for hosts in
NO_VERIFY_HOSTS, and every such fetch is recorded in the sidecar meta.
"""
import hashlib, json, os, re, ssl, time, urllib.error, urllib.parse, urllib.request

import polite
from textnorm import nfc
from polite import HostParked  # noqa: F401  (re-exported for callers)
from datetime import date, datetime, timezone

UA = "GSNA-research/0.1 (Bangladesh gov service navigator; contact: tajwarrahmanmahir@gmail.com)"
RAW = os.path.join("data", "raw")
DELAY_PER_HOST = 3.0

# Audited 2026-09-04: these hosts fail cert verification. Reason recorded per host.
NO_VERIFY_HOSTS = {
    "www.dip.gov.bd":  "self-signed certificate",
    "minland.gov.bd":  "incomplete chain (no local issuer)",
    "brta.gov.bd":     "incomplete chain (no local issuer)",
    "dncc.gov.bd":     "incomplete chain (no local issuer)",
    "dscc.gov.bd":     "incomplete chain (no local issuer)",
    "www.roc.gov.bd":  "self-signed certificate",
    "dlrms.land.gov.bd": "certificate EXPIRED (found 2026-09-04)",
    "orgbdr.gov.bd":   "incomplete chain (no local issuer)",
}

_last_hit = {}
_PROBED = {}


def _probe_tls(host):
    """Try a real TLS handshake once per host and cache the verdict.

    9 of 20 audited gov.bd hosts fail verification (self-signed, incomplete
    chain, expired). Maintaining that list by hand was breaking every time a
    scraper reached a new office site. This probes per host, records the exact
    reason in the fetch metadata, and never disables verification for a host
    whose certificate actually validates - so it stays an audit trail, not a
    blanket --insecure.
    """
    import socket
    if host in _PROBED:
        return _PROBED[host]
    reason = None
    try:
        with socket.create_connection((host, 443), timeout=15) as sock:
            ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except ssl.SSLError as e:
        reason = f"probed {date.today().isoformat()}: {getattr(e, 'reason', e)}"
    except Exception:
        reason = None      # not a TLS problem; let the real request surface it
    _PROBED[host] = reason
    if reason:
        print(f"    [tls] {host}: verification disabled - {reason}", flush=True)
    return reason


def _tls_exception(host):
    """Match the allowlist on the host and its www/non-www twin.

    Keyed deliberately per host, never by a blanket .gov.bd suffix: a broken
    cert on one office site is not a reason to stop verifying the rest.
    """
    h = host.lower()
    for cand in (h, h[4:] if h.startswith("www.") else "www." + h):
        if cand in NO_VERIFY_HOSTS:
            return NO_VERIFY_HOSTS[cand]
    return _probe_tls(h)


def to_uri(url):
    """Percent-encode non-ASCII path/query so Bengali CMS slugs are fetchable.

    The V2Ministry CMS builds URLs like
    /pages/office-citizen-charters/সিটিজেন-চার্টার-6d0265-...
    which urllib cannot send as-is (it ASCII-encodes headers).
    """
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((
        p.scheme, p.netloc.encode("idna").decode("ascii") if any(ord(c) > 127 for c in p.netloc) else p.netloc,
        urllib.parse.quote(p.path, safe="/%:@!$&'()*+,;=~-._"),
        urllib.parse.quote(p.query, safe="=&%:/?@!$'()*+,;~-._"),
        p.fragment))


def _slug(url):
    p = urllib.parse.urlparse(url)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (p.path + ("?" + p.query if p.query else "")).strip("/")) or "index"
    return f"{base[:80]}.{hashlib.sha1(url.encode()).hexdigest()[:8]}"


def fetch(url, force=False):
    """Return dict(url, final_url, status, body: bytes, from_cache, tls_verified)."""
    url = to_uri(url)
    host = urllib.parse.urlparse(url).netloc
    d = os.path.join(RAW, host)
    body_path, meta_path = os.path.join(d, _slug(url)), os.path.join(d, _slug(url) + ".meta.json")

    if not force and os.path.exists(body_path) and os.path.exists(meta_path):
        meta = json.load(open(meta_path, encoding="utf-8"))
        return {**meta, "body": open(body_path, "rb").read(), "from_cache": True}

    polite.before(url)          # rate limit, jitter, budget; raises HostParked

    skip_reason = _tls_exception(host)
    verify = skip_reason is None
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "bn,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            status, final, body = r.getcode(), r.geturl(), r.read()
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status, final, body, ctype = e.code, url, (e.read() or b""), (e.headers or {}).get("Content-Type", "")
        retry_in = polite.after(url, status, dict(e.headers or {}))
        if retry_in:
            print(f"    [polite] HTTP {status} from {host}; backing off {retry_in:.0f}s", flush=True)
            time.sleep(retry_in)
            polite.before(url)
            try:
                with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                    status, final, body = r.getcode(), r.geturl(), r.read()
                    ctype = r.headers.get("Content-Type", "")
                    polite.after(url, status)
            except urllib.error.HTTPError as e2:
                status, body = e2.code, (e2.read() or b"")
                polite.after(url, status, dict(e2.headers or {}))
    else:
        polite.after(url, status)

    meta = {
        "url": url, "final_url": final, "status": status, "content_type": ctype,
        "bytes": len(body), "fetched_at": datetime.now(timezone.utc).isoformat(),
        "tls_verified": verify,
        "tls_skip_reason": skip_reason,
    }
    os.makedirs(d, exist_ok=True)
    open(body_path, "wb").write(body)
    json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return {**meta, "body": body, "from_cache": False}


def visible_text(html):
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"')):
        t = t.replace(ent, ch)
    return nfc(re.sub(r"\s+", " ", t).strip())
