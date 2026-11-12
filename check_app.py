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

The app's data/ directory is backed up first and restored afterwards,
so founding signups, scans and vault entries from real use are never
touched by the test run.
"""

import os
import shutil
import subprocess
import sys
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


def main():
    backup_dir = DATA_DIR + ".check-backup"
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    if os.path.exists(DATA_DIR):
        shutil.copytree(DATA_DIR, backup_dir)
    fix = ThreadingHTTPServer(("127.0.0.1", FIX_PORT), FixtureHandler)
    threading.Thread(target=fix.serve_forever, daemon=True).start()
    env = dict(os.environ, PORT=str(APP_PORT), HOST="127.0.0.1")
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
        app_baseline_checks()
        app_new_module_checks()
        app_filing_checks()
    finally:
        app.terminate()
        fix.shutdown()
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        if os.path.exists(backup_dir):
            shutil.move(backup_dir, DATA_DIR)
        else:
            os.makedirs(DATA_DIR, exist_ok=True)
    print(f"\nTOTAL: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
