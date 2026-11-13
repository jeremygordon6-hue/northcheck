#!/usr/bin/env python3
"""NorthCheck web app — end-to-end verification.

Starts a fixture HTTP server (three fabricated sites — bad, good and
mid — plus the engine's demo page) and the app itself on throwaway
ports, then asserts:

  * the Phase 1 engine regression counts (demo AODA 10, PostCheck 4);
  * the pre-existing pages and flows (landing, /scan, /postcheck,
    /vault, evidence pack download, posting clocks);
  * Loi25 Kit: engine findings on the three fixtures (bad 3, good 0,
    mid 1), the /loi25 form and scan flow, and its evidence pack;
  * Français Check: engine findings (bad 4, good 0, mid 1, plus the
    resolved-but-English case), the /francais form and scan flow, and
    its evidence pack.
  * AODA Complete the Filing: re-scan comparison correctness on
    fabricated pages (improving site, dropped page, duplicate
    findings), the /filing checklist flow end to end, the Filing Pack
    (website findings + owner-stated answers + certification note),
    and the accessibility statement with marked placeholders.
  * Email Authentication Check: engine findings on fabricated DNS
    answers served through a mocked resolver (fully protected /
    unprotected / partial domains, multiple-SPF and over-lookup-limit
    records, and the resolver-failure path), the /emailauth form and
    scan flow (the app subprocess reads the same fabricated answers
    from a NORTHCHECK_DNS_FIXTURE JSON file — fully offline), and
    its evidence pack.

  * Tracker and Consent Check: engine findings on fabricated pages
    (trackers with no consent mechanism anywhere, trackers behind a
    named consent platform with Consent Mode signals, and a clean
    page with no trackers), the /trackers form and scan flow, and
    its evidence pack. Fully offline — the fixtures are served by
    the same local fixture server as the other site modules.
  * ADA Title II Check: engine findings on two fabricated US city
    sites (a problem city seeding the carried-over WCAG findings
    plus the ADA-only checks — iframe title, zoom-blocking
    viewport, input purpose, missing accessibility contact, an
    unchecked PDF — and a clean city with an ADA coordinator page),
    the /ada form and scan flow, its evidence pack, and the
    deadline copy (April 26, 2027 / April 26, 2028, stated as under
    the current DOJ rule, with no price or payment link).
  * SEO layer: per-page meta descriptions / Open Graph / canonical
    tags, homepage JSON-LD (Organization + FAQPage), /sitemap.xml and
    /robots.txt, and the /aoda-compliance-report deadline landing
    page (December 31, 2026, who must file, does-not-file honesty).

The app's data/ directory is backed up first and restored afterwards,
so founding signups, scans and vault entries from real use are never
touched by the test run.
"""

import json as _json_mod
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
import northcheck as nc

APP_PORT = 8893
FIX_PORT = 8894
BASE = f"http://127.0.0.1:{APP_PORT}"
FIX = f"http://127.0.0.1:{FIX_PORT}"
DATA_DIR = os.path.join(APP_DIR, "data")

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {detail}")


# ---------------------------------------------------------------------------
# Fabricated fixture sites (problems seeded on purpose — see expectations)
# ---------------------------------------------------------------------------

BAD_HOME = """<!DOCTYPE html>
<html lang="en">
<head><title>Bad Bakery</title></head>
<body>
<h1>Bad Bakery</h1>
<a href="/bad/contact">Contact us</a>
<p>We sell bread. Nothing else is published anywhere on this
site.</p>
</body>
</html>
"""
BAD_CONTACT = """<!DOCTYPE html>
<html lang="en">
<head><title>Contact — Bad Bakery</title></head>
<body><h1>Contact</h1><p>Call the shop.</p></body>
</html>
"""

GOOD_HOME = """<!DOCTYPE html>
<html lang="en">
<head><title>Good Grocer</title>
<link rel="alternate" hreflang="fr" href="/fr/good/">
<link rel="alternate" hreflang="en" href="/good/">
</head>
<body>
<h1>Good Grocer</h1>
<nav>
  <a href="/fr/good/">Français</a>
  <a href="/good/privacy">Privacy Policy</a>
  <a href="/good/contact">Contact us</a>
</nav>
<p>We use cookies to run this site. Manage your cookie consent
preferences or accept cookies.</p>
</body>
</html>
"""
GOOD_CONTACT = """<!DOCTYPE html>
<html lang="en">
<head><title>Contact — Good Grocer</title></head>
<body><h1>Contact</h1><p>Email the store.</p></body>
</html>
"""
GOOD_PRIVACY = """<!DOCTYPE html>
<html lang="en">
<head><title>Privacy Policy — Good Grocer</title></head>
<body>
<h1>Privacy Policy</h1>
<p>Our Privacy Officer is Alex Tremblay. You can reach the privacy
officer at privacy@good.example with any question about your personal
information.</p>
<a href="/fr/good/privacy">Politique de confidentialité en français</a>
</body>
</html>
"""
GOOD_FR_HOME = """<!DOCTYPE html>
<html lang="fr">
<head><title>Bon Marché</title></head>
<body>
<h1>Bon Marché</h1>
<a href="/fr/good/contact">Contactez-nous</a>
<a href="/fr/good/privacy">Politique de confidentialité</a>
</body>
</html>
"""
GOOD_FR_CONTACT = """<!DOCTYPE html>
<html lang="fr">
<head><title>Contact — Bon Marché</title></head>
<body><h1>Contact</h1><p>Écrivez au magasin.</p></body>
</html>
"""
GOOD_FR_PRIVACY = """<!DOCTYPE html>
<html lang="fr">
<head><title>Politique de confidentialité — Bon Marché</title></head>
<body><h1>Politique de confidentialité</h1>
<p>Notre responsable de la protection des renseignements personnels
est Alex Tremblay.</p></body>
</html>
"""

MID_HOME = """<!DOCTYPE html>
<html lang="en">
<head><title>Mid Motors</title>
<link rel="alternate" hreflang="fr" href="/fr/mid/">
</head>
<body>
<h1>Mid Motors</h1>
<nav>
  <a href="/fr/mid/">Français</a>
  <a href="/mid/privacy">Privacy Policy</a>
</nav>
<p>We use cookies on this site. <button>Accept cookies</button>
to continue.</p>
</body>
</html>
"""
MID_PRIVACY = """<!DOCTYPE html>
<html lang="en">
<head><title>Privacy Policy — Mid Motors</title></head>
<body>
<h1>Privacy Policy</h1>
<p>Questions about your personal information go to our privacy
officer, Sam Roy, at privacy@mid.example.</p>
</body>
</html>
"""
MID_FR_HOME = """<!DOCTYPE html>
<html lang="fr">
<head><title>Mid Motors FR</title></head>
<body><h1>Mid Motors</h1><p>Bienvenue.</p></body>
</html>
"""

