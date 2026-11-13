#!/usr/bin/env python3
"""
NorthCheck — production web app (free-tools build).

Canadian SMB compliance platform, Phase 1 modules:

  * AODA FileReady — scan a small business website for WCAG 2.0 issues
    Ontario's AODA asks about, and produce a dated evidence pack ahead
    of the December 31, 2026 accessibility compliance report deadline.
  * PostCheck ON — check a job posting against Ontario's Jan 1, 2026
    posting rules (O. Reg. 476/24) and work out its 45-day / 3-year
    clocks on the results page. (The posting vault is PAUSED as of
    the 2026-11-13 fix pass: /vault and /vault/save return the
    branded 404 and no save button is offered, until per-customer
    access exists. Stored vault data is left untouched.)
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
  * Email Authentication Check — DMARC / SPF / DKIM evidence from the
    domain's public DNS records only (DNS-over-HTTPS, no tenant or
    mailbox access). DKIM selectors cannot be enumerated from DNS, so
    the module checks a documented list of common selectors and says
    exactly that when none of them resolves.
  * Tracker and Consent Check — known tracker / ad-tag signatures,
    consent-platform signatures and Google Consent Mode signals in
    the HTML exactly as served. No JavaScript is run, so the module
    reports what the page source shows and never claims to prove
    when a tag fires in a real browser.
  * ADA Title II Check — WCAG 2.1 Level AA evidence for US state and
    local government websites under the Department of Justice's ADA
    Title II rule. The April 26, 2027 / April 26, 2028 deadlines are
    stated as "under the current DOJ rule". Free check; no price is
    set for this module.
  * Privacy Register — not a scan: the organization records its own
    privacy incidents and access / correction requests through
    forms, stored in the same JSON-store pattern as the checklist.
    Entries are owner-stated, never verified, and labelled as such
    on every surface including the dated register pack.
  * Compliance Calendar — a public page rendering the engine's one
    deadline table (nc.COMPLIANCE_CALENDAR): dated deadlines, review
    cadences and ongoing duties kept distinct, plus the existing
    monthly re-scan offers shown together at their existing prices. No
    bundle price exists and none is shown.
  * Evidence Binder — assembles one dated binder for a site from
    its stored scans across modules (a module with no scan on file
    is listed as such, never omitted), plus a senior-officer
    sign-off record stored with the binder and printed in it. The
    sign-off is owner-stated; certification happens on the Ontario
    portal, not here.

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
REGISTERS_PATH = os.path.join(DATA_DIR, "registers.json")
BINDERS_PATH = os.path.join(DATA_DIR, "binders.json")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8790"))

MAX_PAGES = 10            # same-domain crawl cap per scan
PAGE_TIMEOUT = 8          # seconds per fetched page
MAX_BODY = 2_000_000      # bytes per fetched page

HONESTY_LINE = ("NorthCheck prepares evidence. It does not certify "
                "compliance and is not legal advice.")

BASE_URL = "https://getnorthcheck.ca"

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
.skip { position: absolute; left: -9999px; top: 0; background: #fff;
        color: #123524; padding: 10px 16px; z-index: 10;
        font-weight: 700; }
.skip:focus { left: 8px; top: 8px; }
@media (max-width: 760px) {
  header.site nav { float: none; margin-top: 8px; }
  header.site nav a { display: inline-block; margin: 2px 14px 2px 0; }
}
"""


# ---------------------------------------------------------------------------
# Search and sharing metadata (SEO)
# ---------------------------------------------------------------------------

# Per-page metadata, keyed by the title each page passes to page().
# "path" is the page's canonical public path. Result views have
# per-record URLs, so they carry a description but no canonical.
PAGE_SEO = {
    "AODA compliance report — December 31, 2026 deadline": {
        "path": "/",
        "description":
            "Ontario's AODA accessibility compliance report is due "
            "December 31, 2026. Run the free website scan and get a "
            "dated evidence pack for your senior officer.",
    },
    "AODA website scan": {
        "path": "/scan",
        "description":
            "Scan your website free for the December 31, 2026 AODA "
            "filing: up to 10 pages crawled, deterministic WCAG 2.0 "
            "checks, and a dated evidence pack to review.",
    },
    "AODA compliance report — due December 31, 2026": {
        "path": "/aoda-compliance-report",
        "description":
            "What Ontario organizations with 20 or more employees "
            "must file by December 31, 2026, what the AODA compliance "
            "report asks, and how NorthCheck can help.",
    },
    "Complete the Filing — checklist": {
        "path": "/filing",
        "description":
            "Complete the AODA filing: an owner-answered checklist "
            "for the non-website standards, a remediation tracker "
            "verified by re-scan, and one full Filing Pack.",
    },
    "Loi25 Kit — website check": {
        "path": "/loi25",
        "description":
            "Quebec Law 25 website check: a privacy policy linked "
            "from your homepage, a named privacy officer, a cookie "
            "consent mechanism, and a French privacy policy.",
    },
    "Français Check — French version check": {
        "path": "/francais",
        "description":
            "Français Check verifies that a real French version of "
            "your site exists: a French entry point, hreflang links, "
            "and French home, contact and privacy pages.",
    },
    "Email Authentication Check": {
        "path": "/emailauth",
        "description":
            "Check your domain's DMARC, SPF and DKIM records, free: "
            "read exactly the way a receiving mail server reads "
            "them, with a dated evidence pack of results.",
    },
    "Tracker and Consent Check": {
        "path": "/trackers",
        "description":
            "Free check: which ad trackers and marketing tags your "
            "website loads, and whether a consent banner or Google "
            "Consent Mode appears in the page source today.",
    },
    "ADA Title II Check": {
        "path": "/ada",
        "description":
            "Free ADA Title II website check for US state and local "
            "governments: WCAG 2.1 AA issues to review, a dated "
            "evidence pack, and the April 2027 and 2028 deadlines.",
    },
    "PostCheck ON": {
        "path": "/postcheck",
        "description":
            "Check a job posting against Ontario's January 1, 2026 "
            "posting rules: the pay range cap, AI screening "
            "disclosure, vacancy statement, and the records rule.",
    },
    "Scan results": {
        "description":
            "Your AODA scan results: WCAG 2.0 issues to review on "
            "the pages scanned, with a dated evidence pack. "
            "NorthCheck prepares evidence; it does not certify.",
    },
    "Loi25 Kit results": {
        "description":
            "Your Loi25 Kit results: what your public website shows "
            "for Quebec's Law 25, issue by issue, with a dated "
            "evidence pack. Evidence, not a certification.",
    },
    "Français Check results": {
        "description":
            "Your Français Check results: whether a real French "
            "version of your site exists and its key pages resolve "
            "in French, page by page, with an evidence pack.",
    },
    "Email Authentication Check results": {
        "description":
            "Your Email Authentication Check results: the DMARC, "
            "SPF and DKIM records that public DNS showed at scan "
            "time, with a full dated evidence pack for review.",
    },
    "Tracker and Consent Check results": {
        "description":
            "Your Tracker and Consent Check results: the trackers "
            "found in your site's page source, the consent signals "
            "detected, and a full dated evidence pack for review.",
    },
    "ADA Title II Check results": {
        "description":
            "Your ADA Title II Check results: WCAG 2.1 AA issues "
            "to review on your public website, page by page, with "
            "a dated evidence pack. Evidence, not certification.",
    },
    "Privacy Register": {
        "path": "/register",
        "description":
            "Keep your privacy register: log confidentiality "
            "incidents and access or correction requests, with "
            "the 30-day response window shown, as a dated pack.",
    },
    "Privacy Register — your entries": {
        "description":
            "Your privacy register entries: incidents and access "
            "or correction requests you recorded, labelled owner "
            "stated, with a dated register pack to download.",
    },
    "Compliance Calendar": {
        "path": "/calendar",
        "description":
            "Every NorthCheck deadline in one place: the December "
            "31, 2026 AODA report, Ontario posting duties, Law 25, "
            "and the ADA Title II dates in 2027 and 2028.",
    },
    "Evidence Binder": {
        "path": "/binder",
        "description":
            "One dated evidence binder for your site: every "
            "NorthCheck scan on file, what is missing, and a "
            "senior officer sign-off record, in a single pack.",
    },
    "Evidence Binder — cover": {
        "description":
            "Your evidence binder cover: which module scans are "
            "included, which have no scan on file, and the senior "
            "officer sign-off record for this binder.",
    },
    "PostCheck results": {
        "description":
            "Your PostCheck results: how the posting reads against "
            "Ontario's January 1, 2026 posting rules, with suggested "
            "corrections and its 45-day and 3-year clocks.",
    },
    "Filing Pack": {
        "description":
            "Your Filing Pack: website scan evidence combined with "
            "your organization's own owner-stated checklist answers, "
            "ready for a senior officer's final review.",
    },
}

# The public GET pages a crawler may index: the form and explainer
# pages only — never result views or downloads, whose URLs carry
# record ids.
SITEMAP_PATHS = ["/", "/aoda-compliance-report", "/scan", "/filing",
                 "/loi25", "/francais", "/emailauth", "/trackers",
                 "/ada", "/register", "/calendar", "/binder",
                 "/postcheck"]


def sitemap_xml():
    urls = "".join(f"  <url><loc>{BASE_URL}{p}</loc></url>\n"
                   for p in SITEMAP_PATHS)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/'
            'sitemap/0.9">\n' + urls + "</urlset>\n")


def robots_txt():
    return ("User-agent: *\nAllow: /\n"
            f"Sitemap: {BASE_URL}/sitemap.xml\n")


def security_txt():
    return ("Contact: mailto:jeremygordon6@gmail.com\n"
            "Preferred-Languages: en, fr\n"
            f"Canonical: {BASE_URL}/.well-known/security.txt\n"
            "\n"
            "NorthCheck is operated by CanCheck (Jeremy Gordon). "
            "Please report\nsecurity issues with this site to the "
            "contact above.\n")


