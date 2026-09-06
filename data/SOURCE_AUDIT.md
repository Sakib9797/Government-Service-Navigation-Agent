# Step 0 — Source Audit Findings

Audited 2026-09-04 by `tools/audit_sources.py`. Raw data: `data/source_audit.json`.
One polite GET per source (3s/host, descriptive UA). This is an audit, not a scrape.

## Verdict per source

| id | host | status | ingest tier | note |
|---|---|---|---|---|
| national_portal | bangladesh.gov.bd | 200 | **T1 HTML** | 5.6k visible chars, mostly Bengali. Service directory — good for taxonomy seeding. |
| mygov | www.mygov.bd | 200 | **T1 HTML** | 6.3k chars. robots advertises sitemaps but they 500 (point at `beta.stage.` host). |
| epassport_home | www.epassport.gov.bd | 200 | **T3 JS** | 37 visible chars — pure SPA shell. No robots.txt. |
| epassport_fees | (guessed URL) | 200 | **invalid** | Returns the same SPA shell; the guessed path does not exist as a page. |
| dip_home | www.dip.gov.bd | 200 | **T1 HTML** | 9.4k chars. Self-signed cert. Real passport source, not epassport. |
| nidw_home | services.nidw.gov.bd | 200 | **T4 login** | Password field present; redirects to `/nid-pub/`. Do not scrape. |
| ecs_home | www.ecs.gov.bd | 403 | **T3 JS** | Cloudflare challenge ("Just a moment..."). Needs a real browser. |
| land_ministry | minland.gov.bd | 200 | **T1 HTML** | 13k chars — richest land source. Cert chain incomplete. |
| land_portal | land.gov.bd | 200 | T1 thin | 1k chars, mostly a launcher page. |
| eporcha | eporcha.gov.bd | — | **DEAD** | **No DNS at all**, incl. `www.`. The explain.md reference is stale. `dlrms.land.gov.bd` resolves — likely successor. |
| emutation | mutation.land.gov.bd | 200 | **T3 JS** | 33 chars. Has real robots.txt with specific Disallows (respect them). |
| ldtax | ldtax.gov.bd | 200 | T1 thin | 2.1k chars. |
| nbr_home | nbr.gov.bd | 200 | **T1 + T2 PDF** | 30k chars and **66 PDF links** — by far the best-documented source. |
| etaxnbr | etaxnbr.gov.bd | 200 | **T3 JS** | 8 visible chars ("e-Return" SPA). |
| brta_home | brta.gov.bd | 200 | **T1 HTML** | 9k chars. Cert chain incomplete. |
| brta_bsp | bsp.brta.gov.bd | 200 | **T3 JS** | 222 chars, notification shell only. |
| bdris | bdris.gov.bd | 200 | T1 thin | 1.3k chars. robots.txt 403s. |
| dncc / dscc | dncc.gov.bd, dscc.gov.bd | 200 | **T1 HTML** | 9.6k / 7.6k chars. Both certs incomplete. |
| rjsc | www.roc.gov.bd | 200 | **T1 HTML** | 7.3k chars. Self-signed cert. |

## The four findings that change the build plan

**1. Six "separate portals" are one CMS.** `dip`, `minland`, `brta`, `dncc`, `dscc`, `roc` all serve
their PDFs from the same Oracle object-storage bucket pattern:
`.../b/V2Ministry/o/office-<slug>/<yyyy>/<mm>/<hash>`. This is the national ministry CMS.
=> **Phase 1 needs ONE parameterised CMS scraper + a per-office slug config, not six bespoke
scrapers.** Only NBR, the SPAs, and BDRIS need their own handling. Large scope reduction.

**2. Every transactional portal is a JS SPA; every informational site is plain HTML.**
epassport, etaxnbr, bsp.brta, mutation all render ~0 text without JS. But those are the *apply*
portals — the *procedure and fee* content lives on the plain-HTML ministry sites (dip.gov.bd,
brta.gov.bd, nbr.gov.bd). => **Playwright is not needed for the MVP.** Point scrapers at the
ministry sites and skip the SPAs entirely. This removes a whole dependency from Phase 1.

**3. `eporcha.gov.bd` does not exist.** No DNS record. explain.md §3 lists it as a primary source.
At least one other listed URL (the guessed passport-fee path) is also not real. => Treat every
URL in explain.md as unverified until it appears in `source_audit.json` as reachable.

**4. TLS is broken across gov.bd.** 6 of 20 hosts fail certificate verification (self-signed, or
incomplete chain). => Scrapers need an explicit per-host `verify=False` allowlist with the reason
recorded, never a blanket `verify=False`. Log every unverified fetch.

## Crawl permissions

- `ldtax.gov.bd`, `www.ecs.gov.bd`: `User-agent: * / Allow: /` — general crawling permitted.
  They also declare `Content-Signal: search=yes, ai-train=no, use=reference` and block named AI
  crawlers (CCBot, ClaudeBot, Bytespider, Amazonbot, …).
  - `ai-train=no` => **do not fine-tune on this content.** This rules out the Unsloth
    fine-tuning option floated in explain.md §6 if trained on scraped gov text.
  - `ai-input` (RAG/grounding) is **not declared** — neither granted nor restricted.
  - `use=reference` aligns with what this project already does: cite `source_url` + show the date.
- `mutation.land.gov.bd`: specific Disallows (`/QrScanner/`, `/qr-print/`, `/support-request`, …) —
  all transactional endpoints we have no reason to touch. Honour them.
- `bangladesh.gov.bd`, `land.gov.bd`: content-signal boilerplate only, no rules, no signals declared.
- `nbr.gov.bd`, `bsp.brta.gov.bd`, `www.epassport.gov.bd`: no robots.txt (404).
- `bdris.gov.bd`: robots.txt returns 403.

## Open questions for Step 1

- Confirm `dlrms.land.gov.bd` is the eporcha successor before putting it in the taxonomy.
- Find the real passport fee document on `dip.gov.bd` (expect a PDF circular, not an HTML table).
- `www.ecs.gov.bd` needs a browser to get past Cloudflare — decide whether NID procedure content
  is reachable from `dip`-style plain pages instead.