# Tracker and Consent Check fixtures.
# /tracked/ — Google Analytics (gtag) + Meta Pixel in the source and
# no consent mechanism of any kind: no consent platform, no banner
# markup, and the word cookie never appears.
# -> TRACK-NO-CONSENT (high) + TRACK-NO-CONSENT-MODE (medium)
TRACKED_HOME = """<!DOCTYPE html>
<html lang="en">
<head><title>Tracked Treasures</title>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-TRACKED123"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-TRACKED123');
</script>
<script src="https://connect.facebook.net/en_US/fbevents.js"></script>
<script>fbq('init', '1234567890'); fbq('track', 'PageView');</script>
</head>
<body>
<h1>Tracked Treasures</h1>
<p>Handmade gifts and home goods, shipped anywhere in Canada.</p>
</body>
</html>
"""

# /consented/ — Google Tag Manager behind a Cookiebot script, with a
# gtag consent default call carrying all four Consent Mode storage
# settings. -> TRACK-CONSENT-UNVERIFIED (info), nothing else.
CONSENTED_HOME = """<!DOCTYPE html>
<html lang="en">
<head><title>Consented Crafts</title>
<script id="Cookiebot" src="https://consent.cookiebot.com/uc.js"
        data-cbid="00000000-0000-0000-0000-000000000000"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('consent', 'default', {
  'ad_storage': 'denied',
  'analytics_storage': 'denied',
  'ad_user_data': 'denied',
  'ad_personalization': 'denied'
});
</script>
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-CONSENT1"></script>
</head>
<body>
<h1>Consented Crafts</h1>
<p>We ask before we track. Manage your cookie consent preferences
or accept cookies to continue.</p>
</body>
</html>
"""

# ADA Title II fixtures: a fabricated US city site with seeded
# problems, a clean services page on the same site, and a clean city
# whose accessibility page names its ADA Coordinator.
# USGOV_HOME seeds: no lang (ADA-LANG), empty title (ADA-TITLE),
# h1 -> h3 skip (ADA-HEADING-ORDER), img without alt (ADA-IMG-ALT),
# unlabelled email field with no autocomplete (ADA-LABEL +
# ADA-INPUT-PURPOSE), iframe without title (ADA-IFRAME-TITLE),
# user-scalable=no viewport (ADA-VIEWPORT), one PDF link
# (ADA-PDF-UNCHECKED) and no accessibility contact anywhere
# (ADA-STATEMENT) = 10 findings across the two pages.
USGOV_HOME = """<!DOCTYPE html>
<html>
<head><title></title>
<meta name="viewport" content="width=device-width, user-scalable=no">
</head>
<body>
<h1>City of Example Falls</h1>
<h3>News</h3>
<img src="mayor.jpg">
<iframe src="https://www.youtube.com/embed/council"></iframe>
<form>
<input type="email" id="nl-email" name="email">
</form>
<a href="/usgov/services">City services</a>
<a href="/usgov/budget.pdf">2026 budget (PDF)</a>
</body>
</html>
"""
USGOV_SERVICES = """<!DOCTYPE html>
<html lang="en">
<head><title>City services — Example Falls</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>City services</h1>
<h2>Permits</h2>
<img src="counter.jpg" alt="Residents at the permits counter">
<form>
<label for="appt-email">Email for your appointment reminder</label>
<input type="email" id="appt-email" name="email" autocomplete="email">
</form>
<iframe src="https://maps.example.com/embed" title="Map of city offices"></iframe>
<a href="/usgov/">Back to the home page</a>
</body>
</html>
"""
USCITY_HOME = """<!DOCTYPE html>
<html lang="en">
<head><title>City of Good Example</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
<h1>City of Good Example</h1>
<h2>Latest news</h2>
<img src="hall.jpg" alt="Good Example city hall">
<a href="/uscity/accessibility">Accessibility</a>
</body>
</html>
"""
USCITY_ACCESS = """<!DOCTYPE html>
<html lang="en">
<head><title>Accessibility — City of Good Example</title></head>
<body>
<h1>Accessibility</h1>
<p>Our ADA Coordinator is Jordan Lee. Contact the ADA Coordinator
to request an alternate format or to file an accessibility
grievance.</p>
</body>
</html>
"""

# Complete the Filing fixtures: one page whose problems partly get
# fixed between scans (v1 -> v2), used to prove the re-scan comparison.
# v1: no lang, empty title, img without alt  -> LANG + TITLE + IMG-ALT
# v2: lang + title fixed, img untouched      -> IMG-ALT only
IMPROVE_V1 = """<!DOCTYPE html>
<html>
<head><title></title></head>
<body>
<h1>Improve Bakery</h1>
<img src="images/store.jpg">
</body>
</html>
"""
IMPROVE_V2 = """<!DOCTYPE html>
<html lang="en">
<head><title>Improve Bakery</title></head>
<body>
<h1>Improve Bakery</h1>
<img src="images/store.jpg">
</body>
</html>
"""
IMPROVE_EXTRA = """<!DOCTYPE html>
<html lang="en">
<head><title>Extra</title></head>
<body><h1>Extra</h1><a href="/more">click here</a></body>
</html>
"""

FIXTURES = {
    "/bad/": BAD_HOME,
    "/bad/contact": BAD_CONTACT,
    "/improve/": IMPROVE_V1,
    "/good/": GOOD_HOME,
    "/good/contact": GOOD_CONTACT,
    "/good/privacy": GOOD_PRIVACY,
    "/fr/good/": GOOD_FR_HOME,
    "/fr/good/contact": GOOD_FR_CONTACT,
    "/fr/good/privacy": GOOD_FR_PRIVACY,
    "/mid/": MID_HOME,
    "/mid/privacy": MID_PRIVACY,
    "/fr/mid/": MID_FR_HOME,
    "/tracked/": TRACKED_HOME,
    "/consented/": CONSENTED_HOME,
    "/usgov/": USGOV_HOME,
    "/usgov/services": USGOV_SERVICES,
    "/uscity/": USCITY_HOME,
    "/uscity/accessibility": USCITY_ACCESS,
    # deliberately absent (404): /fr/bad/*, /fr/mid/privacy
}


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body_text = nc.DEMO_SITE_HTML if self.path == "/" \
            else FIXTURES.get(self.path)
        if body_text is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = body_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def fixture_pages(*paths):
    return [{"url": FIX + p, "html": FIXTURES[p]} for p in paths]