# Baseline security headers sent on every response. The CSP is a
# baseline, not a strict policy: the pages are server-rendered with
# an inline <style> block and inline JSON-LD <script> blocks, so
# 'unsafe-inline' is required for style-src and script-src or the
# site breaks; everything else is locked to 'self', framing is
# denied (also via X-Frame-Options), and form posts go to 'self'.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy":
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
}


def _json_ld(data):
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False) + "</script>")


def home_json_ld():
    """Homepage structured data: the organization, plus a FAQ whose
    answers restate only facts and prices already shown on the page
    (the deadline box, the module cards, the filing copy)."""
    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "NorthCheck",
        "url": BASE_URL + "/",
        "description": PAGE_SEO[
            "AODA compliance report — December 31, 2026 deadline"
        ]["description"],
    }
    faq_pairs = [
        ("When is Ontario's AODA accessibility compliance report "
         "due?",
         "December 31, 2026. Ontario businesses and non-profits with "
         "20 or more employees must file an accessibility compliance "
         "report by December 31, 2026."),
        ("Who has to file an AODA compliance report?",
         "Ontario businesses and non-profits with 20 or more "
         "employees. Those with 50 or more employees must also "
         "certify that their websites meet WCAG 2.0 Level AA."),
        ("What does the AODA compliance report ask about?",
         "Every part of the Integrated Accessibility Standards "
         "Regulation: the General requirements, Information and "
         "Communications, Employment, Transportation (only if you "
         "provide transportation services), the Design of Public "
         "Spaces, and Customer Service — and it must be certified by "
         "a senior officer."),
        ("Does NorthCheck file or certify the report?",
         "No. The report itself is filed by your organization "
         "through the Ontario government's Accessibility Compliance "
         "Reporting portal and certified by a senior officer. "
         "NorthCheck prepares the evidence a senior officer reviews "
         "before signing; it does not certify compliance and is not "
         "legal advice."),
        ("How much does NorthCheck cost?",
         "Founding prices shown on this page, in CAD: the AODA "
         "evidence pack is $149 CAD, monitoring (a re-scan plan: "
         "you ask, we re-run the scan — no automatic scheduler "
         "yet) is $39 CAD/month, PostCheck ON is $49 CAD/month, "
         "and the Complete Filing Pack is $249 CAD."),
    ]
    faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faq_pairs],
    }
    return _json_ld(org) + "\n" + _json_ld(faq)


def page(title, body, extra_head=""):
    full_title = f"{title} — NorthCheck"
    seo = PAGE_SEO.get(title, {})
    description = seo.get("description")
    path = seo.get("path")
    head_extra = (
        '\n<meta name="google-site-verification" '
        'content="GP0cHkACrflT-3zNe7A33me-mfctb1OgeCyK7ZlHNfo">'
        '\n<meta name="msvalidate.01" '
        'content="5A6E6E3DD0931B9DB02307A62305125F">')
    if description:
        head_extra += (f'\n<meta name="description" '
                       f'content="{escape(description, quote=True)}">')
    if path:
        head_extra += (f'\n<link rel="canonical" '
                       f'href="{BASE_URL}{path}">')
    if description:
        head_extra += (
            f'\n<meta property="og:title" '
            f'content="{escape(full_title, quote=True)}">'
            f'\n<meta property="og:description" '
            f'content="{escape(description, quote=True)}">'
            '\n<meta property="og:type" content="website">')
        if path:
            head_extra += (f'\n<meta property="og:url" '
                           f'content="{BASE_URL}{path}">')
        head_extra += (
            '\n<meta name="twitter:card" content="summary">'
            f'\n<meta name="twitter:title" '
            f'content="{escape(full_title, quote=True)}">'
            f'\n<meta name="twitter:description" '
            f'content="{escape(description, quote=True)}">')
    if extra_head:
        head_extra += "\n" + extra_head
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(full_title)}</title>{head_extra}
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to main content</a>
<header class="site">
  <a href="/">NorthCheck</a>
  <nav aria-label="Primary">
    <a href="/scan">AODA scan</a>
    <a href="/filing">Complete the Filing</a>
    <a href="/postcheck">PostCheck</a>
    <a href="/loi25">Loi25 Kit</a>
    <a href="/francais">Français Check</a>
    <a href="/emailauth">Email check</a>
    <a href="/trackers">Tracker check</a>
    <a href="/ada">ADA (US)</a>
    <a href="/register">Register</a>
    <a href="/calendar">Calendar</a>
    <a href="/binder">Binder</a>
  </nav>
</header>
<main id="main">
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
    thanks = ('<div class="notice">Thanks — you are on the founding '
              'list for the Loi25 Kit paid plan. We will write when '
              'that plan opens. Checkout for the AODA packs and '
              'PostCheck ON is open on this page.</div>') \
        if joined else ""
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
  <p><strong>Founding price: $149 CAD</strong> per evidence pack ·
  <strong>$39 CAD/month</strong> monitoring — a re-scan plan: you ask, we re-run the scan and compare it with your last scan. No automatic scheduler yet.</p>
  <p><strong>Complete the Filing Pack</strong> — it prepares
  evidence for every part of the report (the Integrated
  Accessibility Standards Regulation), not just the website, and
  the non-website answers in the pack are your own statements. A
  senior officer has to certify the report. This
  fuller offer adds a remediation tracker (a finding counts as fixed
  only when a re-scan verifies it is gone — never on a say-so), an
  owner-answered checklist for the non-website standards, one Filing
  Pack that combines the website evidence with those answers and the
  remaining gaps, and a publish-ready accessibility statement for
  your site. <strong>Founding price: $249 CAD</strong> for the Complete
  Filing Pack.</p>
  <p><a href="/aoda-compliance-report">What the December 31, 2026
  compliance report requires, in full</a></p>
  <a class="btn" href="/filing">Complete the Filing checklist</a>
  <a class="btn" href="https://buy.stripe.com/cNi00c4kVgGP9um5wM5Rm06">Buy the Complete Filing Pack — $249 CAD</a><br>
  <a class="btn" href="/scan">Scan my website</a>
  <a class="btn" href="https://buy.stripe.com/eVqaEQ6t32PZ6iaaR65Rm00">Buy the evidence pack — $149 CAD</a>
  <a class="btn" href="https://buy.stripe.com/cNi3co4kV4Y77meaR65Rm01">Add monitoring — $39 CAD/month</a>
</div>

<div class="card">
  <h2>PostCheck ON <span class="badge">Module 2 — live</span></h2>
  <p>Since January 1, 2026, Ontario employers with 25 or more employees
  must state compensation in every public posting (range no wider than
  $50,000 unless the top exceeds $200,000), disclose AI screening, state
  whether a vacancy exists, include no Canadian-experience requirement,
  notify interviewed applicants within 45 days, and keep records for
  3 years. PostCheck reads the posting the way the rule does, suggests
  the corrected draft, and works out the posting's clocks.</p>
  <p><strong>Founding price: $49 CAD/month</strong> flat per company.
  The 45-day and 3-year clocks are worked out each time you check
  a posting or ask for a re-scan — nothing runs on a schedule in
  the background.</p>
  <a class="btn" href="/postcheck">Check a job posting</a>
  <a class="btn" href="https://buy.stripe.com/14A8wI5oZairbCugbq5Rm02">Subscribe — $49 CAD/month</a>
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
  on a website (privacy impact assessments, internal governance)
  are out of scope for this scan and are never implied by it. The
  incident register is one of those invisible duties, so NorthCheck
  offers it separately: the <a href="/register">Privacy Register</a>
  tool below is where you record incidents and requests yourself.
  This scan neither checks nor implies anything about a register.</p>
  <p>The check is available now. The paid plan is on the founding
  list. <strong>Founding price: $39 CAD/month</strong> per site.
  Re-scans run when you ask and are compared with your last scan —
  there is no automatic refresh.</p>
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
  <p><strong>Included</strong> with a scan or a monitoring re-scan plan.</p>
  <a class="btn" href="/francais">Check my French version</a>
</div>

<div class="card">
  <h2>Email Authentication Check <span class="badge">Module 5 — live</span></h2>
  <p>Spoofed email is how most small-firm fraud starts, and the defence
  lives in three public DNS records. This check reads them the way a
  receiving mail server does: the SPF record at your domain (missing,
  duplicated, +all pass-everyone, or over the 10-lookup limit), the
  DMARC policy at _dmarc (missing, monitor-only p=none, or p=reject),
  and DKIM keys under the common selectors used by the big senders.
  What it finds is what your DNS shows — no mailbox access, no sign-in,
  and when DKIM uses a selector name outside the common list, the
  report says so instead of claiming DKIM is absent.</p>
  <p><strong>Free check</strong> · included with monitoring re-scan plans.</p>
  <a class="btn" href="/emailauth">Check my domain's email records</a>
  <p class="small">Run Microsoft 365 for your firm? This check covers
  the public DNS side. The tenant side — accounts, app access,
  insurer evidence — is what <a href="https://tenantcheck365.ca">TenantCheck 365</a>
  checks.</p>
</div>

<div class="card">
  <h2>Tracker and Consent Check <span class="badge">Module 6 — live</span></h2>
  <p>Most sites load advertising trackers the moment a page opens.
  This check reads your site's HTML exactly as served and reports
  what is actually in the source: the known trackers and marketing
  tags (Google Analytics, Tag Manager, Meta Pixel, Google Ads,
  TikTok, LinkedIn, Hotjar, Microsoft Clarity and similar), whether
  any consent mechanism shows with them (a consent platform like
  OneTrust or Cookiebot, banner markup, consent wording), and
  whether Google Consent Mode signals appear alongside the Google
  tags. It runs no JavaScript, so it never claims to prove when a
  tag fires in a real browser — it shows you the tags and the
  consent signals, side by side, as dated evidence you can act
  on.</p>
  <p><strong>Free check</strong> · included with monitoring re-scan plans.</p>
  <a class="btn" href="/trackers">Check my site's trackers</a>
