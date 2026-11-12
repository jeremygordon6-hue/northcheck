#!/usr/bin/env python3
"""
NorthCheck — production web app (free-tools build).

Canadian SMB compliance platform, Phase 1 modules:

  * AODA FileReady — scan a small business website for WCAG 2.0 issues
    Ontario's AODA asks about, and produce a dated evidence pack ahead
    of the December 31, 2026 accessibility compliance report deadline.
  * PostCheck ON — check a job posting against Ontario's Jan 1, 2026
    posting rules (O. Reg. 476/24) and keep its 45-day / 3-year clocks
    in a vault.
  * Loi25 Kit — Quebec Law 25 evidence from the public website:
    privacy policy linked from the homepage, a named privacy officer,
    a cookie consent mechanism, and a French privacy policy.
  * Français Check — whether a real French version of the site exists
    and its key pages (home, contact, privacy) resolve in French.
  * AODA Complete the Filing — on top of the AODA scan: a remediation
    tracker whose "resolved" status comes only from re-scan
    verification, an owner-answered checklist for the non-website
    IASR standards, a combined Filing Pack, and a publish-ready
    accessibility statement generator. Checklist answers are the
    organization's own statements and are labelled as such everywhere;
    the compliance report itself is filed by the organization on the
    Ontario portal and certified by a senior officer.

Stack: Python standard library only — http.server, server-rendered
HTML with inline CSS, no JavaScript frameworks, no external requests.
All checking logic is the verified Phase 1 engine in northcheck.py,
imported and reused, not rewritten.

Honesty rule (product requirement): NorthCheck prepares evidence. It
does not certify compliance and is not legal advice. Findings are
issues to review; the signing officer / owner makes the call.
"""

import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html import escape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import northcheck as nc  # the verified Phase 1 engine (copied in)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
FOUNDING_PATH = os.path.join(DATA_DIR, "founding.json")
SCANS_PATH = os.path.join(DATA_DIR, "scans.json")
VAULT_PATH = os.path.join(DATA_DIR, "vault.json")
CHECKLISTS_PATH = os.path.join(DATA_DIR, "checklists.json")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8790"))

MAX_PAGES = 10            # same-domain crawl cap per scan
PAGE_TIMEOUT = 8          # seconds per fetched page
MAX_BODY = 2_000_000      # bytes per fetched page

HONESTY_LINE = ("NorthCheck prepares evidence. It does not certify "
                "compliance and is not legal advice.")

# ---------------------------------------------------------------------------
# JSON stores (created at runtime)
# ---------------------------------------------------------------------------

def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return default
    return default


def _save(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def load_list(path):
    data = _load(path, [])
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Styling — inline CSS only, no external resources
# ---------------------------------------------------------------------------

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial,
       sans-serif; margin: 0; color: #1c2430; background: #f6f7f9;
       line-height: 1.55; }