# ---------------------------------------------------------------------------
# Fabricated DNS answers for the Email Authentication Check.
# Shape: {name: {"answers": [TXT, ...]} | {"error": true}} — a name
# absent from the table answers with no records. The engine tests use
# it through a fake resolver; the app subprocess reads the same table
# from a JSON file named by NORTHCHECK_DNS_FIXTURE. Fully offline.
# ---------------------------------------------------------------------------

DNS_TABLE = {
    # Fully protected: SPF -all (1 lookup via include), DMARC
    # p=reject with rua, DKIM key on selector1.
    "protected.example": {"answers": [
        "v=spf1 include:_spf.google.com -all"]},
    "_spf.google.com": {"answers": [
        "v=spf1 ip4=209.85.220.0/24 ~all"]},
    "_dmarc.protected.example": {"answers": [
        "v=DMARC1; p=reject; rua=mailto:dmarc@protected.example"]},
    "selector1._domainkey.protected.example": {"answers": [
        "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC"]},
    # Partial: SPF +all, DMARC p=none with no rua, no DKIM anywhere.
    "partial.example": {"answers": ["v=spf1 +all"]},
    "_dmarc.partial.example": {"answers": ["v=DMARC1; p=none"]},
    # Invalid: two SPF records at one domain.
    "multi.example": {"answers": [
        "v=spf1 include:sendgrid.example -all", "v=spf1 -all"]},
    # Over the limit: 11 include mechanisms, nothing nested.
    "loopy.example": {"answers": [
        "v=spf1 " + " ".join(f"include:i{n}.example"
                              for n in range(1, 12)) + " -all"]},
    # bare.example is deliberately absent everywhere: no records.
}
for _name in (["fail.example", "_dmarc.fail.example"]
              + [f"{s}._domainkey.fail.example"
                 for s in nc.DKIM_COMMON_SELECTORS]):
    DNS_TABLE[_name] = {"error": True}


def fixture_resolver(name):
    entry = DNS_TABLE.get(name)
    if entry is None:
        return []
    if entry.get("error"):
        raise nc.DnsLookupError(f"fixture failure for {name}")
    return list(entry.get("answers", []))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.status, r.read().decode("utf-8", "replace")