</div>

<div class="card">
  <h2>ADA Title II Check (US) <span class="badge">Module 7 — live</span></h2>
  <p>US state and local governments face the same shape of rule
  under the Americans with Disabilities Act: the Department of
  Justice's Title II rule requires their websites and mobile apps
  to conform to WCAG 2.1 Level AA. Under the current DOJ rule, the
  deadline is <strong>April 26, 2027</strong> for public entities
  serving a population of 50,000 or more, and
  <strong>April 26, 2028</strong> for smaller public entities and
  special district
  governments. This check crawls up to 10 pages of a public site
  and runs the WCAG 2.1 checks the HTML as served honestly
  supports — the carried-over page criteria plus 2.1's own
  input-purpose criterion, frame titles and zoom settings — then
  builds the same dated evidence pack as every NorthCheck module.
  What the scan cannot read (the inside of PDF documents, app
  behaviour, anything that needs rendering) is named in the
  results, not skipped over.</p>
  <p><strong>Free check</strong> · new US module.</p>
  <a class="btn" href="/ada">Run the ADA Title II check</a>
</div>

<div class="card">
  <h2>Privacy Register <span class="badge">Module 8 — live</span></h2>
  <p>Quebec's Law 25 expects an organization to keep a register of
  confidentiality incidents, and PIPEDA requires every
  organization it covers to keep a record of every breach of
  security safeguards for at least 24 months — and no website
  scan can see whether you keep one.
  This tool is the register itself, not a check of it: you record
  each privacy incident (what happened, when you discovered it,
  who was affected, what you did, who was notified) and each
  access or correction request from an individual, with the
  30-day response window shown beside every request. Entries are
  your own records, stored as given and never verified by
  NorthCheck, and you can download the whole register as one
  dated pack.</p>
  <p><strong>Free tool</strong> · included with every plan.</p>
  <a class="btn" href="/register">Open the Privacy Register</a>
</div>

<div class="card">
  <h2>Compliance Calendar</h2>
  <p>Every date NorthCheck covers, on one page: the December 31,
  2026 AODA report (and the 3-year cycle after it), the Ontario
  posting duties in force since January 1, 2026, Law 25's ongoing
  duties, and the ADA Title II dates in April 2027 and April 2028
  under the current DOJ rule — with the monthly re-scan offers shown
  together at their regular prices.</p>
  <a class="btn" href="/calendar">See the compliance calendar</a>
</div>

<div class="card">
  <h2>Evidence Binder + senior-officer sign-off</h2>
  <p>When the pieces are done, a senior officer needs one folder,
  not seven downloads. The binder assembles every NorthCheck scan
  on file for your site — AODA, Loi25, Français, email, trackers,
  ADA, and your filing checklist where one exists — into a single
  dated pack. Modules with no scan on file are listed as missing,
  never quietly dropped, and a sign-off record (officer name,
  title, date, and the review statement) is stored with the
  binder and printed in it.</p>
  <a class="btn" href="/binder">Assemble an evidence binder</a>
</div>

<div class="card" id="founding">
  <h2>Join the founding list</h2>
  <p>Checkout is open for the AODA evidence pack, AODA monitoring,
  the Complete Filing Pack, and PostCheck ON. Français Check is
  included with a scan or a monitoring re-scan plan, and the Email
  Authentication Check is free.</p>
  <p>The Loi25 Kit check is available now. Its paid plan stays on
  this founding list. Founding pricing for that plan is locked for
  the first cohort. Leave an email and we will write when the
  Loi25 paid plan opens. No email is sent by this form — it only
  records your address.</p>
  {thanks}
  <form method="post" action="/founding">
    <label for="email">Email address</label>
    <input type="email" id="email" name="email" required
           placeholder="you@yourbusiness.ca">
    <button type="submit">Join the founding list</button>
  </form>
  <p class="small">CanCheck is operated by Jeremy Gordon. By
  joining the founding list, you agree to receive email from
  CanCheck about the Loi25 Kit paid plan and the offers above.
  You can unsubscribe at any time — reply to any email and ask
  to be removed, and we will remove you.</p>
</div>

<p class="small">{HONESTY_LINE} Every finding is an issue to review,
found by deterministic checks — never a certification.</p>
"""
    return page("AODA compliance report — December 31, 2026 deadline",
                body, extra_head=home_json_ld())


# ---------------------------------------------------------------------------
# AODA compliance report — deadline landing page
# ---------------------------------------------------------------------------

def aoda_report_page():
    body = f"""
<h1>AODA compliance report — due December 31, 2026</h1>
<p>Ontario's accessibility law asks covered organizations to file an
accessibility compliance report — and the next one is due
<strong>December 31, 2026</strong>.</p>

<div class="deadline">
  <strong>Who must file:</strong> Ontario businesses and non-profits
  with 20 or more employees must file an accessibility compliance
  report by December 31, 2026 — and those with 50 or more must also
  certify that their websites meet WCAG 2.0 Level AA. Giving false or
  misleading information in the report is an offence, and a senior
  officer signs it. An overlay widget does not produce filing
  evidence. A scan with a dated evidence pack does.
</div>

<div class="card">
  <h2>What the report asks</h2>
  <p>The December 31, 2026 accessibility compliance report asks about
  every part of the Integrated Accessibility Standards Regulation —
  the General requirements, Information and Communications,
  Employment, Transportation (only if you provide transportation
  services), the Design of Public Spaces, and Customer Service —
  and it must be certified by a senior officer. The website is one
  part of it, not the whole report.</p>
</div>

<div class="card">
  <h2>How NorthCheck fits</h2>
  <p><strong>Start with the free scan.</strong> Point the
  <a href="/scan">AODA scanner</a> at your website: it crawls up to
  {MAX_PAGES} pages, runs the deterministic WCAG 2.0 checks, and
  builds a dated evidence pack. <strong>Founding price: $149 CAD</strong>
  per evidence pack · <strong>$39 CAD/month</strong> monitoring — a
  re-scan plan: you ask, we re-run the scan and compare it with
  your last scan. No automatic scheduler yet. Checkout is open at
  these founding prices.</p>
  <p><strong>The report covers more than the website.</strong> The
  <a href="/filing">Complete the Filing Pack</a> (<strong>founding
  price: $249 CAD</strong>) adds a remediation tracker — a finding counts
  as fixed only when a re-scan verifies it is gone, never on a
  say-so — an owner-answered checklist for the non-website
  standards, one Filing Pack that combines the website evidence with
  those answers and the remaining gaps, and a publish-ready
  accessibility statement for your site.</p>
  <a class="btn" href="/scan">Scan my website</a>
  <a class="btn" href="https://buy.stripe.com/eVqaEQ6t32PZ6iaaR65Rm00">Buy the evidence pack — $149 CAD</a>
  <a class="btn" href="https://buy.stripe.com/cNi3co4kV4Y77meaR65Rm01">Add monitoring — $39 CAD/month</a><br>
  <a class="btn" href="/filing">Complete the Filing checklist</a>
  <a class="btn" href="https://buy.stripe.com/cNi00c4kVgGP9um5wM5Rm06">Buy the Complete Filing Pack — $249 CAD</a>
</div>

<div class="card">
  <h2>Who files, who certifies</h2>
  <p>{escape(nc.FILING_CERTIFICATION_NOTE)}</p>
  <p class="small">{HONESTY_LINE} Every finding is an issue to review,
  found by deterministic checks — never a certification.</p>
</div>
"""
    return page("AODA compliance report — due December 31, 2026", body)


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
    elif module == "trackers":
        title = "Tracker and Consent Check"
        intro = ("Enter your website address. NorthCheck crawls up "
                 f"to {MAX_PAGES} pages on the same domain and reads "
                 "the HTML exactly as served: the known trackers "
                 "and marketing tags in the page source, whether a "
                 "consent platform, banner or consent wording shows "
                 "with them, and whether Google Consent Mode signals "
                 "appear. No JavaScript is run, so the check reports "
                 "what the source shows — never a claim about when "
                 "a tag fires in a real browser.")
        action, cta = "/trackers", "Run the tracker check"
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
# ADA Title II Check — WCAG 2.1 AA evidence for US public websites
# ---------------------------------------------------------------------------
# Same shape as the other site modules: the shared crawler fetches
# the pages, the engine checks them (nc.run_ada_checks), and the
# shared results / pack renderers present the findings. The module
# is a free check — no price is set and no payment link exists for
# it. Deadline dates are stated throughout as "under the current
# DOJ rule" (see the engine's module notes for why).

def run_ada_scan(start_url):
    pages, errors = crawl(start_url)
    findings, stats = (nc.run_ada_checks(pages) if pages
                       else ([], {}))
    return _store_site_record({
        "id": uuid.uuid4().hex[:12],
        "module": "ada",
        "start_url": start_url,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": [p["url"] for p in pages],
        "errors": errors,
        "findings": findings,
        "stats": stats,
        "total_findings": len(findings),
    })


def _ada_stats_rows(record):
    s = record["stats"]
    return [
        ("Title II deadline — entities serving 50,000 or more",
         f"{nc.ADA_DEADLINE_LARGE}, under the current DOJ rule"),
        ("Title II deadline — smaller entities and special districts",
         f"{nc.ADA_DEADLINE_SMALL}, under the current DOJ rule"),
        ("Pages scanned", str(s.get("pages_scanned", 0))),
        ("Pages with at least one issue",
         str(s.get("pages_with_findings", 0))),
        ("Accessibility statement / ADA contact found",
         _yesno(s.get("statement_found"))),
        ("PDF documents linked (not checked)",
         str(s.get("pdf_links", 0))),
    ]


def ada_form_page(error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    body = f"""
<h1>ADA Title II Check — US public websites</h1>
<p>Enter the website address of a US state or local government
entity. NorthCheck crawls up to {MAX_PAGES} pages on the same domain
and checks the WCAG 2.1 Level AA issues the HTML as served can
honestly show, then builds a dated evidence pack. Under the
current DOJ rule, public entities serving a population of 50,000 or more
must conform by <strong>{nc.ADA_DEADLINE_LARGE}</strong>, and
smaller public entities and special district governments by
<strong>{nc.ADA_DEADLINE_SMALL}</strong>.</p>
{err}
<div class="card">
  <form method="post" action="/ada">
    <label for="url">Website URL (http or https)</label>
    <input type="url" id="url" name="url" required
           placeholder="https://www.yourcity.gov">
    <button type="submit">Run the ADA Title II check</button>
  </form>
