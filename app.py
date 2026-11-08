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
    <a href="/postcheck">PostCheck</a>
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
  <h2>Loi25 Kit <span class="badge soon">Coming soon</span></h2>
  <p>Quebec's Law 25 binds any business holding Quebecers' personal
  information — including sellers outside Quebec. Privacy officer,
  incident register, privacy impact assessments, bilingual policy.
  On the same engine; not yet open.</p>
</div>

<div class="card">
  <h2>Français Check <span class="badge soon">Coming soon</span></h2>
  <p>Bill 96 audit layer above translation tools: French predominance,
  trademark descriptors, and OQLF francization triggers for stores and
  sites selling into Quebec. On the same engine; not yet open.</p>
</div>

<div class="card">
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
                self._send(
                    200, evidence_pack_html(record),
                    extra_headers={
                        "Content-Disposition":
                            f'attachment; filename="northcheck_evidence_'
                            f'pack_{scan_id}.html"'})
        else:
            self._not_found()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        form = self._form()
        if path == "/founding":
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