def post(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def last_scan_record():
    import json as _json
    with open(os.path.join(DATA_DIR, "scans.json"),
              encoding="utf-8") as fh:
        return _json.load(fh)[-1]


def last_checklist_record():
    import json as _json
    with open(os.path.join(DATA_DIR, "checklists.json"),
              encoding="utf-8") as fh:
        return _json.load(fh)[-1]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def engine_baseline_checks():
    print("Engine baseline (Phase 1 regression)")
    f, _ = nc.run_aoda_checks(nc.DEMO_SITE_HTML)
    check("demo AODA findings == 10", len(f) == 10, f"got {len(f)}")
    c = nc.count_by_severity(f)
    check("demo AODA severity split 6/3/1/0",
          (c["high"], c["medium"], c["low"], c["info"]) == (6, 3, 1, 0),
          str(c))
    f2, _ = nc.run_postcheck(nc.DEMO_POSTING_TXT)
    check("demo PostCheck findings == 4", len(f2) == 4, f"got {len(f2)}")
    pack = nc.render_evidence_pack("AODA web accessibility scan",
                                   [("Module", "AODA")], f)
    check("markdown evidence pack carries DRAFT stamp",
          nc.DRAFT_STAMP in pack)
    check("markdown evidence pack carries honesty note",
          "issue to review" in pack)


def engine_loi25_checks():
    print("Engine — Loi25 Kit")
    bad = fixture_pages("/bad/", "/bad/contact")
    f, _ = nc.run_loi25_checks(bad)
    check("bad site Loi25 findings == 3", len(f) == 3,
          f"got {[(x['rule_id']) for x in f]}")
    check("bad site Loi25 rules are PRIVACY-LINK/OFFICER/COOKIE",
          {x["rule_id"] for x in f} == {"LOI25-PRIVACY-LINK",
                                        "LOI25-OFFICER",
                                        "LOI25-COOKIE"},
          str({x["rule_id"] for x in f}))
    good = fixture_pages("/good/", "/good/privacy", "/good/contact",
                         "/fr/good/", "/fr/good/contact",
                         "/fr/good/privacy")
    f, _ = nc.run_loi25_checks(good)
    check("good site Loi25 findings == 0", len(f) == 0,
          f"got {[(x['rule_id']) for x in f]}")
    mid = fixture_pages("/mid/", "/mid/privacy", "/fr/mid/")
    f, _ = nc.run_loi25_checks(mid)
    check("mid site Loi25 findings == 1 (POLICY-FRENCH)",
          len(f) == 1 and f[0]["rule_id"] == "LOI25-POLICY-FRENCH",
          f"got {[(x['rule_id']) for x in f]}")
    bad_f, _ = nc.run_loi25_checks(bad)
    pack = nc.render_evidence_pack("Loi25 Kit", [("Module", "Loi25")],
                                   bad_f)
    check("Loi25 pack carries DRAFT stamp + honesty note",
          nc.DRAFT_STAMP in pack and "issue to review" in pack)


def engine_francais_checks():
    print("Engine — Français Check")
    bad = fixture_pages("/bad/", "/bad/contact")
    attempts_bad = [
        {"role": "home", "url": FIX + "/fr/bad/", "ok": False,
         "lang": None, "error": "HTTP 404"},
        {"role": "contact", "url": FIX + "/fr/bad/contact", "ok": False,
         "lang": None, "error": "HTTP 404"},
    ]
    f, _ = nc.run_francais_checks(bad, attempts_bad)
    check("bad site Français findings == 4 (ENTRY/HREFLANG/HOME/CONTACT)",
          len(f) == 4 and {x["rule_id"] for x in f} ==
          {"FR-ENTRY", "FR-HREFLANG", "FR-HOME", "FR-CONTACT"},
          f"got {[(x['rule_id']) for x in f]}")
    good = fixture_pages("/good/", "/good/privacy", "/good/contact",
                         "/fr/good/", "/fr/good/contact",
                         "/fr/good/privacy")
    attempts_good = [
        {"role": r, "url": FIX + u, "ok": True, "lang": "fr",
         "error": None}
        for r, u in (("home", "/fr/good/"), ("contact", "/fr/good/contact"),
                     ("privacy", "/fr/good/privacy"))]
    f, _ = nc.run_francais_checks(good, attempts_good)
    check("good site Français findings == 0", len(f) == 0,
          f"got {[(x['rule_id']) for x in f]}")
    mid = fixture_pages("/mid/", "/mid/privacy", "/fr/mid/")
    attempts_mid = [
        {"role": "home", "url": FIX + "/fr/mid/", "ok": True,
         "lang": "fr", "error": None},
        {"role": "privacy", "url": FIX + "/fr/mid/privacy", "ok": False,
         "lang": None, "error": "HTTP 404"},
    ]
    f, _ = nc.run_francais_checks(mid, attempts_mid)
    check("mid site Français findings == 1 (FR-PRIVACY)",
          len(f) == 1 and f[0]["rule_id"] == "FR-PRIVACY",
          f"got {[(x['rule_id']) for x in f]}")
    check("french_variant_url prefixes /fr and is idempotent",
          nc.french_variant_url("http://x/contact") == "http://x/fr/contact"
          and nc.french_variant_url("http://x/") == "http://x/fr/"
          and nc.french_variant_url("http://x/fr/contact")
          == "http://x/fr/contact")
    attempts_en = [
        {"role": "home", "url": FIX + "/fr/good/", "ok": True,
         "lang": "en", "error": None}]
    f, _ = nc.run_francais_checks(good, attempts_en)
    check("resolved-but-English French home flags FR-HOME-LANG",
          any(x["rule_id"] == "FR-HOME-LANG" for x in f),
          f"got {[(x['rule_id']) for x in f]}")


def _pages(url, html_text):
    findings, _ = nc.run_aoda_checks(html_text)
    return [{"url": url, "findings": findings}]


def engine_filing_checks():
    print("Engine — AODA Complete the Filing (comparison + checklist)")
    prev = _pages(FIX + "/improve/", IMPROVE_V1) \
        + _pages(FIX + "/improve/extra", IMPROVE_EXTRA)
    curr = _pages(FIX + "/improve/", IMPROVE_V2)
    comp = nc.compare_scan_pages(prev, curr)
    c = comp["counts"]
    check("comparison: 2 resolved (LANG + TITLE)",
          c["resolved"] == 2
          and {e["finding"]["rule_id"] for e in comp["resolved"]}
          == {"AODA-LANG", "AODA-TITLE"}, str(c))
    check("comparison: 1 still open (IMG-ALT)",
          c["still_open"] == 1
          and comp["still_open"][0]["finding"]["rule_id"]
          == "AODA-IMG-ALT", str(c))
    check("comparison: 0 new", c["new"] == 0, str(c))
    check("comparison: dropped page's finding is not_rechecked, "
          "not resolved",
          c["not_rechecked"] == 1
          and comp["not_rechecked"][0]["finding"]["rule_id"]
          == "AODA-LINK-GENERIC", str(c))

    two_imgs = ('<html lang="en"><head><title>T</title></head><body>'
                '<img src="a.jpg"><img src="b.jpg"></body></html>')
    one_img = ('<html lang="en"><head><title>T</title></head><body>'
               '<img src="a.jpg"></body></html>')
    comp = nc.compare_scan_pages(_pages(FIX + "/m/", two_imgs),
                                 _pages(FIX + "/m/", one_img))
    c = comp["counts"]
    check("comparison counts duplicates with multiplicity "
          "(2 -> 1 = 1 resolved, 1 still open)",
          c["resolved"] == 1 and c["still_open"] == 1
          and c["new"] == 0, str(c))

    comp = nc.compare_scan_pages(curr, prev)
    c = comp["counts"]
    check("comparison reversed: regressed items come back as new "
          "(LANG + TITLE + the extra page's LINK-GENERIC)",
          c["new"] == 3 and c["resolved"] == 0
          and c["still_open"] == 1, str(c))

    answers = {"GEN-POLICY": "compliant", "GEN-PLAN": "in_progress",
               "CS-DISRUPTION": "not_started",
               "TRANS-FEATURES": "not_applicable"}
    summary = nc.checklist_summary(answers)
    t = summary["totals"]
    total_items = sum(len(s["items"]) for s in nc.FILING_CHECKLIST)
    check("checklist summary totals match the checklist size",
          t["total"] == total_items
          and t["compliant"] == 1 and t["in_progress"] == 1
          and t["not_started"] == 1 and t["not_applicable"] == 1
          and t["unanswered"] == total_items - 4, str(t))
    check("checklist covers the six IASR areas from the research",
          [s["standard"] for s in nc.FILING_CHECKLIST][0]
          == "General requirements"
          and any(s["standard"].startswith("Customer Service")
                  for s in nc.FILING_CHECKLIST)
          and any(s["standard"].startswith("Employment")
                  for s in nc.FILING_CHECKLIST)
          and any(s["standard"].startswith("Transportation")
                  for s in nc.FILING_CHECKLIST)
          and any(s["standard"].startswith("Design of Public")
                  for s in nc.FILING_CHECKLIST),
          str([s["standard"] for s in nc.FILING_CHECKLIST]))
    gaps = nc.filing_gaps(answers, comparison=nc.compare_scan_pages(
        prev, curr))
    check("filing gaps mention still-open website findings and "
          "owner-stated checklist gaps",
          any("still open" in g for g in gaps)
          and any("owner stated" in g for g in gaps), str(gaps))
    check("certification note names senior officer + Ontario portal "
          "+ not verified",
          "senior officer" in nc.FILING_CERTIFICATION_NOTE
          and "Ontario" in nc.FILING_CERTIFICATION_NOTE
          and "has not verified" in nc.FILING_CERTIFICATION_NOTE)


def engine_emailauth_checks():
    print("Engine — Email Authentication Check (mocked DNS)")
    f, s = nc.run_emailauth_checks("protected.example",
                                   resolver=fixture_resolver)
    check("protected domain: 0 findings", len(f) == 0,
          f"got {[(x['rule_id']) for x in f]}")
    check("protected domain: DKIM found on selector1",
          [d["selector"] for d in s["dkim_found"]] == ["selector1"],
          str(s["dkim_found"]))
    check("protected domain: SPF chain counted at 1 lookup, complete",
          s["spf_dns_lookups"] == 1 and s["spf_lookup_complete"],
          str(s["spf_dns_lookups"]))
    check("protected domain: DMARC policy read as reject",
          s["dmarc_policy"] == "reject", str(s["dmarc_policy"]))

    f, s = nc.run_emailauth_checks("bare.example",
                                   resolver=fixture_resolver)
    by_rule = {x["rule_id"]: x["severity"] for x in f}
    check("bare domain: SPF/DMARC missing (high) + DKIM not found "
          "(medium), nothing else",
          by_rule == {"EMAIL-SPF-MISSING": "high",
                      "EMAIL-DMARC-MISSING": "high",
                      "EMAIL-DKIM-NOTFOUND": "medium"}, str(by_rule))
    dkim_f = next(x for x in f if x["rule_id"] == "EMAIL-DKIM-NOTFOUND")
    check("DKIM not-found finding carries the honesty wording",
          "may still exist under a different selector name"
          in dkim_f["explanation"])

    f, s = nc.run_emailauth_checks("partial.example",
                                   resolver=fixture_resolver)
    by_rule = {x["rule_id"]: x["severity"] for x in f}
    check("partial domain: +all high, p=none medium, no-rua low, "
          "DKIM not found medium",
          by_rule == {"EMAIL-SPF-PASSALL": "high",
                      "EMAIL-DMARC-MONITORING": "medium",
                      "EMAIL-DMARC-NOREPORTING": "low",
                      "EMAIL-DKIM-NOTFOUND": "medium"}, str(by_rule))

    f, _s = nc.run_emailauth_checks("multi.example",
                                    resolver=fixture_resolver)
    check("two SPF records flag EMAIL-SPF-MULTIPLE (high)",
          any(x["rule_id"] == "EMAIL-SPF-MULTIPLE"
              and x["severity"] == "high" for x in f),
          str([x["rule_id"] for x in f]))
    f, s = nc.run_emailauth_checks("loopy.example",
                                   resolver=fixture_resolver)
    check("11-include SPF flags EMAIL-SPF-LOOKUPS with count 11",
          any(x["rule_id"] == "EMAIL-SPF-LOOKUPS" for x in f)
          and s["spf_dns_lookups"] == 11,
          f"count {s['spf_dns_lookups']}, "
          f"rules {[x['rule_id'] for x in f]}")

    def boom(_name):
        raise nc.DnsLookupError("resolver down")

    f, s = nc.run_emailauth_checks("fail.example", resolver=boom)
    check("resolver failure: resolution_failed, no findings invented",
          s["resolution_failed"] is True and f == [],
          f"failed={s['resolution_failed']} findings={len(f)}")
    check("normalize_domain reduces a URL to the bare domain",
          nc.normalize_domain("https://Example.COM/some/path")
          == "example.com")


def engine_trackers_checks():
    print("Engine — Tracker and Consent Check (fixture pages)")
    tracked = fixture_pages("/tracked/")
    f, s = nc.run_trackers_checks(tracked)
    by_rule = {x["rule_id"]: x["severity"] for x in f}
    check("tracked site: no-consent high + no-consent-mode medium, "
          "nothing else",
          by_rule == {"TRACK-NO-CONSENT": "high",
                      "TRACK-NO-CONSENT-MODE": "medium"}, str(by_rule))
    check("tracked site: GA and Meta Pixel named, in signature order",
          s["trackers_found"] == ["Google Analytics",
                                  "Meta (Facebook) Pixel"],
          str(s["trackers_found"]))
    check("tracked site: no consent mechanism, Google tags flagged",
          s["consent_mechanism_found"] is False
          and s["google_tags_found"] is True
          and s["consent_mode_found"] is False, str(s))
    noconsent = next(x for x in f
                     if x["rule_id"] == "TRACK-NO-CONSENT")
    check("no-consent finding carries the honesty wording (does not "
          "prove firing order)",
          "does not prove the tags fire before consent"
          in noconsent["explanation"])
    check("tracker findings are stored under module trackers",
          all(x["module"] == "trackers" for x in f))

    consented = fixture_pages("/consented/")
    f, s = nc.run_trackers_checks(consented)
    by_rule = {x["rule_id"]: x["severity"] for x in f}
    check("consented site: consent-unverified info only",
          by_rule == {"TRACK-CONSENT-UNVERIFIED": "info"},
          str(by_rule))
    check("consented site: Cookiebot platform named, Consent Mode "
          "found with the default call",
          s["consent_platforms"] == ["Cookiebot"]
          and s["consent_mode_found"] is True
          and s["consent_mode_calls"] == ["default"], str(s))
    unverified = f[0]
    check("consent-unverified finding states presence is not proof "
          "of blocking",
          "does not prove the tags wait for consent"
          in unverified["explanation"])

    good = fixture_pages("/good/", "/good/privacy", "/good/contact")
    f, s = nc.run_trackers_checks(good)
    by_rule = {x["rule_id"]: x["severity"] for x in f}
    check("good site: clean info result only (TRACK-NONE-FOUND)",
          by_rule == {"TRACK-NONE-FOUND": "info"}, str(by_rule))
    check("good site: tracker count 0 across the scanned pages",
          s["tracker_count"] == 0 and s["pages_scanned"] == 3,
          str(s["tracker_count"]))


def engine_ada_checks():
    print("Engine — ADA Title II Check (fixture pages)")
    gov = fixture_pages("/usgov/", "/usgov/services")
    f, s = nc.run_ada_checks(gov)
    check("usgov site ADA findings == 10", len(f) == 10,
          f"got {[(x['rule_id']) for x in f]}")
    check("usgov ADA rules are the expected 10",
          {x["rule_id"] for x in f} ==
          {"ADA-LANG", "ADA-TITLE", "ADA-IMG-ALT", "ADA-LABEL",
           "ADA-HEADING-ORDER", "ADA-IFRAME-TITLE", "ADA-VIEWPORT",
           "ADA-INPUT-PURPOSE", "ADA-STATEMENT", "ADA-PDF-UNCHECKED"},
          str({x["rule_id"] for x in f}))
    by_rule = {x["rule_id"]: x["severity"] for x in f}
    check("usgov ADA severity split: carried highs stay high, "
          "ADA-only checks are medium/low/info",
          by_rule["ADA-LANG"] == "high"
          and by_rule["ADA-IMG-ALT"] == "high"
          and by_rule["ADA-IFRAME-TITLE"] == "medium"
          and by_rule["ADA-INPUT-PURPOSE"] == "medium"
          and by_rule["ADA-STATEMENT"] == "low"
          and by_rule["ADA-PDF-UNCHECKED"] == "info", str(by_rule))
    check("ADA findings are stamped module ada and name WCAG 2.1, "
          "never WCAG 2.0",
          all(x["module"] == "ada" for x in f)
          and all("WCAG 2.0" not in x["category"]
                  and "WCAG 2.0" not in x["explanation"]
                  for x in f))
    check("ADA carried findings name the page in their evidence",
          all(x["evidence"].startswith(FIX) for x in f
              if x["rule_id"] not in ("ADA-STATEMENT",
                                      "ADA-PDF-UNCHECKED")))
    check("ADA stats: 2 pages scanned, 1 with findings, no "
          "statement, 1 PDF linked",
          s["pages_scanned"] == 2 and s["pages_with_findings"] == 1
          and s["statement_found"] is False and s["pdf_links"] == 1,
          str(s))
    stmt = next(x for x in f if x["rule_id"] == "ADA-STATEMENT")
    check("ADA-STATEMENT is an issue to review, not a determination",
          "not a determination" in stmt["explanation"])
    city = fixture_pages("/uscity/", "/uscity/accessibility")
    f, s = nc.run_ada_checks(city)
    check("uscity site ADA findings == 0 (statement found via its "
          "accessibility page)", len(f) == 0 and s["statement_found"],
          f"got {[(x['rule_id']) for x in f]}")
    f, _ = nc.run_ada_checks(gov)
    pack = nc.render_evidence_pack("ADA Title II Check",
                                   [("Module", "ADA Title II")], f)
    check("ADA pack carries DRAFT stamp + honesty note",
          nc.DRAFT_STAMP in pack and "issue to review" in pack)


def app_baseline_checks():
    print("App baseline (pre-existing pages and flows)")
    s, body = get("/")
    check("landing 200", s == 200)
    check("landing shows AODA FileReady live", "AODA FileReady" in body)
    check("landing shows PostCheck live", "PostCheck ON" in body)
    check("landing carries honesty line", "does not certify" in body)
    s, body = get("/scan")
    check("/scan 200 with form", s == 200 and 'name="url"' in body)
    s, body = get("/postcheck")
    check("/postcheck 200 with form",
          s == 200 and 'name="posting_text"' in body)
    s, body = get("/vault")
    check("/vault 200", s == 200)
    s, body = post("/scan", {"url": FIX + "/"})
    check("AODA scan of demo page: 10 issues in total",
          s == 200 and "10 issues to review in total" in body)
    rec = last_scan_record()
    s, body = get(f"/pack/{rec['id']}")
    check("AODA evidence pack download 200 with DRAFT stamp",
          s == 200 and "DRAFT" in body and "not legal advice" in body)
    s, body = post("/postcheck", {
        "title": "Warehouse Operations Supervisor",
        "employer": "Lakeside Logistics Inc.",
        "date_posted": "2026-11-07",
        "posting_text": nc.DEMO_POSTING_TXT})
    check("PostCheck flow 200", s == 200)
    check("PostCheck shows notify-by 2026-12-22", "2026-12-22" in body)
    check("PostCheck shows retention 2029-11-07", "2029-11-07" in body)


def app_new_module_checks():
    print("App — Loi25 Kit + Français Check")
    s, body = get("/")
    check("landing shows Loi25 as Module 3 live",
          "Loi25 Kit" in body and "Module 3 — live" in body)
    check("landing shows Français Check as Module 4 live",
          "Français Check" in body and "Module 4 — live" in body)
    check("landing has no Coming soon badge left",
          "Coming soon" not in body)
    check("landing shows Loi25 founding price $39/month per site",
          "$39/month</strong> per site" in body)
    check("landing presents Français Check as included",
          "Included</strong> with a scan or monitoring plan" in body)
    s, body = get("/loi25")
    check("/loi25 200 with form", s == 200 and 'name="url"' in body)
    s, body = get("/francais")
    check("/francais 200 with form", s == 200 and 'name="url"' in body)

    s, body = post("/loi25", {"url": FIX + "/bad/"})
    check("Loi25 scan of bad site: 3 issues in total",
          s == 200 and "3 issues to review in total" in body,
          f"status {s}")
    rec = last_scan_record()
    check("Loi25 scan stored as module loi25",
          rec.get("module") == "loi25")
    s, body = get(f"/pack/{rec['id']}")
    check("Loi25 evidence pack 200 with stamp and honesty line",
          s == 200 and "DRAFT" in body and "Loi25 Kit" in body
          and "does not certify compliance" in body)
    s, body = post("/loi25", {"url": FIX + "/good/"})
    check("Loi25 scan of good site: 0 issues in total",
          s == 200 and "0 issues to review in total" in body)
    s, body = post("/loi25", {"url": "example.com"})
    check("Loi25 scan rejects a URL without scheme (400)", s == 400)

    s, body = post("/francais", {"url": FIX + "/bad/"})
    check("Français scan of bad site: 4 issues in total",
          s == 200 and "4 issues to review in total" in body,
          f"status {s}")
    rec = last_scan_record()
    check("Français scan stored as module francais",
          rec.get("module") == "francais")
    s, body = get(f"/pack/{rec['id']}")
    check("Français evidence pack 200 with stamp and module label",
          s == 200 and "DRAFT" in body and "Français Check" in body
          and "does not certify compliance" in body)
    s, body = post("/francais", {"url": FIX + "/good/"})
    check("Français scan of good site: 0 issues in total",
          s == 200 and "0 issues to review in total" in body)
    s, body = post("/francais", {"url": FIX + "/mid/"})
    check("Français scan of mid site: 1 issue in total",
          s == 200 and "1 issues to review in total" in body)


def app_filing_checks():
    print("App — AODA Complete the Filing")
    s, body = get("/")
    check("landing presents Complete Filing Pack at $249 founding",
          s == 200 and "Complete the Filing Pack" in body
          and "Founding price: $249" in body)
    s, body = get("/filing")
    check("/filing 200 with checklist form",
          s == 200 and 'name="org_name"' in body
          and 'name="item_GEN-POLICY"' in body
          and "own statements" in body)

    # First scan of the improving site: 3 findings, no comparison yet.
    s, body = post("/scan", {"url": FIX + "/improve/"})
    check("improve v1 scan: 3 issues in total, no tracker card",
          s == 200 and "3 issues to review in total" in body
          and "Remediation tracker" not in body, f"status {s}")
    rec = last_scan_record()
    check("improve v1 record has no comparison",
          "comparison" not in rec)

    # The site fixes lang + title; the img finding must stay open.
    FIXTURES["/improve/"] = IMPROVE_V2
    try:
        s, body = post("/scan", {"url": FIX + "/improve/"})
        check("improve v2 scan: 1 issue in total with tracker card",
              s == 200 and "1 issues to review in total" in body
              and "Remediation tracker" in body, f"status {s}")
        check("results page shows 2 verified resolved by re-scan",
              "2 verified resolved by re-scan" in body)
        check("results page shows still open / new counts",
              "1 still open" in body and "0 new" in body)
        check("results page keeps resolved distinct from say-so",
              "not verification" in body)
        rec = last_scan_record()
        comp = rec.get("comparison", {})
        check("stored comparison counts resolved 2 / open 1 / new 0",
              comp.get("counts", {}).get("resolved") == 2
              and comp.get("counts", {}).get("still_open") == 1
              and comp.get("counts", {}).get("new") == 0,
              str(comp.get("counts")))
    finally:
        FIXTURES["/improve/"] = IMPROVE_V1

    # Checklist flow end to end.
    s, body = post("/filing", {
        "org_name": "Improve Bakery Inc.",
        "website": FIX + "/improve/",
        "item_GEN-POLICY": "compliant",
        "item_GEN-PLAN": "in_progress",
        "item_CS-DISRUPTION": "not_started",
        "item_TRANS-FEATURES": "not_applicable"})
    check("checklist POST lands on the Filing Pack view",
          s == 200 and "Filing Pack — Improve Bakery Inc." in body,
          f"status {s}")
    check("view page carries the certification note",
          "certified by a senior officer" in body
          and "does not file the report" in body)
    rec = last_checklist_record()
    check("checklist stored with 4 owner answers",
          len(rec.get("answers", {})) == 4, str(rec.get("answers")))

    s, body = get(f"/filing/pack/{rec['id']}")
    check("Filing Pack 200 with DRAFT stamp",
          s == 200 and "DRAFT" in body and "not legal advice" in body)
    check("Filing Pack includes the website findings",
          "AODA-IMG-ALT" in body and "Website findings" in body)
    check("Filing Pack labels checklist answers owner stated",
          "Compliant (owner stated)" in body
          and "has not verified them" in body)
    check("Filing Pack carries the certification note + gaps",
          "must be certified by a senior officer" in body
          and "Remaining gaps" in body)

    s, body = get(f"/filing/statement/{rec['id']}")
    check("accessibility statement 200 with org name",
          s == 200 and "Accessibility Statement" in body
          and "Improve Bakery Inc." in body)
    check("statement carries the feedback placeholder, marked",
          "[FEEDBACK CONTACT — TO BE COMPLETED BY THE ORGANIZATION"
          in body and "placeholder" in body)
    check("statement reflects the real scan (1 issue to review)",
          "found 1 issue(s)" in body)

    s, body = post("/filing", {"org_name": "X", "website": "nope"})
    check("checklist POST rejects a URL without scheme (400)",
          s == 400)


def app_emailauth_checks():
    print("App — Email Authentication Check")
    s, body = get("/")
    check("landing shows Email Authentication Check as Module 5 live",
          "Email Authentication Check" in body
          and "Module 5 — live" in body)
    check("landing presents it as a free check with TenantCheck "
          "cross-reference",
          "Free check" in body and "tenantcheck365.ca" in body)
    s, body = get("/emailauth")
    check("/emailauth 200 with domain form",
          s == 200 and 'name="domain"' in body)

    s, body = post("/emailauth", {"domain": "protected.example"})
    check("protected domain flow: 0 issues in total",
          s == 200 and "0 issues to review in total" in body,
          f"status {s}")
    check("protected results show the records found + cross-reference",
          "selector1" in body and "p=reject" in body
          and "TenantCheck 365" in body)
    rec = last_scan_record()
    check("emailauth scan stored as module emailauth",
          rec.get("module") == "emailauth")
    s, body = get(f"/pack/{rec['id']}")
    check("emailauth evidence pack 200 with DRAFT stamp, module "
          "label and record evidence",
          s == 200 and "DRAFT" in body
          and "Email Authentication Check" in body
          and "v=DMARC1; p=reject" in body
          and "public DNS records showed" in body)

    s, body = post("/emailauth", {"domain": "bare.example"})
    check("bare domain flow: 3 issues in total",
          s == 200 and "3 issues to review in total" in body,
          f"status {s}")
    check("bare results carry the DKIM honesty wording",
          "may still exist under a different selector name" in body)
    s, body = post("/emailauth", {"domain": "partial.example"})
    check("partial domain flow: 4 issues in total, +all shown as "
          "evidence",
          s == 200 and "4 issues to review in total" in body
          and "v=spf1 +all" in body, f"status {s}")
    s, body = post("/emailauth", {"domain": "fail.example"})
    check("resolver failure flow: honest could-not-complete page, "
          "no findings claimed",
          s == 200 and "Check could not be completed" in body
          and "issues to review in total" not in body,
          f"status {s}")
    s, body = post("/emailauth", {"domain": "not a domain"})
    check("emailauth rejects a non-domain (400)", s == 400)


def app_trackers_checks():
    print("App — Tracker and Consent Check")
    s, body = get("/")
    check("landing shows Tracker and Consent Check as Module 6 live",
          "Tracker and Consent Check" in body
          and "Module 6 — live" in body)
    check("landing presents it as a free check linking /trackers",
          "Free check" in body and 'href="/trackers"' in body)
    check("landing carries no payment link for the tracker check",
          body.count("buy.stripe.com") == 4,
          f"count {body.count('buy.stripe.com')}")
    s, body = get("/trackers")
    check("/trackers 200 with form", s == 200 and 'name="url"' in body)
    check("/trackers form states the served-HTML honesty limit",
          "never a claim about when" in body and "tag fires" in body)

    s, body = post("/trackers", {"url": FIX + "/tracked/"})
    check("tracked scan: 2 issues in total",
          s == 200 and "2 issues to review in total" in body,
          f"status {s}")
    check("tracked results name the trackers and signatures",
          "Google Analytics" in body and "Meta (Facebook) Pixel"
          in body and "connect.facebook.net" in body)
    check("tracked results carry the module stamp",
          "cannot show when a tag actually" in body)
    rec = last_scan_record()
    check("trackers scan stored as module trackers",
          rec.get("module") == "trackers")
    s, body = get(f"/pack/{rec['id']}")
    check("trackers evidence pack 200 with DRAFT stamp and module "
          "label",
          s == 200 and "DRAFT" in body
          and "Tracker and Consent Check" in body
          and "does not certify compliance" in body)

    s, body = post("/trackers", {"url": FIX + "/consented/"})
    check("consented scan: 1 issue in total (info)",
          s == 200 and "1 issues to review in total" in body,
          f"status {s}")
    check("consented results name the Cookiebot platform",
          "Cookiebot" in body)
    s, body = post("/trackers", {"url": FIX + "/good/"})
    check("good scan: 1 issue in total (clean info result)",
          s == 200 and "1 issues to review in total" in body,
          f"status {s}")
    s, body = post("/trackers", {"url": "example.com"})
    check("trackers scan rejects a URL without scheme (400)",
          s == 400)


def app_ada_checks():
    print("App — ADA Title II Check")
    s, body = get("/")
    check("landing shows ADA Title II Check as Module 7 live",
          "ADA Title II Check" in body and "Module 7 — live" in body)
    check("landing states both Title II deadlines under the "
          "current DOJ rule",
          "April 26, 2027" in body and "April 26, 2028" in body
          and "current DOJ rule" in body)
    check("landing presents ADA as a free check with no payment "
          "link for it (Stripe link count unchanged at 4)",
          'href="/ada"' in body and body.count("buy.stripe.com") == 4,
          f"count {body.count('buy.stripe.com')}")
    s, body = get("/ada")
    check("/ada 200 with form", s == 200 and 'name="url"' in body)
    check("/ada form states the deadlines with the current-rule "
          "care wording",
          "April 26, 2027" in body and "current DOJ rule" in body)
    check("seo: /ada canonical is /ada on the production domain",
          '<link rel="canonical" href="https://getnorthcheck.ca'
          '/ada">' in body)

    s, body = post("/ada", {"url": FIX + "/usgov/"})
    check("ADA scan of usgov site: 10 issues in total",
          s == 200 and "10 issues to review in total" in body,
          f"status {s}")
    check("ADA results carry the deadline care wording (Interim "
          "Final Rule + not legal advice)",
          "Interim Final Rule" in body and "not legal advice" in body)
    check("ADA results show the unchecked PDF count",
          "PDF documents linked (not checked)" in body)
    rec = last_scan_record()
    check("ADA scan stored as module ada", rec.get("module") == "ada")
    s, body = get(f"/pack/{rec['id']}")
    check("ADA evidence pack 200 with DRAFT stamp, module label "
          "and deadline rows",
          s == 200 and "DRAFT" in body and "ADA Title II Check" in body
          and "April 26, 2027" in body
          and "does not certify compliance" in body)
    s, body = post("/ada", {"url": FIX + "/uscity/"})
    check("ADA scan of uscity site: 0 issues in total",
          s == 200 and "0 issues to review in total" in body)
    s, body = post("/ada", {"url": "example.com"})
    check("ADA scan rejects a URL without scheme (400)", s == 400)


def _meta_description(body):
    import re as _re
    m = _re.search(r'<meta name="description" content="([^"]*)"',
                   body)
    return m.group(1) if m else None


def _json_ld_types(body):
    import re as _re
    types = []
    for raw in _re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            body, _re.S):
        try:
            types.append(_json_mod.loads(raw).get("@type"))
        except ValueError:
            types.append(None)
    return types