</div>
<p class="small">{HONESTY_LINE}</p>
"""
    return page("ADA Title II Check", body)


def ada_results_page(record):
    extra = f"""
<div class="card">
  <h2>Which deadline applies</h2>
  <p>Under the US Department of Justice's current ADA Title II web
  and mobile app rule, a public entity serving a population of
  50,000 or more must conform by <strong>{nc.ADA_DEADLINE_LARGE}</strong>;
  smaller public entities and special district governments by
  <strong>{nc.ADA_DEADLINE_SMALL}</strong>. The standard is WCAG
  2.1 Level AA. The 2027 and 2028 dates come from the Department's
  April 2026 Interim Final Rule — confirm the date that applies to
  your entity with your own legal counsel before relying on this
  pack. NorthCheck prepares evidence; it does not certify
  compliance and is not legal advice.</p>
</div>"""
    return _site_results_page(record, "ADA Title II Check results",
                              _ada_stats_rows(record), extra_card=extra)


def ada_pack_html(record):
    return _site_pack_html(
        record, "ADA Title II Check — US ADA Title II website "
                "evidence", _ada_stats_rows(record))


# ---------------------------------------------------------------------------
# Email Authentication Check — DMARC / SPF / DKIM from public DNS
# ---------------------------------------------------------------------------
# The engine does the checking (nc.run_emailauth_checks) over an
# injectable resolver. Production uses DNS-over-HTTPS; the checker
# sets NORTHCHECK_DNS_FIXTURE to a JSON file of fabricated answers so
# the whole module can be verified offline:
#   {name: {"answers": [TXT, ...]} | {"error": true}}

def _fixture_resolver():
    path = os.environ.get("NORTHCHECK_DNS_FIXTURE")
    if not path:
        return None
    table = _load(path, {})

    def resolve(name):
        entry = table.get(name)
        if entry is None:
            return []
        if entry.get("error"):
            raise nc.DnsLookupError(
                f"DNS lookup for {name} failed (fixture error)")
        return list(entry.get("answers", []))

    return resolve


def run_emailauth_scan(domain):
    findings, stats = nc.run_emailauth_checks(
        domain, resolver=_fixture_resolver())
    return _store_site_record({
        "id": uuid.uuid4().hex[:12],
        "module": "emailauth",
        "start_url": stats["domain"],
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": [stats["domain"]],
        "errors": stats.get("lookup_errors", []),
        "findings": findings,
        "stats": stats,
        "total_findings": len(findings),
    })


def emailauth_form_page(error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    body = f"""
<h1>Email Authentication Check — DMARC / SPF / DKIM</h1>
<p>Enter your domain. NorthCheck reads its public email
authentication records — SPF at the domain, DMARC at
_dmarc.yourdomain, and DKIM under the common selectors — and builds
a dated evidence pack from what the DNS actually shows. No mailbox
access, no sign-in, nothing installed.</p>
{err}
<div class="card">
  <form method="post" action="/emailauth">
    <label for="domain">Domain (for example yourbusiness.ca)</label>
    <input type="text" id="domain" name="domain" required
           placeholder="yourbusiness.ca">
    <button type="submit">Run the email check</button>
  </form>
</div>
<p class="small">{HONESTY_LINE} This check reports what public DNS
records show at scan time.</p>
"""
    return page("Email Authentication Check", body)


def _emailauth_rows(record):
    s = record["stats"]
    spf_state = "not found"
    if s.get("spf_record"):
        spf_state = "found"
        if len(s.get("spf_records", [])) > 1:
            spf_state += f" ({len(s['spf_records'])} records — invalid)"
    lookups = s.get("spf_dns_lookups")
    dkim_found = s.get("dkim_found", [])
    return [
        ("SPF record at the domain", spf_state),
        ("SPF DNS lookups in the chain",
         "not counted" if lookups is None else
         str(lookups) + ("" if s.get("spf_lookup_complete")
                         else " (floor — part of the chain could "
                              "not be resolved)")),
        ("DMARC policy", s.get("dmarc_policy") or
         ("lookup failed" if s.get("dmarc_lookup_failed")
          else "no record")),
        ("DKIM selectors found",
         ", ".join(d["selector"] for d in dkim_found)
         if dkim_found else "none of the common selectors"),
        ("DKIM selectors checked",
         ", ".join(s.get("dkim_selectors_checked", []))),
    ]


def _emailauth_records_html(record):
    s = record["stats"]
    rows = []
    for text in s.get("spf_records", []):
        rows.append(("SPF · " + s["domain"], text))
    if s.get("dmarc_record"):
        rows.append(("DMARC · _dmarc." + s["domain"],
                     s["dmarc_record"]))
    for d in s.get("dkim_found", []):
        rows.append((f"DKIM · {d['selector']}._domainkey."
                     + s["domain"], d["record"]))
    if not rows:
        return ""
    items = "".join(
        f"<tr><td>{escape(name)}</td>"
        f"<td><span class=\"evidence\">{escape(text)}</span></td></tr>"
        for name, text in rows)
    return f"""
<div class="card">
  <h2>Records found (as published)</h2>
  <table>
    <tr><th>Record</th><th>Text</th></tr>
    {items}
  </table>
</div>"""


def _emailauth_crossref_card():
    return """
<div class="card">
  <h2>The other half of email safety</h2>
  <p>This check covers the public DNS records. If your firm runs
  Microsoft 365, the tenant itself — accounts without multi-factor
  authentication, app access nobody remembers approving, the
  evidence an insurer asks for at renewal — is the other half, and
  it is what <a href="https://tenantcheck365.ca">TenantCheck 365</a>
  checks.</p>
</div>"""


def emailauth_results_page(record):
    s = record["stats"]
    if s.get("resolution_failed"):
        body = f"""
<h1>Email Authentication Check results</h1>
<p>Domain: <strong>{escape(record['start_url'])}</strong><br>
Checked: {escape(record['timestamp'])}</p>
<div class="card">
  <h2>Check could not be completed</h2>
  <p>The DNS lookups this check depends on did not answer, so there
  are no findings to show. NorthCheck does not guess at DNS state:
  a resolver failure is reported as a failure, not dressed up as
  results. Try again in a few minutes.</p>
  <p><a class="btn" href="/emailauth">Run the check again</a></p>
</div>
{_emailauth_crossref_card()}
<div class="card">
  <h2>Honesty note</h2>
  <p class="small">{escape(nc.EMAILAUTH_STAMP)}</p>
</div>
"""
        return page("Email Authentication Check results", body)
    counts = nc.count_by_severity(record["findings"])
    counts_line = " · ".join(
        f"{sev} {counts[sev]}" for sev in ("high", "medium", "low", "info"))
    stats_html = "".join(
        f"<li><strong>{escape(k)}:</strong> {escape(v)}</li>"
        for k, v in _emailauth_rows(record))
    errors_html = ""
    if record["errors"]:
        items = "".join(f"<li>{escape(e)}</li>" for e in record["errors"])
        errors_html = f"""
<div class="card">
  <h2>Lookups that failed</h2>
  <p>These individual lookups did not answer. Sections that depend
  on them were judged only on what resolved.</p>
  <ul>{items}</ul>
</div>"""
    body = f"""
<h1>Email Authentication Check results</h1>
<p>Domain: <strong>{escape(record['start_url'])}</strong><br>
Checked: {escape(record['timestamp'])} ·
<strong>{record['total_findings']} issues to review in total</strong>
({counts_line})</p>
<p><a class="btn" href="/pack/{record['id']}">Download the evidence pack (HTML)</a></p>

<div class="card">
  <h2>What was checked</h2>
  <ul>{stats_html}</ul>
</div>
{_emailauth_records_html(record)}
<div class="card">
  <h2>Issues to review</h2>
  {findings_html(record['findings'])}
</div>
{errors_html}
{_emailauth_crossref_card()}
<div class="card">
  <h2>Honesty note</h2>
  <p>Every item above is an issue to review, found by deterministic
  checks against the domain's public DNS records. A finding is not a
  determination that mail is or is not protected, and an empty
  findings list would not be a guarantee either. DKIM selectors
  cannot be enumerated from DNS; this check reads the common
  selectors listed above and says so where it matters.</p>
  <p class="small">{escape(nc.EMAILAUTH_STAMP)}</p>