header.site { background: #123524; color: #fff; padding: 14px 20px; }
header.site a { color: #fff; text-decoration: none; font-weight: 700;
                font-size: 1.25rem; }
header.site nav { float: right; }
header.site nav a { font-size: .95rem; font-weight: 400; margin-left: 16px; }
main { max-width: 880px; margin: 0 auto; padding: 24px 20px 60px; }
h1 { font-size: 1.9rem; line-height: 1.25; margin: .4em 0 .3em; }
h2 { margin-top: 1.6em; }
.deadline { background: #fff3cd; border: 1px solid #e0c25e;
            border-radius: 8px; padding: 14px 18px; margin: 18px 0; }
.card { background: #fff; border: 1px solid #dde1e6; border-radius: 8px;
        padding: 18px 20px; margin: 16px 0; }
.badge { display: inline-block; background: #e8eef7; color: #274b73;
         border-radius: 999px; padding: 1px 10px; font-size: .8rem;
         margin-left: 8px; vertical-align: middle; }
.soon { background: #f0e6f6; color: #5b3a75; }
form label { display: block; font-weight: 600; margin: 14px 0 4px; }
input[type=text], input[type=url], input[type=email], input[type=date],
textarea { width: 100%; padding: 9px 10px; border: 1px solid #b9c0c9;
           border-radius: 6px; font: inherit; background: #fff; }
textarea { min-height: 220px; }
button, .btn { background: #123524; color: #fff; border: 0;
               border-radius: 6px; padding: 10px 18px; font: inherit;
               cursor: pointer; text-decoration: none; display: inline-block;
               margin-top: 16px; }
button:hover, .btn:hover { background: #1b4d33; }
.sev { display: inline-block; border-radius: 4px; padding: 0 8px;
       font-size: .8rem; font-weight: 700; text-transform: uppercase; }
.sev-high { background: #f8d7da; color: #7a1f28; }
.sev-medium { background: #fff3cd; color: #7a5b00; }
.sev-low { background: #d1ecf1; color: #0c5460; }
.sev-info { background: #e2e3e5; color: #383d41; }
.finding { border-left: 4px solid #b9c0c9; padding: 6px 0 6px 14px;
           margin: 14px 0; }
.finding p { margin: 4px 0; }
code, .evidence { font-family: ui-monospace, Menlo, Consolas, monospace;
                  font-size: .88rem; background: #f1f3f5; padding: 1px 5px;
                  border-radius: 4px; word-break: break-all; }
table { border-collapse: collapse; width: 100%; background: #fff; }
th, td { border: 1px solid #dde1e6; padding: 8px 10px; text-align: left;
         vertical-align: top; }
th { background: #f1f3f5; }
.notice { background: #eef6ee; border: 1px solid #bcd8bc; border-radius: 8px;
          padding: 12px 16px; margin: 16px 0; }
footer.site { max-width: 880px; margin: 0 auto; padding: 0 20px 40px;
              color: #5a6572; font-size: .9rem; }
.small { color: #5a6572; font-size: .9rem; }
.overdue { color: #7a1f28; font-weight: 700; }
"""


def page(title, body):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — NorthCheck</title>
<style>{CSS}</style>
</head>
<body>
<header class="site">
  <a href="/">NorthCheck</a>
  <nav>
    <a href="/scan">AODA scan</a>
    <a href="/filing">Complete the Filing</a>
    <a href="/postcheck">PostCheck</a>
    <a href="/loi25">Loi25 Kit</a>
    <a href="/francais">Français Check</a>
    <a href="/vault">Vault</a>
  </nav>
</header>
<main>
{body}
</main>
<footer class="site">
  <p>{HONESTY_LINE}</p>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------

def landing_page(joined=False):
    thanks = ('<div class="notice">Thanks — you are on the founding list. '
              'We will write when your module opens.</div>') if joined else ""
    body = f"""
<h1>Canadian compliance paperwork, checked before the deadline checks you.</h1>
<p>NorthCheck is one platform for the Canadian rules small businesses
actually get fined over: deterministic rule checks, plain-English
findings, and a dated evidence pack a signing officer can rely on.</p>

<div class="deadline">
  <strong>Ontario AODA filing deadline: December 31, 2026.</strong><br>
  Ontario businesses and non-profits with 20 or more employees must file
  an accessibility compliance report by December 31, 2026 — and those
  with 50 or more must also certify that their websites meet WCAG 2.0
  Level AA. Giving false or misleading information in the report is an
  offence, and a senior officer signs it. An overlay widget does not
  produce filing evidence. A scan with a dated evidence pack does.
</div>

<div class="card">
  <h2>AODA FileReady <span class="badge">Module 1 — live</span></h2>
  <p>Point the scanner at your website. It crawls up to 10 pages, runs
  deterministic WCAG 2.0 checks (missing language declaration, empty
  page titles, images without alt text, unlabelled form fields, skipped
  heading levels, nameless links and buttons, duplicate ids), and builds
  a dated evidence pack for the December 31, 2026 filing.</p>
  <p><strong>Founding price: $149</strong> per evidence pack ·
  <strong>$39/month</strong> monitoring with re-scan alerts.</p>
  <p><strong>Complete the Filing Pack</strong> — the report covers
  every part of the Integrated Accessibility Standards Regulation,
  not just the website, and a senior officer has to certify it. This
  fuller offer adds a remediation tracker (a finding counts as fixed
  only when a re-scan verifies it is gone — never on a say-so), an
  owner-answered checklist for the non-website standards, one Filing
  Pack that combines the website evidence with those answers and the
  remaining gaps, and a publish-ready accessibility statement for
  your site. <strong>Founding price: $249</strong> for the Complete
  Filing Pack.</p>
  <a class="btn" href="/filing">Complete the Filing checklist</a>
  <a class="btn" href="https://buy.stripe.com/cNi00c4kVgGP9um5wM5Rm06">Buy the Complete Filing Pack — $249</a><br>
  <a class="btn" href="/scan">Scan my website</a>
  <a class="btn" href="https://buy.stripe.com/eVqaEQ6t32PZ6iaaR65Rm00">Buy the evidence pack — $149</a>
  <a class="btn" href="https://buy.stripe.com/cNi3co4kV4Y77meaR65Rm01">Add monitoring — $39/month</a>
</div>

<div class="card">
  <h2>PostCheck ON <span class="badge">Module 2 — live</span></h2>
  <p>Since January 1, 2026, Ontario employers with 25 or more employees
  must state compensation in every public posting (range no wider than
  $50,000 unless the top exceeds $200,000), disclose AI screening, state
  whether a vacancy exists, include no Canadian-experience requirement,
  notify interviewed applicants within 45 days, and keep records for
  3 years. PostCheck reads the posting the way the rule does, suggests
  the corrected draft, and keeps the clocks in a vault.</p>
  <p><strong>Founding price: $49/month</strong> flat per company.</p>
  <a class="btn" href="/postcheck">Check a job posting</a>
  <a class="btn" href="https://buy.stripe.com/14A8wI5oZairbCugbq5Rm02">Subscribe — $49/month</a>
</div>

<div class="card">
  <h2>Loi25 Kit <span class="badge">Module 3 — live</span></h2>
  <p>Quebec's Law 25 binds any business holding Quebecers' personal
  information — including sellers outside Quebec. Loi25 Kit checks
  what a public website can honestly show: a privacy policy linked
  from the homepage, a named privacy officer or privacy contact, a
  cookie consent mechanism visible in the served HTML, and a French
  version of the privacy policy — then builds the same dated
  evidence pack as AODA FileReady. Law 25 duties that leave no trace
  on a website (an incident register, privacy impact assessments)
  are out of scope and are never implied.</p>
  <p><strong>Founding price: $39/month</strong> per site.</p>
  <a class="btn" href="/loi25">Run the Loi25 check</a>
  <a class="btn" href="/#founding">Join the founding list</a>
</div>

<div class="card">
  <h2>Français Check <span class="badge">Module 4 — live</span></h2>
  <p>Selling into Quebec starts with a French version that actually
  exists. Français Check verifies reachability, not translation
  quality: a French entry point from the homepage, hreflang
  declarations tying the versions together, and the French
  counterparts of your home, contact and privacy pages resolving
  in French.</p>
  <p><strong>Included</strong> with a scan or monitoring plan.</p>
  <a class="btn" href="/francais">Check my French version</a>
</div>

<div class="card" id="founding">
  <h2>Join the founding list</h2>
  <p>Founding pricing is locked for the first cohort. Leave an email and
  we will write when your module opens. No email is sent by this form —
  it only records your address for the launch note.</p>
  {thanks}
  <form method="post" action="/founding">
    <label for="email">Email address</label>
    <input type="email" id="email" name="email" required
           placeholder="you@yourbusiness.ca">
    <button type="submit">Join the founding list</button>
  </form>
</div>

<p class="small">{HONESTY_LINE} Every finding is an issue to review,
found by deterministic checks — never a certification.</p>
"""
    return page("Canadian SMB compliance, checked", body)


# ---------------------------------------------------------------------------
# AODA scan — crawl + engine checks
# ---------------------------------------------------------------------------

class LinkParser(HTMLParser):
    """Collects href values from <a> tags for the crawler."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value)


SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
                   ".ico", ".pdf", ".zip", ".css", ".js", ".xml",
                   ".mp3", ".mp4", ".doc", ".docx", ".xls", ".xlsx")


def _same_host(base, other):
    return urllib.parse.urlparse(base).netloc == \
        urllib.parse.urlparse(other).netloc


def crawl(start_url):
    """Breadth-first crawl, same domain only, up to MAX_PAGES pages.

    Returns a list of {url, html} for pages fetched, plus a list of
    per-URL error strings for pages that could not be read as HTML.
    """
    seen = set()
    queue = [start_url]
    fetched = []
    errors = []
    while queue and len(fetched) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "NorthCheck/1.0"})
            with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as resp:
                ctype = resp.headers.get_content_type()
                if ctype != "text/html":
                    errors.append(f"{url} — skipped (content type "
                                  f"{ctype}, not HTML)")
                    continue
                raw = resp.read(MAX_BODY + 1)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"{url} — could not be fetched ({exc})")
            continue
        html_text = raw.decode("utf-8", errors="replace")
        fetched.append({"url": url, "html": html_text})
        parser = LinkParser()
        try:
            parser.feed(html_text)
        except Exception:
            parser.hrefs = []
        for href in parser.hrefs:
            nxt = urllib.parse.urljoin(url, href)
            nxt = urllib.parse.urldefrag(nxt)[0]
            if not nxt.startswith(("http://", "https://")):
                continue
            if not _same_host(start_url, nxt):
                continue
            if urllib.parse.urlparse(nxt).path.lower().endswith(
                    SKIP_EXTENSIONS):
                continue
            if nxt not in seen and nxt not in queue:
                queue.append(nxt)
    return fetched, errors


def site_key(url):
    """Key tying together every scan / checklist for the same site.

    The normalised start URL as entered — two scans of the same site
    start from the same address, so this is also the re-scan key.
    """
    return nc._norm_page_url(url)


def previous_aoda_scan(key, scans):
    """Most recent stored AODA scan for this site key, else None."""
    for record in reversed(scans):
        if record.get("module") == "aoda" \
                and site_key(record.get("start_url", "")) == key:
            return record
    return None


def run_scan(start_url):
    pages, errors = crawl(start_url)
    page_results = []
    for p in pages:
        findings, stats = nc.run_aoda_checks(p["html"])
        page_results.append({
            "url": p["url"],
            "findings": findings,
            "stats": stats,
        })
    record = {
        "id": uuid.uuid4().hex[:12],
        "module": "aoda",
        "start_url": start_url,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": page_results,
        "errors": errors,
        "total_findings": sum(len(pr["findings"]) for pr in page_results),
    }
    scans = load_list(SCANS_PATH)
    previous = previous_aoda_scan(site_key(start_url), scans)
    if previous is not None:
        # Remediation tracker: "resolved" is earned only here, by the
        # new scan no longer reporting the finding — never by a click.
        record["comparison"] = {
            "previous_scan_id": previous["id"],
            "previous_timestamp": previous["timestamp"],
            **nc.compare_scan_pages(previous["pages"],
                                    page_results),
        }
    scans.append(record)
    _save(SCANS_PATH, scans)
    return record


def findings_html(findings):
    """Render findings grouped by severity (engine's shared ordering)."""
    if not findings:
        return ("<p>No issues matched the checks in this run. See the "
                "honesty note — this is not a certification.</p>")
    out = []
    current = None
    for f in nc.sort_findings(findings):
        if f["severity"] != current:
            current = f["severity"]
            out.append(f"<h3>{escape(current.capitalize())}</h3>")
        out.append(f"""
<div class="finding">
  <p><span class="sev sev-{escape(f['severity'])}">{escape(f['severity'])}</span>
     <strong>{escape(f['rule_id'])}</strong> — {escape(f['category'])}</p>
  <p><strong>What this means:</strong> {escape(f['explanation'])}</p>
  <p><strong>Evidence found:</strong> <span class="evidence">{escape(f['evidence'])}</span></p>
  <p><strong>Suggested fix:</strong> {escape(f['fix'])}</p>
</div>""")
    return "\n".join(out)


def scan_form_page(error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    body = f"""
<h1>AODA FileReady — website scan</h1>
<p>Enter your website address. NorthCheck crawls up to {MAX_PAGES} pages
on the same domain, runs the deterministic WCAG 2.0 checks, and builds a
dated evidence pack for the December 31, 2026 Ontario filing.</p>
{err}
<div class="card">
  <form method="post" action="/scan">
    <label for="url">Website URL (http or https)</label>
    <input type="url" id="url" name="url" required
           placeholder="https://yourbusiness.ca">
    <button type="submit">Run the scan</button>
  </form>
</div>
<p class="small">{HONESTY_LINE}</p>
"""
    return page("AODA website scan", body)


def _comparison_entry_list(entries):
    if not entries:
        return "<p>None.</p>"
    items = "".join(
        f"<li><span class=\"sev sev-{escape(e['finding']['severity'])}\">"
        f"{escape(e['finding']['severity'])}</span> "
        f"<strong>{escape(e['finding']['rule_id'])}</strong> — "
        f"{escape(e['finding']['category'])}<br>"
        f"<span class=\"small\">Page: {escape(e['page_url'])}</span></li>"
        for e in entries)
    return f"<ul>{items}</ul>"


def comparison_html(record):
    """Remediation-tracker card: this scan vs the previous one.

    Status vocabulary is deliberate: "Verified resolved by re-scan"
    (the new scan no longer reports the finding) is the only fixed
    status NorthCheck shows. There is no mark-as-fixed button — an
    owner's say-so is never presented as verification.
    """
    comp = record.get("comparison")
    if not comp:
        return ""
    c = comp["counts"]
    return f"""
<div class="card">
  <h2>Remediation tracker — compared with the previous scan</h2>
  <p>Previous scan: {escape(comp['previous_timestamp'])} ·
  <strong>{c['resolved']} verified resolved by re-scan</strong> ·
  {c['still_open']} still open · {c['new']} new ·
  {c['not_rechecked']} on pages this scan did not crawl</p>
  <p class="small">A finding counts as resolved only when a re-scan
  no longer reports it. NorthCheck does not offer a "mark as fixed"
  button: an owner's say-so is not verification, and only the
  re-scan result above is shown as resolved.</p>
  <h3>Verified resolved by re-scan ({c['resolved']})</h3>
  {_comparison_entry_list(comp['resolved'])}
  <h3>Still open ({c['still_open']})</h3>
  {_comparison_entry_list(comp['still_open'])}
  <h3>New in this scan ({c['new']})</h3>
  {_comparison_entry_list(comp['new'])}
  <h3>Not re-checked — page not crawled this time
      ({c['not_rechecked']})</h3>
  {_comparison_entry_list(comp['not_rechecked'])}
</div>"""


def scan_results_page(record):
    sections = []
    for pr in record["pages"]:
        n = len(pr["findings"])
        counts = nc.count_by_severity(pr["findings"])
        counts_line = " · ".join(
            f"{sev} {counts[sev]}"
            for sev in ("high", "medium", "low", "info"))
        sections.append(f"""
<div class="card">
  <h2>{escape(pr['url'])}</h2>
  <p><strong>{n} issues to review</strong> ({counts_line})</p>
  {findings_html(pr['findings'])}
</div>""")
    errors_html = ""
    if record["errors"]:
        items = "".join(f"<li>{escape(e)}</li>" for e in record["errors"])
        errors_html = f"""
<div class="card">
  <h2>Pages not scanned</h2>
  <ul>{items}</ul>
</div>"""
    body = f"""
<h1>Scan results</h1>
<p>Site: <strong>{escape(record['start_url'])}</strong><br>
Scanned: {escape(record['timestamp'])} · {len(record['pages'])} page(s) ·
<strong>{record['total_findings']} issues to review in total</strong></p>
<p><a class="btn" href="/pack/{record['id']}">Download the evidence pack (HTML)</a></p>
{comparison_html(record)}
{''.join(sections)}
{errors_html}
<div class="card">
  <h2>Honesty note</h2>
  <p>Every item above is an issue to review, found by deterministic
  checks against WCAG 2.0. A finding is not a determination that a page
  is compliant or non-compliant, and an empty findings list would not be
  a guarantee of compliance either. The signing officer reviews the
  evidence and makes the call.</p>
  <p class="small">{nc.DRAFT_STAMP}</p>
</div>
"""
    return page("Scan results", body)


def evidence_pack_html(record):
    """One self-contained HTML evidence pack for a stored scan."""
    date_line = record["timestamp"][:10]
    page_sections = []
    for pr in record["pages"]:
        counts = nc.count_by_severity(pr["findings"])
        counts_line = " · ".join(
            f"{sev} {counts[sev]}"
            for sev in ("high", "medium", "low", "info"))
        page_sections.append(f"""
<h2>Page: {escape(pr['url'])}</h2>
<p>{len(pr['findings'])} issues to review ({counts_line}). Scan stats:
{pr['stats']['images_total']} images ({pr['stats']['images_decorative']}
decorative with empty alt), {pr['stats']['controls_total']} form
controls, {pr['stats']['links_total']} links,
{pr['stats']['headings_total']} headings.</p>
{findings_html(pr['findings'])}""")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NorthCheck Evidence Pack — AODA web accessibility scan</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>NorthCheck Evidence Pack — AODA web accessibility scan</h1>
<p><strong>{escape(nc.DRAFT_STAMP, quote=False)}</strong></p>
<ul>
  <li><strong>Module:</strong> AODA — web accessibility (WCAG 2.0)</li>
  <li><strong>Target:</strong> {escape(record['start_url'])}</li>
  <li><strong>Date scanned:</strong> {escape(date_line)}</li>
  <li><strong>Pages scanned:</strong> {len(record['pages'])}</li>
  <li><strong>Total issues to review:</strong> {record['total_findings']}</li>
</ul>
{''.join(page_sections)}
<h2>Honesty note</h2>
<p>Every item above is an issue to review, found by deterministic checks
against the stated rules. A finding means the check matched something
worth a human look — it is not a determination that the target is
compliant or non-compliant, and an empty findings list would not be a
guarantee of compliance either. The signing officer / owner reviews the
evidence and makes the call.</p>
<hr>
<p class="small">Generated by NorthCheck. {HONESTY_LINE}</p>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Loi25 Kit + Français Check — site-level scans on the shared crawler
# ---------------------------------------------------------------------------

def _fetch_one(url):
    """Fetch one URL as HTML. Returns (ok, html_text, error_string)."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "NorthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as resp:
            ctype = resp.headers.get_content_type()
            if ctype != "text/html":
                return False, None, f"content type {ctype}, not HTML"
            raw = resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        return False, None, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, None, f"could not be fetched ({exc})"
    return True, raw.decode("utf-8", errors="replace"), None


def _key_page_url(pages, marker):
    """First crawled URL whose path contains marker, else None."""
    for p in pages:
        if marker in urllib.parse.urlparse(p["url"]).path.lower():
            return p["url"]
    return None


def _store_site_record(record):
    scans = load_list(SCANS_PATH)
    scans.append(record)
    _save(SCANS_PATH, scans)
    return record


def run_loi25_scan(start_url):
    pages, errors = crawl(start_url)
    findings, stats = (nc.run_loi25_checks(pages) if pages
                       else ([], {}))
    return _store_site_record({
        "id": uuid.uuid4().hex[:12],
        "module": "loi25",
        "start_url": start_url,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": [p["url"] for p in pages],
        "errors": errors,
        "findings": findings,
        "stats": stats,
        "total_findings": len(findings),
    })


def run_francais_scan(start_url):
    pages, errors = crawl(start_url)
    attempts = []
    findings, stats = [], {}
    if pages:
        crawled = {p["url"]: p["html"] for p in pages}
        targets = [("home", start_url)]
        contact = _key_page_url(pages, "contact")
        if contact and contact != start_url:
            targets.append(("contact", contact))
        privacy = (_key_page_url(pages, "privacy")
                   or _key_page_url(pages, "confidential"))
        if privacy and privacy != start_url:
            targets.append(("privacy", privacy))
        for role, url in targets:
            variant = nc.french_variant_url(url)
            if variant in crawled:
                lang = nc.parse_site_page(crawled[variant]).html_lang
                attempts.append({"role": role, "url": variant,
                                 "ok": True, "lang": lang, "error": None})
                continue
            ok, html_text, error = _fetch_one(variant)
            lang = nc.parse_site_page(html_text).html_lang if ok else None
            attempts.append({"role": role, "url": variant, "ok": ok,
                             "lang": lang, "error": error})
        findings, stats = nc.run_francais_checks(pages, attempts)
    return _store_site_record({
        "id": uuid.uuid4().hex[:12],
        "module": "francais",
        "start_url": start_url,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": [p["url"] for p in pages],
        "errors": errors,
        "findings": findings,
        "stats": stats,
        "attempts": attempts,
        "total_findings": len(findings),
    })


def _site_form_page(module, error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    if module == "loi25":
        title = "Loi25 Kit — website check"
        intro = ("Enter your website address. NorthCheck crawls up to "
                 f"{MAX_PAGES} pages on the same domain and checks what "
                 "the public site can honestly show for Quebec's Law 25: "
                 "a privacy policy linked from the homepage, a named "
                 "privacy officer or privacy contact, a cookie consent "
                 "mechanism, and a French version of the privacy policy.")
        action, cta = "/loi25", "Run the Loi25 check"
    else:
        title = "Français Check — French version check"
        intro = ("Enter your website address. NorthCheck crawls up to "
                 f"{MAX_PAGES} pages on the same domain, then tries the "
                 "conventional French addresses (/fr/…) for your home, "
                 "contact and privacy pages and checks that they resolve "
                 "in French.")
        action, cta = "/francais", "Run the Français Check"
    body = f"""
<h1>{title}</h1>
<p>{intro}</p>
{err}
<div class="card">
  <form method="post" action="{action}">
    <label for="url">Website URL (http or https)</label>
    <input type="url" id="url" name="url" required
           placeholder="https://yourbusiness.ca">
    <button type="submit">{cta}</button>
  </form>
</div>
<p class="small">{HONESTY_LINE}</p>
"""
    return page(title, body)


def _site_results_page(record, heading, stats_rows, extra_card=""):
    counts = nc.count_by_severity(record["findings"])
    counts_line = " · ".join(
        f"{sev} {counts[sev]}" for sev in ("high", "medium", "low", "info"))
    stats_html = "".join(
        f"<li><strong>{escape(k)}:</strong> {escape(v)}</li>"
        for k, v in stats_rows)
    errors_html = ""
    if record["errors"]:
        items = "".join(f"<li>{escape(e)}</li>" for e in record["errors"])
        errors_html = f"""
<div class="card">
  <h2>Pages not scanned</h2>
  <ul>{items}</ul>
</div>"""
    body = f"""
<h1>{heading}</h1>
<p>Site: <strong>{escape(record['start_url'])}</strong><br>
Scanned: {escape(record['timestamp'])} · {len(record['pages'])} page(s) ·
<strong>{record['total_findings']} issues to review in total</strong>
({counts_line})</p>
<p><a class="btn" href="/pack/{record['id']}">Download the evidence pack (HTML)</a></p>

<div class="card">
  <h2>What was checked</h2>
  <ul>{stats_html}</ul>
</div>
{extra_card}
<div class="card">
  <h2>Issues to review</h2>
  {findings_html(record['findings'])}
</div>
{errors_html}
<div class="card">
  <h2>Honesty note</h2>
  <p>Every item above is an issue to review, found by deterministic
  checks. A finding is not a determination that a site is compliant or
  non-compliant, and an empty findings list would not be a guarantee of
  compliance either. The signing officer reviews the evidence and makes
  the call.</p>
  <p class="small">{nc.DRAFT_STAMP}</p>
</div>
"""
    return page(heading, body)


def _yesno(flag):
    return "yes" if flag else "no"


def loi25_results_page(record):
    s = record["stats"]
    rows = [
        ("Privacy policy linked from the homepage",
         _yesno(s.get("privacy_link_found"))),
        ("Privacy pages scanned", str(s.get("privacy_pages_scanned", 0))),
        ("Privacy officer / contact named",
         _yesno(s.get("officer_found"))),
        ("Cookie consent mechanism detected",
         _yesno(s.get("cookie_consent_found"))),
        ("French privacy policy reachable",
         _yesno(s.get("policy_french_reachable"))),
    ]
    return _site_results_page(record, "Loi25 Kit results", rows)


def francais_results_page(record):
    s = record["stats"]
    rows = [
        ("French entry point on the homepage",
         _yesno(s.get("french_entry_found"))),
        ("hreflang=\"fr\" declaration found",
         _yesno(s.get("hreflang_fr_found"))),
        ("French pages tried", str(s.get("attempts", 0))),
        ("French pages resolved", str(s.get("attempts_ok", 0))),
    ]
    attempt_rows = "".join(f"""
<tr>
  <td>{escape(a['role'])}</td>
  <td>{escape(a['url'])}</td>
  <td>{'resolved' if a['ok'] else 'did not resolve'}</td>
  <td>{escape(a.get('lang') or '—')}</td>
</tr>""" for a in record["attempts"])
    extra = f"""
<div class="card">
  <h2>French addresses tried</h2>
  <table>
    <tr><th>Page</th><th>French address</th><th>Result</th>
        <th>Declared language</th></tr>
    {attempt_rows}
  </table>
</div>"""
    return _site_results_page(record, "Français Check results", rows,
                              extra_card=extra)


def _site_pack_html(record, module_label, stats_rows):
    date_line = record["timestamp"][:10]
    counts = nc.count_by_severity(record["findings"])
    counts_line = " · ".join(
        f"{sev} {counts[sev]}" for sev in ("high", "medium", "low", "info"))
    stats_html = "".join(
        f"<li><strong>{escape(k)}:</strong> {escape(v)}</li>"
        for k, v in stats_rows)
    pages_html = "".join(f"<li>{escape(u)}</li>" for u in record["pages"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NorthCheck Evidence Pack — {escape(module_label)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>NorthCheck Evidence Pack — {escape(module_label)}</h1>
<p><strong>{escape(nc.DRAFT_STAMP, quote=False)}</strong></p>
<ul>
  <li><strong>Module:</strong> {escape(module_label)}</li>
  <li><strong>Target:</strong> {escape(record['start_url'])}</li>
  <li><strong>Date scanned:</strong> {escape(date_line)}</li>
  <li><strong>Pages scanned:</strong> {len(record['pages'])}</li>
  <li><strong>Total issues to review:</strong> {record['total_findings']}
      ({counts_line})</li>
</ul>
<h2>What was checked</h2>
<ul>{stats_html}</ul>
<h2>Pages scanned</h2>
<ul>{pages_html}</ul>
<h2>Issues to review</h2>
{findings_html(record['findings'])}
<h2>Honesty note</h2>
<p>Every item above is an issue to review, found by deterministic checks
against the stated rules. A finding means the check matched something
worth a human look — it is not a determination that the target is
compliant or non-compliant, and an empty findings list would not be a
guarantee of compliance either. The signing officer / owner reviews the
evidence and makes the call.</p>
<hr>
<p class="small">Generated by NorthCheck. {HONESTY_LINE}</p>
</main>
</body>
</html>
"""


def loi25_pack_html(record):
    s = record["stats"]
    rows = [
        ("Privacy policy linked from the homepage",
         _yesno(s.get("privacy_link_found"))),
        ("Privacy pages scanned", str(s.get("privacy_pages_scanned", 0))),
        ("Privacy officer / contact named",
         _yesno(s.get("officer_found"))),
        ("Cookie consent mechanism detected",
         _yesno(s.get("cookie_consent_found"))),
        ("French privacy policy reachable",
         _yesno(s.get("policy_french_reachable"))),
    ]
    return _site_pack_html(record, "Loi25 Kit — Quebec Law 25 website "
                                   "evidence", rows)


def francais_pack_html(record):
    s = record["stats"]
    rows = [
        ("French entry point on the homepage",
         _yesno(s.get("french_entry_found"))),
        ("hreflang=\"fr\" declaration found",
         _yesno(s.get("hreflang_fr_found"))),
        ("French pages tried", str(s.get("attempts", 0))),
        ("French pages resolved", str(s.get("attempts_ok", 0))),
    ]
    rows += [(f"French {a['role']} page", a["url"] + " — "
              + ("resolved" if a["ok"] else "did not resolve"))
             for a in record["attempts"]]
    return _site_pack_html(record, "Français Check — French version "
                                   "reachability", rows)


# ---------------------------------------------------------------------------
# AODA Complete the Filing — checklist, Filing Pack, statement
# ---------------------------------------------------------------------------

OWNER_STATED_LINE = ("Checklist answers below are the organization's "
                     "own statements, recorded as given. NorthCheck "
                     "has not verified them.")


def load_checklists():
    return load_list(CHECKLISTS_PATH)


def find_checklist(checklist_id):
    return next((c for c in load_checklists()
                 if c.get("id") == checklist_id), None)


def latest_checklist_for_site(key):
    for record in reversed(load_checklists()):
        if record.get("site_key") == key:
            return record
    return None


def latest_aoda_for_site(key):
    return previous_aoda_scan(key, load_list(SCANS_PATH))


def filing_form_page(prefill=None, error=None):
    prefill = prefill or {}
    answers = prefill.get("answers", {})
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    sections = []
    for section in nc.FILING_CHECKLIST:
        radios = []
        for item in section["items"]:
            options = []
            for status in nc.CHECKLIST_STATUSES:
                checked = " checked" if answers.get(item["id"]) == status \
                    else ""
                label = nc.CHECKLIST_STATUS_LABELS[status].replace(
                    " (owner stated)", "")
                options.append(
                    f'<label style="display:inline-block;font-weight:400;'
                    f'margin:0 14px 0 0">'
                    f'<input type="radio" name="item_{item["id"]}" '
                    f'value="{status}"{checked}> {escape(label)}</label>')
            radios.append(f"""
<div class="finding">
  <p><strong>{escape(item['id'])}</strong> — {escape(item['text'])}</p>
  <p>{''.join(options)}</p>
</div>""")
        sections.append(f"""
<div class="card">
  <h2>{escape(section['standard'])}</h2>
  <p class="small">{escape(section['applies'])}</p>
  {''.join(radios)}
</div>""")
    body = f"""
<h1>Complete the Filing — checklist for the rest of the report</h1>
<p>The December 31, 2026 accessibility compliance report asks about
every part of the Integrated Accessibility Standards Regulation — the
General requirements, Information and Communications, Employment,
Transportation (only if you provide transportation services), the
Design of Public Spaces, and Customer Service — and it must be
certified by a senior officer. The website scan covers the web part.
This checklist covers the rest.</p>
<div class="deadline">
  <strong>These answers are your organization's own statements.</strong>
  NorthCheck records them as given and does not verify them. They are
  labelled "owner stated" everywhere they appear, including in the
  Filing Pack. The report itself is filed by your organization on the
  Ontario government portal — NorthCheck prepares the evidence, it
  does not file or certify.
</div>
{err}
<form method="post" action="/filing">
<div class="card">
  <label for="org_name">Organization name</label>
  <input type="text" id="org_name" name="org_name" required
         value="{escape(prefill.get('org_name', ''), quote=True)}"
         placeholder="Maple Street Bakery Inc.">
  <label for="website">Website (the address you scanned)</label>
  <input type="url" id="website" name="website" required
         value="{escape(prefill.get('website', ''), quote=True)}"
         placeholder="https://yourbusiness.ca">
</div>
{''.join(sections)}
<button type="submit">Save the checklist</button>
</form>
<p class="small">{HONESTY_LINE}</p>
"""
    return page("Complete the Filing — checklist", body)


def _checklist_answers_html(answers):
    """Checklist answers grouped by standard, owner-stated labelled."""
    out = []
    for section in nc.FILING_CHECKLIST:
        rows = []
        for item in section["items"]:
            status = answers.get(item["id"])
            if status not in nc.CHECKLIST_STATUSES:
                status = "unanswered"
            rows.append(f"""
<tr>
  <td><strong>{escape(item['id'])}</strong></td>
  <td>{escape(item['text'])}</td>
  <td>{escape(nc.CHECKLIST_STATUS_LABELS[status])}</td>
</tr>""")
        out.append(f"""
<h3>{escape(section['standard'])}</h3>
<table>
  <tr><th>Item</th><th>Statement</th><th>Owner's answer</th></tr>
  {''.join(rows)}
</table>""")
    return "\n".join(out)


def _website_status_html(scan, detailed=False):
    """Website evidence block shared by the view page and the pack."""
    if scan is None:
        return ("<p>No AODA website scan is on file for this site yet. "
                "Run the <a href=\"/scan\">website scan</a> so the "
                "Filing Pack can include the website evidence.</p>")
    counts = nc.count_by_severity(
        [f for pr in scan["pages"] for f in pr["findings"]])
    counts_line = " · ".join(
        f"{sev} {counts[sev]}" for sev in ("high", "medium", "low",
                                           "info"))
    comp = scan.get("comparison")
    comp_html = ""
    if comp:
        c = comp["counts"]
        comp_html = f"""
<p><strong>Remediation status (verified by re-scan only):</strong>
{c['resolved']} verified resolved since the previous scan
({escape(comp['previous_timestamp'])}), {c['still_open']} still open,
{c['new']} new, {c['not_rechecked']} on pages not re-crawled.</p>"""
    findings_block = ""
    if detailed:
        sections = []
        for pr in scan["pages"]:
            sections.append(f"""
<h3>Page: {escape(pr['url'])}</h3>
{findings_html(pr['findings'])}""")
        findings_block = "\n".join(sections)
    return f"""
<p>Latest scan: {escape(scan['timestamp'])} · {len(scan['pages'])}
page(s) · <strong>{scan['total_findings']} issues to review</strong>
({counts_line})</p>
{comp_html}
{findings_block}"""


def filing_view_page(record):
    scan = latest_aoda_for_site(record["site_key"])
    summary = nc.checklist_summary(record["answers"])
    t = summary["totals"]
    std_rows = "".join(
        f"<tr><td>{escape(r['standard'])}</td>"
        f"<td>{r['compliant']}</td><td>{r['in_progress']}</td>"
        f"<td>{r['not_started']}</td><td>{r['not_applicable']}</td>"
        f"<td>{r['unanswered']}</td></tr>"
        for r in summary["per_standard"])
    gaps = nc.filing_gaps(record["answers"],
                          comparison=(scan or {}).get("comparison"),
                          latest_total=(scan or {}).get(
                              "total_findings"))
    gaps_html = "".join(f"<li>{escape(g)}</li>" for g in gaps) \
        or "<li>No gaps recorded from the scan or the checklist.</li>"
    body = f"""
<h1>Filing Pack — {escape(record['org_name'])}</h1>
<p>Website: <strong>{escape(record['website'])}</strong><br>
Checklist saved: {escape(record['timestamp'])}</p>
<p><a class="btn" href="/filing/pack/{record['id']}">Download the Filing Pack (HTML)</a>
<a class="btn" href="/filing/statement/{record['id']}">Download the accessibility statement (HTML)</a></p>

<div class="card">
  <h2>Before you file — read this</h2>
  <p>{escape(nc.FILING_CERTIFICATION_NOTE)}</p>
</div>

<div class="card">
  <h2>Website evidence (from the AODA scan)</h2>
  {_website_status_html(scan)}
</div>

<div class="card">
  <h2>Checklist answers (owner stated)</h2>
  <p class="small">{OWNER_STATED_LINE}</p>
  <p>Compliant {t['compliant']} · In progress {t['in_progress']} ·
  Not started {t['not_started']} · Not applicable
  {t['not_applicable']} · Not answered {t['unanswered']} of
  {t['total']} items.</p>
  <table>
    <tr><th>Standard</th><th>Compliant</th><th>In progress</th>
        <th>Not started</th><th>Not applicable</th>
        <th>Not answered</th></tr>
    {std_rows}
  </table>
</div>

<div class="card">
  <h2>Remaining gaps</h2>
  <ul>{gaps_html}</ul>
</div>

<p class="small">{nc.DRAFT_STAMP}</p>
"""
    return page("Filing Pack", body)


def filing_pack_html(record):
    scan = latest_aoda_for_site(record["site_key"])
    gaps = nc.filing_gaps(record["answers"],
                          comparison=(scan or {}).get("comparison"),
                          latest_total=(scan or {}).get(
                              "total_findings"))
    gaps_html = "".join(f"<li>{escape(g)}</li>" for g in gaps) \
        or "<li>No gaps recorded from the scan or the checklist.</li>"
    date_line = record["timestamp"][:10]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NorthCheck Filing Pack — AODA Complete the Filing</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>NorthCheck Filing Pack — AODA Complete the Filing</h1>
<p><strong>{escape(nc.DRAFT_STAMP, quote=False)}</strong></p>
<ul>
  <li><strong>Organization:</strong> {escape(record['org_name'])}</li>
  <li><strong>Website:</strong> {escape(record['website'])}</li>
  <li><strong>Pack prepared:</strong> {escape(date_line)}</li>
  <li><strong>Filing deadline:</strong> December 31, 2026 (Ontario
  accessibility compliance report, organizations with 20+ employees)</li>
</ul>

<h2>Before you file — certification</h2>
<div class="deadline">
  <p>{escape(nc.FILING_CERTIFICATION_NOTE)}</p>
</div>

<h2>1. Website findings and status (scan evidence)</h2>
{_website_status_html(scan, detailed=True)}

<h2>2. Checklist answers by standard (owner stated)</h2>
<p>{OWNER_STATED_LINE}</p>
{_checklist_answers_html(record['answers'])}

<h2>3. Remaining gaps</h2>
<ul>{gaps_html}</ul>

<h2>Honesty note</h2>
<p>Website findings are issues to review, found by deterministic
checks — not determinations of compliance or non-compliance, and an
empty findings list would not be a guarantee of compliance either.
Checklist answers are the organization's own statements and have not
been verified by NorthCheck. The signing officer reviews all of the
evidence and makes the call.</p>
<hr>
<p class="small">Generated by NorthCheck. {HONESTY_LINE}</p>
</main>
</body>
</html>
"""


def statement_html(record):
    """Publish-ready accessibility statement for the org's own site.

    Every sentence is built from the inputs on file (org name, site,
    scan summary, checklist state). Anything only the organization
    can supply is a bracketed placeholder, marked as such — nothing
    is invented on the organization's behalf.
    """
    scan = latest_aoda_for_site(record["site_key"])
    today = datetime.date.today().isoformat()
    if scan is not None:
        scan_date = scan["timestamp"][:10]
        if scan["total_findings"]:
            scan_sentence = (
                f"Our most recent automated website check, run on "
                f"{scan_date} over {len(scan['pages'])} page(s) of "
                f"this site, found {scan['total_findings']} issue(s) "
                f"for us to review against WCAG 2.0. We are working "
                f"through them. Automated checks cover only part of "
                f"what accessibility standards ask for, so a check "
                f"that finds nothing would not by itself mean the "
                f"site presents no barriers.")
        else:
            scan_sentence = (
                f"Our most recent automated website check, run on "
                f"{scan_date} over {len(scan['pages'])} page(s) of "
                f"this site, found no issues matched by those checks. "
                f"Automated checks cover only part of what "
                f"accessibility standards ask for, so we continue to "
                f"review the site and welcome reports of any barrier.")
    else:
        scan_sentence = (
            "[WEBSITE CHECK — TO BE COMPLETED BY THE ORGANIZATION: "
            "no automated website check from NorthCheck is on file "
            "for this site yet. Delete this note once a check has "
            "been run, or replace it with your own summary.]")
    summary = nc.checklist_summary(record["answers"])
    t = summary["totals"]
    if t["unanswered"] == 0 and t["total"]:
        checklist_sentence = (
            f"We have reviewed our practices against the areas of "
            f"Ontario's accessibility standards (general "
            f"requirements, information and communications, customer "
            f"service, employment, and — where they apply to us — "
            f"transportation and the design of public spaces) and we "
            f"track our progress against them internally.")
    else:
        checklist_sentence = (
            f"We are reviewing our practices against the areas of "
            f"Ontario's accessibility standards (general "
            f"requirements, information and communications, customer "
            f"service, employment, and — where they apply to us — "
            f"transportation and the design of public spaces). "
            f"[REVIEW STATUS — TO BE COMPLETED BY THE ORGANIZATION: "
            f"{t['unanswered']} of {t['total']} review items have "
            f"not been answered yet. Update this sentence when the "
            f"review is complete.]")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Accessibility Statement — {escape(record['org_name'])}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<p class="small">Prepared by NorthCheck for
{escape(record['org_name'])} on {today}. Text in [brackets] is a
placeholder only the organization can complete — review and finish
every bracketed item before publishing. This statement was generated
from the organization's recorded scan results and its own checklist
answers; it is not a certification.</p>
<hr>
<h1>Accessibility Statement</h1>
<p><strong>{escape(record['org_name'])}</strong> is committed to
treating people with disabilities in ways that preserve their
dignity and independence, and to meeting the requirements of the
Accessibility for Ontarians with Disabilities Act (AODA) and the
Integrated Accessibility Standards Regulation.</p>
<p>This statement covers our website, {escape(record['website'])}.</p>
<h2>Our website</h2>
<p>{escape(scan_sentence)}</p>
<h2>Beyond the website</h2>
<p>{escape(checklist_sentence)}</p>
<h2>Feedback</h2>
<p>We welcome feedback on the accessibility of our services and of
this website. To give feedback, request information in an alternate
format, or ask for communication supports, contact us:</p>
<ul>
  <li>[FEEDBACK CONTACT — TO BE COMPLETED BY THE ORGANIZATION:
  name or role, email address, phone number]</li>
</ul>
<p>We will respond to accessibility feedback in a format that is
accessible to the person providing it.</p>
<h2>Review</h2>
<p>This statement was prepared on {today} and will be reviewed when
our practices or this website change.</p>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# PostCheck
# ---------------------------------------------------------------------------

def postcheck_form_page():
    today = datetime.date.today().isoformat()
    body = f"""
<h1>PostCheck ON — job-posting check</h1>
<p>Paste a publicly advertised job posting. PostCheck checks it against
Ontario's January 1, 2026 posting rules (O. Reg. 476/24): compensation
and the $50,000 range cap, AI screening disclosure, vacancy statement,
and the prohibited Canadian-experience requirement. Saving the posting
starts its clocks: interviewed applicants notified within 45 days,
records retained for 3 years.</p>
<div class="card">
  <form method="post" action="/postcheck">
    <label for="title">Posting title</label>
    <input type="text" id="title" name="title" required
           placeholder="Warehouse Operations Supervisor">
    <label for="employer">Employer</label>
    <input type="text" id="employer" name="employer" required
           placeholder="Lakeside Logistics Inc.">
    <label for="date_posted">Date posted</label>
    <input type="date" id="date_posted" name="date_posted" required
           value="{today}">
    <label for="posting_text">Posting text</label>
    <textarea id="posting_text" name="posting_text" required
              placeholder="Paste the full posting text here"></textarea>
    <button type="submit">Check this posting</button>
  </form>
</div>
<p class="small">{HONESTY_LINE}</p>
"""
    return page("PostCheck ON", body)


def _md_lines_to_html(md_text):
    """Render the engine's simple suggestion lines as HTML list items."""
    items = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^- ", "", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>",
                      escape(line))
        items.append(f"<li>{line}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def postcheck_results_page(title, employer, posted, findings, details,
                           suggestions_md):
    nb = nc.notify_by(posted)
    ru = nc.retention_until(posted)
    body = f"""
<h1>PostCheck results</h1>
<p>Posting: <strong>{escape(title)}</strong> — {escape(employer)}<br>
Date posted: {posted.isoformat()}<br>
Compensation detected: {escape(details['compensation'])}</p>

<div class="card">
  <h2>Issues to review</h2>
  {findings_html(findings)}
</div>

<div class="card">
  <h2>Corrected-draft suggestions</h2>
  {_md_lines_to_html(suggestions_md)}
</div>

<div class="card">
  <h2>Posting clocks</h2>
  <p><strong>Interview-outcome notify-by:</strong> {nb.isoformat()}
  (date posted + 45 days) — every interviewed applicant must be told
  the outcome by this date.<br>
  <strong>Retention-until:</strong> {ru.isoformat()}
  (date posted + 3 years) — keep this posting and its associated records
  at least until this date.</p>
  <form method="post" action="/vault/save">
    <input type="hidden" name="title" value="{escape(title, quote=True)}">
    <input type="hidden" name="employer" value="{escape(employer, quote=True)}">
    <input type="hidden" name="date_posted" value="{posted.isoformat()}">
    <button type="submit">Save to vault</button>
  </form>
</div>

<p class="small">{escape(nc.DRAFT_STAMP, quote=False)}</p>
"""
    return page("PostCheck results", body)


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------

def vault_page(saved=False):
    entries = load_list(VAULT_PATH)
    notice = ('<div class="notice">Posting saved to the vault.</div>'
              if saved else "")
    if entries:
        today = datetime.date.today()
        rows = []
        for e in entries:
            try:
                nb = datetime.date.fromisoformat(e["notify_by"])
                remaining = (nb - today).days
                if remaining < 0:
                    days = (f'<span class="overdue">overdue by '
                            f'{-remaining} day(s)</span>')
                else:
                    days = f"{remaining} day(s)"
            except (KeyError, ValueError):
                days = "—"
            rows.append(f"""
<tr>
  <td>{escape(e.get('title', ''))}</td>
  <td>{escape(e.get('employer', ''))}</td>
  <td>{escape(e.get('date_posted', ''))}</td>
  <td>{escape(e.get('notify_by', ''))}</td>
  <td>{days}</td>
  <td>{escape(e.get('retention_until', ''))}</td>
</tr>""")
        table = f"""
<table>
  <tr><th>Title</th><th>Employer</th><th>Date posted</th>
      <th>Notify-by (+45 days)</th><th>Days remaining</th>
      <th>Retention-until (+3 years)</th></tr>
  {''.join(rows)}
</table>"""
    else:
        table = ("<p>No postings saved yet. Run a posting through "
                 "<a href=\"/postcheck\">PostCheck</a> and save it to "
                 "start its clocks.</p>")
    body = f"""
<h1>Posting vault</h1>
<p>Every saved posting with its Ontario clocks: interviewed applicants
notified within 45 days of the posting date, and the posting plus its
records retained for 3 years.</p>
{notice}
{table}
<p class="small">{HONESTY_LINE}</p>
"""
    return page("Posting vault", body)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "NorthCheck/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(),
                                        fmt % args))

    # -- helpers ----------------------------------------------------------

    def _send(self, status, body, content_type="text/html; charset=utf-8",
              extra_headers=None):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _form(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = urllib.parse.parse_qs(raw)
        return {k: v[0] for k, v in parsed.items()}

    def _not_found(self):
        self._send(404, page("Not found",
                             "<h1>Not found</h1><p>That page does not "
                             "exist. <a href=\"/\">Back to NorthCheck</a>"
                             "</p>"))

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/":
            joined = query.get("joined", [""])[0] == "1"
            self._send(200, landing_page(joined=joined))
        elif path == "/scan":
            self._send(200, scan_form_page())
        elif path == "/filing":
            prefill = {}
            site = (query.get("site", [""])[0] or "").strip()
            if site:
                existing = latest_checklist_for_site(site_key(site))
                prefill = {"website": site}
                if existing:
                    prefill["org_name"] = existing["org_name"]
                    prefill["answers"] = existing["answers"]
            self._send(200, filing_form_page(prefill=prefill))
        elif path.startswith("/filing/view/"):
            record = find_checklist(path[len("/filing/view/"):])
            if record is None:
                self._not_found()
            else:
                self._send(200, filing_view_page(record))
        elif path.startswith("/filing/pack/"):
            record = find_checklist(path[len("/filing/pack/"):])
            if record is None:
                self._not_found()
            else:
                self._send(
                    200, filing_pack_html(record),
                    extra_headers={
                        "Content-Disposition":
                            'attachment; filename="northcheck_filing_'
                            f'pack_{record["id"]}.html"'})
        elif path.startswith("/filing/statement/"):
            record = find_checklist(path[len("/filing/statement/"):])
            if record is None:
                self._not_found()
            else:
                self._send(
                    200, statement_html(record),
                    extra_headers={
                        "Content-Disposition":
                            'attachment; filename="accessibility_'
                            f'statement_{record["id"]}.html"'})
        elif path == "/loi25":
            self._send(200, _site_form_page("loi25"))
        elif path == "/francais":
            self._send(200, _site_form_page("francais"))
        elif path == "/postcheck":
            self._send(200, postcheck_form_page())
        elif path == "/vault":
            saved = query.get("saved", [""])[0] == "1"
            self._send(200, vault_page(saved=saved))
        elif path.startswith("/pack/"):
            scan_id = path[len("/pack/"):]
            record = next((s for s in load_list(SCANS_PATH)
                           if s.get("id") == scan_id), None)
            if record is None:
                self._not_found()
            else:
                module = record.get("module")
                if module == "loi25":
                    pack = loi25_pack_html(record)
                elif module == "francais":
                    pack = francais_pack_html(record)
                else:
                    pack = evidence_pack_html(record)
                self._send(
                    200, pack,
                    extra_headers={
                        "Content-Disposition":
                            f'attachment; filename="northcheck_evidence_'
                            f'pack_{scan_id}.html"'})
        else:
            self._not_found()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        form = self._form()
        if path == "/filing":
            org_name = (form.get("org_name") or "").strip()
            website = (form.get("website") or "").strip()
            if not org_name or not website.startswith(
                    ("http://", "https://")):
                self._send(400, filing_form_page(
                    error="Enter the organization name and a full "
                          "website URL starting with http:// or "
                          "https://"))
                return
            answers = {}
            for _section, item in nc.checklist_items():
                value = form.get(f"item_{item['id']}")
                if value in nc.CHECKLIST_STATUSES:
                    answers[item["id"]] = value
            record = {
                "id": uuid.uuid4().hex[:12],
                "org_name": org_name,
                "website": website,
                "site_key": site_key(website),
                "answers": answers,
                "timestamp": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            }
            entries = load_checklists()
            entries.append(record)
            _save(CHECKLISTS_PATH, entries)
            self._redirect(f"/filing/view/{record['id']}")
        elif path == "/founding":
            email = (form.get("email") or "").strip()
            if "@" not in email or "." not in email:
                self._send(400, page(
                    "Email not recorded",
                    "<h1>That email does not look complete</h1>"
                    "<p><a href=\"/\">Back to the founding list form</a>"
                    "</p>"))
                return
            entries = load_list(FOUNDING_PATH)
            entries.append({
                "email": email,
                "timestamp": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            })
            _save(FOUNDING_PATH, entries)
            self._redirect("/?joined=1")
        elif path == "/scan":
            url = (form.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                self._send(400, scan_form_page(
                    "Enter a full URL starting with http:// or https://"))
                return
            record = run_scan(url)
            if not record["pages"]:
                detail = "; ".join(record["errors"]) or "no pages read"
                self._send(400, scan_form_page(
                    f"No HTML pages could be scanned at that address "
                    f"({detail}). Check the URL and try again."))
                return
            self._send(200, scan_results_page(record))
        elif path in ("/loi25", "/francais"):
            module = path.lstrip("/")
            url = (form.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                self._send(400, _site_form_page(
                    module,
                    "Enter a full URL starting with http:// or https://"))
                return
            if module == "loi25":
                record = run_loi25_scan(url)
                results = loi25_results_page
            else:
                record = run_francais_scan(url)
                results = francais_results_page
            if not record["pages"]:
                detail = "; ".join(record["errors"]) or "no pages read"
                self._send(400, _site_form_page(
                    module,
                    f"No HTML pages could be scanned at that address "
                    f"({detail}). Check the URL and try again."))
                return
            self._send(200, results(record))
        elif path == "/postcheck":
            title = (form.get("title") or "").strip() or "Untitled posting"
            employer = (form.get("employer") or "").strip() \
                or "Not stated"
            text = form.get("posting_text") or ""
            try:
                posted = datetime.date.fromisoformat(
                    (form.get("date_posted") or "").strip())
            except ValueError:
                posted = datetime.date.today()
            if not text.strip():
                self._send(400, page(
                    "Posting text missing",
                    "<h1>Paste the posting text first</h1>"
                    "<p><a href=\"/postcheck\">Back to PostCheck</a></p>"))
                return
            findings, details = nc.run_postcheck(text)
            suggestions = nc.corrected_draft_suggestions(findings)
            self._send(200, postcheck_results_page(
                title, employer, posted, findings, details, suggestions))
        elif path == "/vault/save":
            title = (form.get("title") or "").strip() or "Untitled posting"
            employer = (form.get("employer") or "").strip() \
                or "Not stated"
            try:
                posted = datetime.date.fromisoformat(
                    (form.get("date_posted") or "").strip())
            except ValueError:
                self._send(400, page(
                    "Could not save",
                    "<h1>The posting date was missing or unreadable</h1>"
                    "<p><a href=\"/postcheck\">Back to PostCheck</a></p>"))
                return
            entry = {
                "title": title,
                "employer": employer,
                "date_posted": posted.isoformat(),
                "notify_by": nc.notify_by(posted).isoformat(),
                "retention_until": nc.retention_until(posted).isoformat(),
                "saved_at": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            }
            entries = load_list(VAULT_PATH)
            entries.append(entry)
            _save(VAULT_PATH, entries)
            self._redirect("/vault?saved=1")
        else:
            self._not_found()


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NorthCheck listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