def app_seo_checks():
    print("\n== SEO: metadata, sitemap, robots, AODA report page ==")
    s, body = get("/")
    check("seo: homepage carries a meta description",
          bool(_meta_description(body)))
    check("seo: homepage carries og:title",
          'property="og:title"' in body)
    check("seo: homepage carries the google-site-verification "
          "meta",
          '<meta name="google-site-verification" '
          'content="GP0cHkACrflT-3zNe7A33me-mfctb1OgeCyK7ZlHNfo">'
          in body)
    check("seo: homepage carries the msvalidate.01 meta",
          '<meta name="msvalidate.01" '
          'content="5A6E6E3DD0931B9DB02307A62305125F">' in body)
    check("seo: homepage canonical is the production root",
          '<link rel="canonical" href="https://getnorthcheck.ca/">'
          in body)
    check("seo: homepage JSON-LD parses (Organization + FAQPage)",
          _json_ld_types(body) == ["Organization", "FAQPage"],
          f"types {_json_ld_types(body)}")
    check("seo: homepage links the AODA report landing page",
          'href="/aoda-compliance-report"' in body)
    home_desc = _meta_description(body)
    s, scan = get("/scan")
    check("seo: scan page description differs from the homepage's",
          bool(_meta_description(scan))
          and _meta_description(scan) != home_desc)
    check("seo: scan canonical is /scan on the production domain",
          '<link rel="canonical" href="https://getnorthcheck.ca'
          '/scan">' in scan)
    s, sm = get("/sitemap.xml")
    expected = ["/", "/aoda-compliance-report", "/scan", "/filing",
                "/loi25", "/francais", "/emailauth", "/trackers",
                "/ada", "/postcheck", "/vault"]
    check("seo: sitemap 200 listing exactly the public pages",
          s == 200
          and all(f"<loc>https://getnorthcheck.ca{p}</loc>" in sm
                  for p in expected)
          and sm.count("<url>") == len(expected)
          and "/pack/" not in sm and "/filing/view/" not in sm,
          f"status {s}")
    s, rb = get("/robots.txt")
    check("seo: robots 200 referencing the sitemap",
          s == 200
          and "Sitemap: https://getnorthcheck.ca/sitemap.xml" in rb)
    s, body = get("/aoda-compliance-report")
    check("aoda report page 200", s == 200)
    check("aoda report page states the December 31, 2026 deadline",
          "December 31, 2026" in body)
    check("aoda report page states who must file (20 or more "
          "employees)", "20 or more employees" in body)
    check("aoda report page carries the does-not-file honesty "
          "wording",
          "does not file the report" in body
          and "does not certify" in body)
    check("aoda report page names both pack prices ($149 / $249)",
          "$149" in body and "$249" in body)