</div>
"""
    return page("Email Authentication Check results", body)


def emailauth_pack_html(record):
    s = record["stats"]
    date_line = record["timestamp"][:10]
    counts = nc.count_by_severity(record["findings"])
    counts_line = " · ".join(
        f"{sev} {counts[sev]}" for sev in ("high", "medium", "low", "info"))
    stats_html = "".join(
        f"<li><strong>{escape(k)}:</strong> {escape(v)}</li>"
        for k, v in _emailauth_rows(record))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NorthCheck Evidence Pack — Email Authentication Check</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>NorthCheck Evidence Pack — Email Authentication Check</h1>
<p><strong>{escape(nc.DRAFT_STAMP, quote=False)}</strong></p>
<ul>
  <li><strong>Module:</strong> Email Authentication Check —
      DMARC / SPF / DKIM</li>
  <li><strong>Domain:</strong> {escape(record['start_url'])}</li>
  <li><strong>Date checked:</strong> {escape(date_line)}</li>
  <li><strong>Total issues to review:</strong> {record['total_findings']}
      ({counts_line})</li>
</ul>
<h2>What was checked</h2>
<ul>{stats_html}</ul>
{_emailauth_records_html(record)}
<h2>Issues to review</h2>
{findings_html(record['findings'])}
<h2>Honesty note</h2>
<p>{escape(nc.EMAILAUTH_STAMP)} Every item above is an issue to
review, found by deterministic checks against the domain's public
DNS records. A finding means the check matched something worth a
human look — it is not a determination that the domain is compliant
or non-compliant, and an empty findings list would not be a
guarantee either. DKIM selectors cannot be enumerated from DNS;
this check reads a documented list of common selectors, and its
DKIM finding says exactly that.</p>
<hr>
<p class="small">Generated by NorthCheck. {HONESTY_LINE}</p>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Tracker and Consent Check — trackers vs consent in the served HTML
# ---------------------------------------------------------------------------
# The engine does the checking (nc.run_trackers_checks) over the same
# crawl the other site modules use. Detection is over the HTML
# exactly as served: tracker and consent-platform signatures plus
# Google Consent Mode signals. No JavaScript is run, so the results
# report what the page source shows and say, in the module stamp,
# that the check cannot show when a tag fires in a real browser.

def run_trackers_scan(start_url):
    pages, errors = crawl(start_url)
    findings, stats = (nc.run_trackers_checks(pages) if pages
                       else ([], {}))
    return _store_site_record({
        "id": uuid.uuid4().hex[:12],
        "module": "trackers",
        "start_url": start_url,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": [p["url"] for p in pages],
        "errors": errors,
        "findings": findings,
        "stats": stats,
        "total_findings": len(findings),
    })


def _trackers_rows(record):
    s = record["stats"]
    trackers = s.get("trackers_found", [])
    mech = []
    if s.get("consent_platforms"):
        mech.append("platform: " + ", ".join(s["consent_platforms"]))
    if s.get("banner_detected"):
        mech.append("banner markup")
    if s.get("consent_wording_found"):
        mech.append("consent wording")
    cm = "not found"
    if s.get("consent_mode_found"):
        calls = ", ".join(s.get("consent_mode_calls", []))
        cm = "found" + (f" ({calls} call)" if calls else
                        " (storage settings present)")
    return [
        ("Trackers found in the page source",
         ", ".join(trackers) if trackers
         else "none of the known signatures"),
        ("Google tags among them",
         _yesno(s.get("google_tags_found"))),
        ("Consent mechanism detected",
         ("yes — " + "; ".join(mech)) if mech else "no"),
        ("Google Consent Mode signals", cm),
    ]


def _trackers_detail_card(record):
    detail = record["stats"].get("trackers_detail", [])
    if not detail:
        return ""
    rows = "".join(f"""
<tr>
  <td>{escape(t['name'])}</td>
  <td>{escape(', '.join(t['pages']))}</td>
  <td><span class="evidence">{escape(', '.join(t['markers']))}</span></td>
</tr>""" for t in detail)
    return f"""
<div class="card">
  <h2>Trackers detected in the page source</h2>
  <table>
    <tr><th>Tracker</th><th>Seen on page(s)</th>
        <th>Signature matched</th></tr>
    {rows}
  </table>
  <p class="small">{escape(nc.TRACKERS_STAMP)}</p>
</div>"""


def trackers_results_page(record):
    return _site_results_page(
        record, "Tracker and Consent Check results",
        _trackers_rows(record),
        extra_card=_trackers_detail_card(record))


def trackers_pack_html(record):
    rows = _trackers_rows(record)
    rows += [(t["name"] + " — signature matched",
              ", ".join(t["markers"]) + " · seen on "
              + ", ".join(t["pages"]))
             for t in record["stats"].get("trackers_detail", [])]
    return _site_pack_html(
        record,
        "Tracker and Consent Check — trackers and consent signals",
        rows)


# ---------------------------------------------------------------------------
# Privacy Register — owner-recorded incidents and requests
# ---------------------------------------------------------------------------
# Deliberately NOT a scan. The Loi25 check can only report what a
# public website shows, and a privacy register leaves no trace on a
# website — so the register is its own tool: the organization
# records its incidents and its access / correction requests
# through these forms, and NorthCheck stores them in the same
# JSON-store pattern as the filing checklist (data/registers.json,
# on the app disk, same persistence caveat as every other store).
# Entries are owner-stated: never verified, labelled as such on the
# page and in the pack, under the engine's REGISTER_STAMP.

REGISTER_OWNER_LINE = ("Entries below are the organization's own "
                       "records, entered by the owner and stored as "
                       "given. NorthCheck has not verified them.")


def load_registers():
    return load_list(REGISTERS_PATH)


def find_register(register_id):
    return next((r for r in load_registers()
                 if r.get("id") == register_id), None)


def _save_register(record):
    entries = load_registers()
    for i, existing in enumerate(entries):
        if existing.get("id") == record["id"]:
            entries[i] = record
            break
    else:
        entries.append(record)
    _save(REGISTERS_PATH, entries)


def _valid_iso_date(value):
    try:
        datetime.date.fromisoformat((value or "").strip())
        return True
    except (ValueError, AttributeError):
        return False


def _select_html(name, choices, current=""):
    options = []
    for choice in choices:
        selected = " selected" if choice == current else ""
        options.append(f'<option value="{escape(choice, quote=True)}"'
                       f'{selected}>{escape(choice)}</option>')
    return (f'<select id="{name}" name="{name}">'
            + "".join(options) + "</select>")


def register_page(error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    existing = load_registers()
    if existing:
        items = "".join(
            f'<li><a href="/register/view/{r["id"]}">'
            f'{escape(r["org_name"])}</a> — {escape(r["website"])} · '
            f'{len(r.get("incidents", []))} incident(s), '
            f'{len(r.get("requests", []))} request(s)</li>'
            for r in existing)
        existing_html = f"""
<div class="card">
  <h2>Registers on file</h2>
  <ul>{items}</ul>
</div>"""
    else:
        existing_html = ""
    body = f"""
<h1>Privacy Register — incidents and requests you record</h1>
<p>Quebec's Law 25 expects an organization to keep a register of
confidentiality incidents involving personal information, and both
Law 25 and PIPEDA give individuals the right to ask for access to —
or correction of — their personal information, with a response
generally due within 30 days. Under PIPEDA, the duty to keep a
record of every breach of security safeguards applies to every
organization PIPEDA covers — it is not limited to federally
regulated work — and those records must be kept for at least
24 months. (General information, not legal advice.) None of
that is visible on a website,
so no scan can check it. This tool keeps the register itself.</p>
<div class="deadline">
  <strong>These entries are your organization's own records.</strong>
  You enter them, NorthCheck stores them as given and does not
  verify them. They are labelled "owner stated" everywhere,
  including in the register pack. Keeping this register is record
  keeping, not legal advice — whether an incident had to be
  reported, or a request answered a particular way, is a call for
  the organization and its own advisors.
</div>
{err}
<div class="card">
  <h2>Start a register</h2>
  <form method="post" action="/register">
    <label for="org_name">Organization name</label>
    <input type="text" id="org_name" name="org_name" required
           placeholder="Maple Street Bakery Inc.">
    <label for="website">Website</label>
    <input type="url" id="website" name="website" required
           placeholder="https://yourbusiness.ca">
    <button type="submit">Start the register</button>
  </form>
</div>
{existing_html}
<p class="small">{escape(nc.REGISTER_STAMP)}</p>
"""
    return page("Privacy Register", body)


def _incidents_table_html(record):
    incidents = record.get("incidents", [])
    if not incidents:
        return "<p>No incidents recorded yet.</p>"
    rows = []
    for e in incidents:
        regulator = escape(e.get("regulator_notified", ""))
        if e.get("regulator_date"):
            regulator += f" ({escape(e['regulator_date'])})"
        individuals = escape(e.get("individuals_notified", ""))
        if e.get("individuals_date"):
            individuals += f" ({escape(e['individuals_date'])})"
        rows.append(f"""
<tr>
  <td>{escape(e.get('date_discovered', ''))}</td>
  <td>{escape(e.get('type', ''))}</td>
  <td>{escape(e.get('description', ''))}<br>
      <span class="small">Affected: {escape(e.get('affected', '') or '—')}<br>
      Containment: {escape(e.get('containment', '') or '—')}</span></td>
  <td>{regulator}</td>
  <td>{individuals}</td>
</tr>""")
    return f"""
<table>
  <tr><th>Date discovered</th><th>Type</th>
      <th>Description (owner stated)</th><th>Regulator notified</th>
      <th>Affected individuals notified</th></tr>
  {''.join(rows)}
</table>"""


def _requests_table_html(record):
    requests = record.get("requests", [])
    if not requests:
        return "<p>No requests recorded yet.</p>"
    rows = []
    for e in requests:
        due = nc.register_request_due_date(e.get("date_received", ""))
        rows.append(f"""
<tr>
  <td>{escape(e.get('date_received', ''))}</td>
  <td>{escape(e.get('requester_type', ''))}</td>
  <td>{escape(e.get('request_type', ''))}</td>
  <td>{escape(due or '—')}</td>
  <td>{escape(e.get('status', ''))}</td>
  <td>{escape(e.get('date_completed', '') or '—')}</td>
</tr>""")
    return f"""
<table>
  <tr><th>Date received</th><th>Requester</th><th>Request</th>
      <th>Response window ends (received + {nc.REGISTER_RESPONSE_DAYS}
      days)</th><th>Status</th><th>Date completed</th></tr>
  {''.join(rows)}
</table>
<p class="small">The response-window date is general information
only: Law 25 and PIPEDA work with a {nc.REGISTER_RESPONSE_DAYS}-day
window for access and correction requests, with extensions in
defined cases. The exact duty for a given request is the
organization's call — this is not legal advice.</p>"""


