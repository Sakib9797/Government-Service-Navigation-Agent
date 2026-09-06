"""
Step 0 of the GSNA build: audit candidate government sources.

For each candidate URL this records the facts that decide how (and whether)
we can ingest it: reachability, TLS health, whether the page renders without
JavaScript, whether it is behind a login, and how much of the real content
sits in linked PDFs rather than HTML.

Nothing here is a scraper. It fetches one page per source, politely, and
writes findings to data/source_audit.json. stdlib only, no install step.
"""
import json, re, ssl, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date

UA = "GSNA-research/0.1 (Bangladesh gov service navigator; contact: tajwarrahmanmahir@gmail.com)"
TIMEOUT = 25
DELAY_PER_HOST = 3.0          # be gentle with public-service infrastructure
JS_TEXT_THRESHOLD = 400       # visible chars below this => probably JS-rendered

_last_hit = {}


def _wait(host):
    prev = _last_hit.get(host)
    if prev is not None:
        gap = DELAY_PER_HOST - (time.time() - prev)
        if gap > 0:
            time.sleep(gap)
    _last_hit[host] = time.time()


def fetch(url, verify=True):
    """Return (status, final_url, headers, body_bytes). Raises on transport error."""
    _wait(urllib.parse.urlparse(url).netloc)
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "bn,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return r.getcode(), r.geturl(), dict(r.headers), r.read(600_000)


def visible_text(html):
    """Strip script/style/markup so we can tell a real page from an empty JS shell."""
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = urllib.parse.unquote(t)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&quot;", '"')):
        t = t.replace(ent, ch)
    return re.sub(r"\s+", " ", t).strip()


def audit(src):
    url = src["url"]
    out = {**src, "checked_on": date.today().isoformat()}
    tls_note = None

    try:
        status, final, headers, body = fetch(url)
    except urllib.error.HTTPError as e:
        status, final, headers, body = e.code, url, dict(e.headers or {}), (e.read(200_000) or b"")
    except urllib.error.URLError as e:
        # urllib wraps SSLError inside URLError, so unwrap before deciding.
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            return {**out, "reachable": False, "error": f"URLError: {e.reason}"}
        tls_note = f"TLS verification FAILED ({e.reason.reason if hasattr(e.reason,'reason') else e.reason}); refetched unverified"
        try:
            status, final, headers, body = fetch(url, verify=False)
        except Exception as e2:
            return {**out, "reachable": False, "error": f"{e2.__class__.__name__}: {e2}", "tls_note": tls_note}
    except Exception as e:
        return {**out, "reachable": False, "error": f"{e.__class__.__name__}: {e}"}

    ctype = headers.get("Content-Type", "").split(";")[0].strip().lower()
    html = body.decode("utf-8", errors="replace")
    text = visible_text(html) if ctype.startswith("text/") else ""

    pdf_links = sorted(set(
        urllib.parse.urljoin(final, m)
        for m in re.findall(r'(?i)href=["\']([^"\']+?\.pdf[^"\']*)["\']', html)
    ))
    has_password_field = bool(re.search(r'(?i)<input[^>]+type=["\']?password', html))
    bengali_chars = len(re.findall(r"[ঀ-৿]", text))

    out.update({
        "reachable": True,
        "status": status,
        "final_url": final,
        "redirected": final.rstrip("/") != url.rstrip("/"),
        "content_type": ctype,
        "bytes": len(body),
        "visible_text_chars": len(text),
        "likely_js_rendered": ctype.startswith("text/html") and len(text) < JS_TEXT_THRESHOLD,
        "login_wall_signal": has_password_field,
        "bengali_chars": bengali_chars,
        "pdf_link_count": len(pdf_links),
        "pdf_links_sample": pdf_links[:5],
        "title": (re.search(r"(?is)<title[^>]*>(.*?)</title>", html) or [None, ""])[1].strip()[:160],
        "text_head": text[:280],
    })
    if tls_note:
        out["tls_note"] = tls_note
    return out


def robots(host_url):
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(host_url))
    try:
        status, _, _, body = fetch(base + "/robots.txt")
        txt = body.decode("utf-8", errors="replace")
        if status != 200 or "<html" in txt[:400].lower():
            return {"present": False, "note": f"no robots.txt (status {status})"}
        return {
            "present": True,
            "disallow_all": bool(re.search(r"(?im)^\s*user-agent:\s*\*\s*$(?:\s*\n(?!user-agent).*)*?^\s*disallow:\s*/\s*$", txt)),
            "rules": [l.strip() for l in txt.splitlines() if re.match(r"(?i)\s*(user-agent|disallow|allow|crawl-delay)", l)][:25],
        }
    except Exception as e:
        return {"present": False, "note": f"{e.__class__.__name__}: {e}"}


def main():
    cands = json.load(open("data/source_candidates.json", encoding="utf-8"))["sources"]
    results, seen_hosts = [], {}
    for i, s in enumerate(cands, 1):
        print(f"[{i}/{len(cands)}] {s['id']:<16} {s['url']}", file=sys.stderr, flush=True)
        r = audit(s)
        host = urllib.parse.urlparse(s["url"]).netloc
        if host not in seen_hosts:
            seen_hosts[host] = robots(s["url"])
        r["robots"] = seen_hosts[host]
        results.append(r)
    json.dump({"audited_on": date.today().isoformat(), "user_agent": UA, "results": results},
              open("data/source_audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nWrote data/source_audit.json ({len(results)} sources)", file=sys.stderr)


if __name__ == "__main__":
    main()