def main():
    backup_dir = DATA_DIR + ".check-backup"
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    if os.path.exists(DATA_DIR):
        shutil.copytree(DATA_DIR, backup_dir)
    fix = ThreadingHTTPServer(("127.0.0.1", FIX_PORT), FixtureHandler)
    threading.Thread(target=fix.serve_forever, daemon=True).start()
    dns_fixture = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="northcheck-dns-",
        delete=False)
    _json_mod.dump(DNS_TABLE, dns_fixture)
    dns_fixture.close()
    env = dict(os.environ, PORT=str(APP_PORT), HOST="127.0.0.1",
               NORTHCHECK_DNS_FIXTURE=dns_fixture.name)
    app = subprocess.Popen([sys.executable, "app.py"], cwd=APP_DIR,
                           env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                get("/")
                break
            except Exception:
                time.sleep(0.2)
        engine_baseline_checks()
        engine_loi25_checks()
        engine_francais_checks()
        engine_filing_checks()
        engine_emailauth_checks()
        engine_trackers_checks()
        engine_ada_checks()
        app_baseline_checks()
        app_new_module_checks()
        app_filing_checks()
        app_emailauth_checks()
        app_trackers_checks()
        app_ada_checks()
        app_seo_checks()
    finally:
        app.terminate()
        fix.shutdown()
        os.unlink(dns_fixture.name)
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        if os.path.exists(backup_dir):
            shutil.move(backup_dir, DATA_DIR)
        else:
            os.makedirs(DATA_DIR, exist_ok=True)
    print(f"\nTOTAL: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