def register_view_page(record, error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    today = datetime.date.today().isoformat()
    body = f"""
<h1>Privacy Register — {escape(record['org_name'])}</h1>
<p>Website: <strong>{escape(record['website'])}</strong><br>
Register started: {escape(record['timestamp'])} ·
{len(record.get('incidents', []))} incident(s) ·
{len(record.get('requests', []))} request(s) recorded</p>
<p><a class="btn" href="/register/pack/{record['id']}">Download the register pack (HTML)</a></p>
{err}
<div class="card">
  <h2>Confidentiality incidents (owner stated)</h2>
  <p class="small">{REGISTER_OWNER_LINE}</p>
  {_incidents_table_html(record)}
</div>

<div class="card">
  <h2>Log an incident</h2>
  <form method="post" action="/register/incident">
    <input type="hidden" name="register_id" value="{record['id']}">
    <label for="date_discovered">Date discovered</label>
    <input type="date" id="date_discovered" name="date_discovered"
           required value="{today}">
    <label for="incident_type">Type of incident</label>
    {_select_html("incident_type", nc.REGISTER_INCIDENT_TYPES)}
    <label for="description">What happened</label>
    <input type="text" id="description" name="description" required
           placeholder="Describe the incident in your own words">
    <label for="affected">Records / people affected</label>
    <input type="text" id="affected" name="affected"
           placeholder="For example: about 40 customer records">
    <label for="containment">Containment — what was done</label>
    <input type="text" id="containment" name="containment"
           placeholder="For example: access revoked, passwords reset">
    <label for="regulator_notified">Regulator notified</label>
    {_select_html("regulator_notified", nc.REGISTER_NOTIFIED_CHOICES,
                  "Not yet")}
    <label for="regulator_date">Date the regulator was notified
    (if applicable)</label>
    <input type="date" id="regulator_date" name="regulator_date">
    <label for="individuals_notified">Affected individuals
    notified</label>
    {_select_html("individuals_notified",
                  nc.REGISTER_NOTIFIED_CHOICES, "Not yet")}
    <label for="individuals_date">Date individuals were notified
    (if applicable)</label>
    <input type="date" id="individuals_date" name="individuals_date">
    <button type="submit">Add the incident</button>
  </form>
</div>

<div class="card">
  <h2>Access / correction requests (owner stated)</h2>
  <p class="small">{REGISTER_OWNER_LINE}</p>
  {_requests_table_html(record)}
</div>

<div class="card">
  <h2>Log a request</h2>
  <form method="post" action="/register/request">
    <input type="hidden" name="register_id" value="{record['id']}">
    <label for="date_received">Date received</label>
    <input type="date" id="date_received" name="date_received"
           required value="{today}">
    <label for="requester_type">Who asked</label>
    {_select_html("requester_type", nc.REGISTER_REQUESTER_TYPES)}
    <label for="request_type">Type of request</label>
    {_select_html("request_type", nc.REGISTER_REQUEST_TYPES)}
    <label for="status">Status</label>
    {_select_html("status", nc.REGISTER_REQUEST_STATUSES)}
    <label for="date_completed">Date completed (if completed)</label>
    <input type="date" id="date_completed" name="date_completed">
    <button type="submit">Add the request</button>
  </form>
  <p class="small">The response window is
  {nc.REGISTER_RESPONSE_DAYS} days from the date received, shown in
  the table above as general information — not legal advice.</p>
</div>

<p class="small">{escape(nc.REGISTER_STAMP)}</p>
<p class="small">{nc.DRAFT_STAMP}</p>
"""
    return page("Privacy Register — your entries", body)


def register_pack_html(record):
    date_line = datetime.date.today().isoformat()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NorthCheck Privacy Register Pack — {escape(record['org_name'])}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>NorthCheck Privacy Register Pack</h1>
<p><strong>{escape(nc.DRAFT_STAMP, quote=False)}</strong></p>
<ul>
  <li><strong>Organization:</strong> {escape(record['org_name'])}</li>
  <li><strong>Website:</strong> {escape(record['website'])}</li>
  <li><strong>Register started:</strong> {escape(record['timestamp'])}</li>
  <li><strong>Pack prepared:</strong> {escape(date_line)}</li>
  <li><strong>Entries:</strong> {len(record.get('incidents', []))}
  incident(s), {len(record.get('requests', []))} request(s)</li>
</ul>

<h2>Confidentiality incidents (owner stated)</h2>
<p>{REGISTER_OWNER_LINE}</p>
{_incidents_table_html(record)}

<h2>Access / correction requests (owner stated)</h2>
<p>{REGISTER_OWNER_LINE}</p>
{_requests_table_html(record)}

<h2>Honesty note</h2>
<p>{escape(nc.REGISTER_STAMP)} NorthCheck stores what the owner
records and does not verify entries, dates, or notification claims.
Whether an incident had to be reported to a regulator or to
affected individuals, and whether a request was answered as the
law requires, are determinations for the organization and its own
advisors.</p>
<hr>
<p class="small">Generated by NorthCheck. {HONESTY_LINE}</p>
</main>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Compliance Calendar — the year-round deadline picture
# ---------------------------------------------------------------------------
# A public page rendered from the engine's single table
# (nc.COMPLIANCE_CALENDAR) so the dates live in exactly one place.
# The bundle section shows the EXISTING monitoring offers together
# at their EXISTING prices, linked to their own module pages — no
# bundle price or discount exists, and none is shown; the section
# ends with the founding-list signup, like the homepage.

def calendar_page(joined=False):
    thanks = ('<div class="notice">Thanks — you are on the founding '
              'list for the Loi25 Kit paid plan. We will write when '
              'that plan opens. Checkout for the AODA packs and '
              'PostCheck ON is open.</div>'
              if joined else "")
    rows = []
    for item in nc.COMPLIANCE_CALENDAR:
        rows.append(f"""
<tr>
  <td><strong>{escape(item['area'])}</strong><br>
      <a href="{escape(item['link'])}">{escape(item['link_label'])}</a></td>
  <td>{escape(item['who'])}</td>
  <td><strong>{escape(item['when'])}</strong><br>
      <span class="small">{escape(item['kind'])}</span></td>
  <td>{escape(item['detail'])}</td>
</tr>""")
    body = f"""
<h1>Compliance calendar — the year-round picture</h1>
<p>Canadian compliance is not one deadline. These are the dates,
cadences and ongoing duties NorthCheck covers, in one place —
dated deadlines are called deadlines, and ongoing duties are
called ongoing duties.</p>

<div class="card">
  <table>
    <tr><th>What</th><th>Who it applies to</th><th>When</th>
        <th>What it involves</th></tr>
    {''.join(rows)}
  </table>
</div>

<div class="card">
  <h2>Monitoring, honestly described</h2>
  <p>Monitoring, as it works today: you ask, we re-run the scan
  and send you the comparison against your last scan. There is
  no scheduler quietly re-scanning your site on its own. What
  NorthCheck actually does today: every scan is stored,
  and when a site is scanned again, the new scan is compared with
  the previous one — findings that a re-scan no longer reports are
  shown as <strong>verified resolved by re-scan</strong>, alongside
  what is still open and what is new. That comparison is the
  re-scan evidence the monthly re-scan offers are built on,
  and it is
  why the AODA filing pack can say "fixed" without taking anyone's
  word for it.</p>
</div>

<div class="card">
  <h2>One subscription picture</h2>
  <p>The existing monthly re-scan offers, together at their regular
  founding prices. There is no separate bundle price — each offer
  keeps its own price and its own terms.</p>
  <table>
    <tr><th>Offer</th><th>Price</th><th>Where</th></tr>
    <tr>
      <td>AODA monitoring — re-scans on request, compared
      with your last scan</td>
      <td><strong>$39 CAD/month</strong></td>
      <td><a href="/">See the AODA FileReady offer</a></td>
    </tr>
    <tr>
      <td>PostCheck ON — Ontario job posting checks with the
      45-day and 3-year clocks worked out
      when a posting is checked or a re-scan is requested</td>
      <td><strong>$49 CAD/month</strong> flat per company</td>
      <td><a href="/postcheck">See PostCheck ON</a></td>
    </tr>
    <tr>
      <td>Loi25 Kit — Quebec Law 25 website evidence, re-run
      when you ask and compared with your last scan</td>
      <td><strong>$39 CAD/month</strong> per site</td>
      <td><a href="/loi25">See the Loi25 Kit</a></td>
    </tr>
  </table>
  {thanks}
  <form method="post" action="/founding">
    <label for="email">Email address</label>
    <input type="email" id="email" name="email" required
           placeholder="you@yourbusiness.ca">
    <button type="submit">Join the founding list</button>
  </form>
  <p class="small">CanCheck is operated by Jeremy Gordon. By
  joining the founding list, you agree to receive email from
  CanCheck about the Loi25 Kit paid plan and the offers above.
  You can unsubscribe at any time — reply to any email and ask
  to be removed, and we will remove you.</p>
</div>

<p class="small">{HONESTY_LINE} Dates that rest on a rule that can
change are worded with the rule's current state — confirm the date
that applies to your organization with your own advisors.</p>
"""
    return page("Compliance Calendar", body)


# ---------------------------------------------------------------------------
# Evidence Binder — one binder per site + senior-officer sign-off
# ---------------------------------------------------------------------------
# The binder does not scan anything. It assembles what is already
# on file for a site — the latest stored scan from each module in
# nc.BINDER_MODULES, plus the filing checklist where one exists —
# under one cover, and says plainly which modules have no scan on
# file. The sign-off record is the officer's own statement, stored
# with the binder and printed in the pack, labelled owner-stated
# everywhere. It is a record of review, not a certification:
# certification of the AODA report happens on the Ontario portal.

BINDER_OWNER_LINE = ("Sign-off details are the officer's own "
                     "statement, recorded as given. NorthCheck "
                     "has not verified them.")


def load_binders():
    return load_list(BINDERS_PATH)


def find_binder(binder_id):
    return next((b for b in load_binders()
                 if b.get("id") == binder_id), None)


def _save_binder(record):
    entries = load_binders()
    for i, existing in enumerate(entries):
        if existing.get("id") == record["id"]:
            entries[i] = record
            break
    else:
        entries.append(record)
    _save(BINDERS_PATH, entries)


def latest_scan_for_site_module(key, module):
    """Most recent stored scan of one module for a site key."""
    for record in reversed(load_list(SCANS_PATH)):
        if record.get("module") == module \
                and site_key(record.get("start_url", "")) == key:
            return record
    return None


def assemble_binder(org_name, website):
    """Build a binder record from what is on file for the site.

    Returns None when the site has no scans and no filing checklist
    on file — an honest "nothing to bind yet", never an empty
    binder.
    """
    key = site_key(website)
    scan_ids = {}
    included, missing = [], []
    for module, _label in nc.BINDER_MODULES:
        scan = latest_scan_for_site_module(key, module)
        if scan is None:
            missing.append(module)
        else:
            scan_ids[module] = scan["id"]
            included.append(module)
    checklist = latest_checklist_for_site(key)
    if not scan_ids and checklist is None:
        return None
    return {
        "id": uuid.uuid4().hex[:12],
        "org_name": org_name,
        "website": website,
        "site_key": key,
        "timestamp": datetime.datetime.now().isoformat(
            timespec="seconds"),
        "scan_ids": scan_ids,
        "included": included,
        "missing": missing,
        "checklist_id": checklist["id"] if checklist else None,
        "signoff": None,
    }


def _binder_scan_by_id(scan_id):
    return next((s for s in load_list(SCANS_PATH)
                 if s.get("id") == scan_id), None)


def _binder_contents_rows(record):
    """Cover contents: included modules with dates, missing named."""
    rows = []
    labels = dict(nc.BINDER_MODULES)
    for module in record["included"]:
        scan = _binder_scan_by_id(record["scan_ids"].get(module, ""))
        when = scan["timestamp"] if scan else "record not found"
        total = scan["total_findings"] if scan else 0
        rows.append(f"""
<tr>
  <td>{escape(labels[module])}</td>
  <td>Included — scanned {escape(str(when))} ·
      {total} issue(s) to review</td>
</tr>""")
    for module in record["missing"]:
        rows.append(f"""
<tr>
  <td>{escape(labels[module])}</td>
  <td><strong>No scan on file</strong> for this site — run the
      check to include it in a future binder.</td>
</tr>""")
    if record.get("checklist_id"):
        rows.append("""
<tr>
  <td>AODA Complete the Filing — owner-answered checklist</td>
  <td>Included (owner stated)</td>
</tr>""")
    else:
        rows.append("""
<tr>
  <td>AODA Complete the Filing — owner-answered checklist</td>
  <td><strong>No scan on file</strong> — no checklist on file for
      this site.</td>
</tr>""")
    return "\n".join(rows)


def _binder_signoff_html(record):
    signoff = record.get("signoff")
    if not signoff:
        return ("<p>No sign-off recorded yet for this binder. The "
                "officer's sign-off is recorded with the form "
                "below and printed in the binder pack.</p>")
    return f"""
<p><strong>Signed off by:</strong> {escape(signoff['officer_name'])},
{escape(signoff['title'])}<br>
<strong>Date:</strong> {escape(signoff['date'])}<br>
<strong>Statement:</strong> {escape(signoff['statement'])}</p>
<p class="small">{BINDER_OWNER_LINE}</p>"""


def binder_form_page(error=None, notice=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    note = (f'<div class="notice">{escape(notice)}</div>'
            if notice else "")
    body = f"""
<h1>Evidence Binder — one folder for the senior officer</h1>
<p>Enter your organization and the website address you scanned.
NorthCheck assembles one dated binder from every scan on file for
that site — AODA, Loi25, Français, Email Authentication, Tracker
and ADA — plus your AODA filing checklist where one exists.
Modules with no scan on file are listed on the cover as
<strong>no scan on file</strong>, never quietly dropped.</p>
<div class="deadline">
  <strong>The binder is evidence, not certification.</strong>
  NorthCheck prepares it; a senior officer reviews it and records
  their sign-off with the binder. The AODA accessibility compliance
  report itself is filed and certified by your organization on the
  Ontario government portal — not here.
</div>
{err}{note}
<div class="card">
  <form method="post" action="/binder">
    <label for="org_name">Organization name</label>
    <input type="text" id="org_name" name="org_name" required
           placeholder="Maple Street Bakery Inc.">
    <label for="website">Website (the address you scanned)</label>
    <input type="url" id="website" name="website" required
           placeholder="https://yourbusiness.ca">
    <button type="submit">Assemble the binder</button>
  </form>
</div>
<p class="small">{HONESTY_LINE}</p>
"""
    return page("Evidence Binder", body)


def binder_view_page(record, error=None):
    err = f'<div class="notice">{escape(error)}</div>' if error else ""
    today = datetime.date.today().isoformat()
    signoff_form = ""
    if not record.get("signoff"):
        signoff_form = f"""
<div class="card">
  <h2>Senior-officer sign-off</h2>
  <p>Recorded with this binder and printed in the pack. The
  sign-off is a record that the evidence was reviewed — it is not
  a certification, and it does not file anything.</p>
  <form method="post" action="/binder/signoff">
    <input type="hidden" name="binder_id" value="{record['id']}">
    <label for="officer_name">Officer name</label>
    <input type="text" id="officer_name" name="officer_name" required
           placeholder="Jordan Lee">
    <label for="officer_title">Title</label>
    <input type="text" id="officer_title" name="officer_title"
           required placeholder="President">
    <label for="signoff_date">Date</label>
    <input type="date" id="signoff_date" name="signoff_date"
           required value="{today}">
    <label style="font-weight:400">
      <input type="checkbox" name="statement_confirmed"
             value="yes" required>
      {escape(nc.BINDER_SIGNOFF_STATEMENT)}</label>
    <button type="submit">Record the sign-off</button>
  </form>
</div>"""
    body = f"""
<h1>Evidence Binder — {escape(record['org_name'])}</h1>
<p>Website: <strong>{escape(record['website'])}</strong><br>
Binder generated: {escape(record['timestamp'])}</p>
<p><a class="btn" href="/binder/pack/{record['id']}">Download the binder pack (HTML)</a></p>
{err}
<div class="card">
  <h2>Cover — what this binder contains</h2>
  <table>
    <tr><th>Module</th><th>Status in this binder</th></tr>
    {_binder_contents_rows(record)}
  </table>
</div>

<div class="card">
  <h2>Senior-officer sign-off (owner stated)</h2>
  {_binder_signoff_html(record)}
</div>
{signoff_form}
<p class="small">{nc.DRAFT_STAMP}</p>
"""
    return page("Evidence Binder — cover", body)


def _binder_module_section(module, scan):
    label = dict(nc.BINDER_MODULES)[module]
    if scan is None:
        return f"""
<h2>{escape(label)}</h2>
<p><strong>No scan on file</strong> for this site when this binder
was generated. This section is intentionally empty — the module is
listed so the gap is visible, not hidden.</p>"""
    if module == "aoda":
        return f"""
<h2>{escape(label)}</h2>
<p>Scanned: {escape(scan['timestamp'])} ·
<strong>{scan['total_findings']} issues to review</strong></p>
{_website_status_html(scan, detailed=True)}"""
    return f"""
<h2>{escape(label)}</h2>
<p>Scanned: {escape(scan['timestamp'])} ·
<strong>{scan['total_findings']} issues to review</strong></p>
{findings_html(scan.get('findings', []))}"""


def binder_pack_html(record):
    sections = []
    for module, _label in nc.BINDER_MODULES:
        scan = None
        if module in record.get("scan_ids", {}):
            scan = _binder_scan_by_id(record["scan_ids"][module])
        sections.append(_binder_module_section(module, scan))
    checklist_section = ""
    if record.get("checklist_id"):
        checklist = find_checklist(record["checklist_id"])
        if checklist is not None:
            checklist_section = f"""
<h2>AODA Complete the Filing — checklist answers (owner stated)</h2>
<p>{OWNER_STATED_LINE}</p>
{_checklist_answers_html(checklist['answers'])}"""
    if not checklist_section:
        checklist_section = """
<h2>AODA Complete the Filing — checklist answers</h2>
<p><strong>No scan on file</strong> — no filing checklist on file
for this site. This section is intentionally empty.</p>"""
    date_line = record["timestamp"][:10]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NorthCheck Evidence Binder — {escape(record['org_name'])}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>NorthCheck Evidence Binder</h1>
<p><strong>{escape(nc.DRAFT_STAMP, quote=False)}</strong></p>

<h2>Cover</h2>
<ul>
  <li><strong>Organization:</strong> {escape(record['org_name'])}</li>
  <li><strong>Website:</strong> {escape(record['website'])}</li>
  <li><strong>Binder generated:</strong> {escape(date_line)}</li>
</ul>
<table>
  <tr><th>Module</th><th>Status in this binder</th></tr>
  {_binder_contents_rows(record)}
</table>

<h2>Senior-officer sign-off (owner stated)</h2>
{_binder_signoff_html(record)}

{''.join(sections)}
{checklist_section}

<h2>Honesty note</h2>
<p>Every finding in this binder is an issue to review, found by
deterministic checks — not a determination that the site is
compliant or non-compliant, and an empty findings list would not
be a guarantee of compliance either. Checklist answers and the
sign-off are the organization's own statements and have not been
verified by NorthCheck. {escape(nc.FILING_CERTIFICATION_NOTE)}</p>
<hr>
<p class="small">Generated by NorthCheck. {HONESTY_LINE}</p>
</main>
</body>
</html>
"""


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
  <p class="small">The posting vault is paused: postings are not
  saved on this site right now, so keep these two dates with the
  posting itself.</p>
</div>

<p class="small">{escape(nc.DRAFT_STAMP, quote=False)}</p>
"""
    return page("PostCheck results", body)


# ---------------------------------------------------------------------------
# Posting vault — PAUSED (2026-11-13 fix pass, owner decision)
# ---------------------------------------------------------------------------
# The vault had no per-customer access: every saved posting was
# world-readable. GET /vault and POST /vault/save now fall through
# to the branded 404, the results page offers no save button, and
# /vault is out of the nav and the sitemap. The stored data file
# (VAULT_PATH) is deliberately left untouched. Re-enable only with
# per-customer access.


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
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(payload)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
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

    def do_HEAD(self):
        # Same routing, status and headers as GET (including the
        # security headers and Content-Length); _send withholds the
        # body, as HEAD requires.
        self._head_only = True
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/":
            joined = query.get("joined", [""])[0] == "1"
            self._send(200, landing_page(joined=joined))
        elif path == "/aoda-compliance-report":
            self._send(200, aoda_report_page())
        elif path == "/.well-known/security.txt":
            self._send(200, security_txt(),
                       content_type="text/plain; charset=utf-8")
        elif path == "/sitemap.xml":
            self._send(200, sitemap_xml(),
                       content_type="application/xml; charset=utf-8")
        elif path == "/robots.txt":
            self._send(200, robots_txt(),
                       content_type="text/plain; charset=utf-8")
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
        elif path == "/emailauth":
            self._send(200, emailauth_form_page())
        elif path == "/ada":
            self._send(200, ada_form_page())
        elif path == "/trackers":
            self._send(200, _site_form_page("trackers"))
        elif path == "/register":
            self._send(200, register_page())
        elif path.startswith("/register/view/"):
            record = find_register(path[len("/register/view/"):])
            if record is None:
                self._not_found()
            else:
                self._send(200, register_view_page(record))
        elif path.startswith("/register/pack/"):
            record = find_register(path[len("/register/pack/"):])
            if record is None:
                self._not_found()
            else:
                self._send(
                    200, register_pack_html(record),
                    extra_headers={
                        "Content-Disposition":
                            'attachment; filename="northcheck_privacy'
                            f'_register_{record["id"]}.html"'})
        elif path == "/calendar":
            joined = query.get("joined", [""])[0] == "1"
            self._send(200, calendar_page(joined=joined))
        elif path == "/binder":
            self._send(200, binder_form_page())
        elif path.startswith("/binder/view/"):
            record = find_binder(path[len("/binder/view/"):])
            if record is None:
                self._not_found()
            else:
                self._send(200, binder_view_page(record))
        elif path.startswith("/binder/pack/"):
            record = find_binder(path[len("/binder/pack/"):])
            if record is None:
                self._not_found()
            else:
                self._send(
                    200, binder_pack_html(record),
                    extra_headers={
                        "Content-Disposition":
                            'attachment; filename="northcheck_evidence'
                            f'_binder_{record["id"]}.html"'})
        elif path == "/postcheck":
            self._send(200, postcheck_form_page())
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
                elif module == "emailauth":
                    pack = emailauth_pack_html(record)
                elif module == "ada":
                    pack = ada_pack_html(record)
                elif module == "trackers":
                    pack = trackers_pack_html(record)
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
        if path == "/register":
            org_name = (form.get("org_name") or "").strip()
            website = (form.get("website") or "").strip()
            if not org_name or not website.startswith(
                    ("http://", "https://")):
                self._send(400, register_page(
                    error="Enter the organization name and a full "
                          "website URL starting with http:// or "
                          "https://"))
                return
            record = {
                "id": uuid.uuid4().hex[:12],
                "org_name": org_name,
                "website": website,
                "site_key": site_key(website),
                "incidents": [],
                "requests": [],
                "timestamp": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            }
            _save_register(record)
            self._redirect(f"/register/view/{record['id']}")
        elif path == "/register/incident":
            record = find_register(
                (form.get("register_id") or "").strip())
            if record is None:
                self._not_found()
                return
            date_discovered = (form.get("date_discovered")
                               or "").strip()
            description = (form.get("description") or "").strip()
            incident_type = (form.get("incident_type") or "").strip()
            regulator = (form.get("regulator_notified")
                         or "Not yet").strip()
            individuals = (form.get("individuals_notified")
                           or "Not yet").strip()
            regulator_date = (form.get("regulator_date")
                              or "").strip()
            individuals_date = (form.get("individuals_date")
                                or "").strip()
            if not _valid_iso_date(date_discovered) \
                    or not description \
                    or incident_type not in nc.REGISTER_INCIDENT_TYPES \
                    or regulator not in nc.REGISTER_NOTIFIED_CHOICES \
                    or individuals not in nc.REGISTER_NOTIFIED_CHOICES \
                    or (regulator_date
                        and not _valid_iso_date(regulator_date)) \
                    or (individuals_date
                        and not _valid_iso_date(individuals_date)):
                self._send(400, register_view_page(
                    record,
                    error="The incident was not saved: it needs a "
                          "valid date discovered, a type from the "
                          "list, and a description in your own "
                          "words. Notification dates, when given, "
                          "must be real dates."))
                return
            record.setdefault("incidents", []).append({
                "date_discovered": date_discovered,
                "type": incident_type,
                "description": description,
                "affected": (form.get("affected") or "").strip(),
                "containment": (form.get("containment") or "").strip(),
                "regulator_notified": regulator,
                "regulator_date": regulator_date,
                "individuals_notified": individuals,
                "individuals_date": individuals_date,
                "recorded": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            })
            _save_register(record)
            self._redirect(f"/register/view/{record['id']}")
        elif path == "/register/request":
            record = find_register(
                (form.get("register_id") or "").strip())
            if record is None:
                self._not_found()
                return
            date_received = (form.get("date_received") or "").strip()
            requester_type = (form.get("requester_type")
                              or "").strip()
            request_type = (form.get("request_type") or "").strip()
            status = (form.get("status") or "").strip()
            date_completed = (form.get("date_completed")
                              or "").strip()
            if not _valid_iso_date(date_received) \
                    or requester_type not in \
                    nc.REGISTER_REQUESTER_TYPES \
                    or request_type not in nc.REGISTER_REQUEST_TYPES \
                    or status not in nc.REGISTER_REQUEST_STATUSES \
                    or (date_completed
                        and not _valid_iso_date(date_completed)):
                self._send(400, register_view_page(
                    record,
                    error="The request was not saved: it needs a "
                          "valid date received and the requester, "
                          "request type and status from the lists. "
                          "A completion date, when given, must be "
                          "a real date."))
                return
            record.setdefault("requests", []).append({
                "date_received": date_received,
                "requester_type": requester_type,
                "request_type": request_type,
                "due_date": nc.register_request_due_date(date_received),
                "status": status,
                "date_completed": date_completed,
                "recorded": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            })
            _save_register(record)
            self._redirect(f"/register/view/{record['id']}")
        elif path == "/binder":
            org_name = (form.get("org_name") or "").strip()
            website = (form.get("website") or "").strip()
            if not org_name or not website.startswith(
                    ("http://", "https://")):
                self._send(400, binder_form_page(
                    error="Enter the organization name and a full "
                          "website URL starting with http:// or "
                          "https://"))
                return
            record = assemble_binder(org_name, website)
            if record is None:
                self._send(400, binder_form_page(
                    error="No scans on file for that site yet, and "
                          "no filing checklist either — there is "
                          "nothing to bind. Run at least one check "
                          "for the site first (the AODA scan, the "
                          "Loi25 check, or any other module), then "
                          "assemble the binder."))
                return
            _save_binder(record)
            self._redirect(f"/binder/view/{record['id']}")
        elif path == "/binder/signoff":
            record = find_binder(
                (form.get("binder_id") or "").strip())
            if record is None:
                self._not_found()
                return
            officer_name = (form.get("officer_name") or "").strip()
            title = (form.get("officer_title") or "").strip()
            signoff_date = (form.get("signoff_date") or "").strip()
            confirmed = (form.get("statement_confirmed")
                         or "").strip()
            if not officer_name or not title \
                    or not _valid_iso_date(signoff_date) \
                    or confirmed != "yes":
                self._send(400, binder_view_page(
                    record,
                    error="The sign-off was not recorded: it needs "
                          "the officer's name and title, a valid "
                          "date, and the review statement confirmed "
                          "with the checkbox."))
                return
            record["signoff"] = {
                "officer_name": officer_name,
                "title": title,
                "date": signoff_date,
                "statement": nc.BINDER_SIGNOFF_STATEMENT,
                "recorded": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            }
            _save_binder(record)
            self._redirect(f"/binder/view/{record['id']}")
        elif path == "/filing":
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
        elif path in ("/loi25", "/francais", "/trackers"):
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
            elif module == "trackers":
                record = run_trackers_scan(url)
                results = trackers_results_page
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
        elif path == "/emailauth":
            domain = nc.normalize_domain(form.get("domain") or "")
            if not re.fullmatch(
                    r"[a-z0-9]([a-z0-9-]*[a-z0-9])?"
                    r"(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", domain):
                self._send(400, emailauth_form_page(
                    "Enter a domain like yourbusiness.ca — a website "
                    "address works too, the domain is what gets "
                    "checked."))
                return
            record = run_emailauth_scan(domain)
            self._send(200, emailauth_results_page(record))
        elif path == "/ada":
            url = (form.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                self._send(400, ada_form_page(
                    "Enter a full URL starting with http:// or "
                    "https://"))
                return
            record = run_ada_scan(url)
            if not record["pages"]:
                detail = "; ".join(record["errors"]) or "no pages read"
                self._send(400, ada_form_page(
                    f"No HTML pages could be scanned at that address "
                    f"({detail}). Check the URL and try again."))
                return
            self._send(200, ada_results_page(record))
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
        else:
            # /vault/save also lands here: the vault is paused, so
            # saving a posting returns the branded 404 and writes
            # nothing.
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
