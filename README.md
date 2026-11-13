# NorthCheck — production web app

NorthCheck is a Canadian SMB compliance platform. One engine —
input → deterministic rule checks → plain-English findings → dated
evidence pack → deadline clocks — with modules switched on per rule
book. This build ships five scanner modules (AODA FileReady,
PostCheck ON, Loi25 Kit, Français Check, and Email Authentication
Check) plus the **AODA Complete the Filing** expansion on top of the
AODA scan: a remediation tracker with re-scan verification, an
owner-answered checklist for the non-website accessibility
standards, a combined Filing Pack, and an accessibility statement
generator.

**Honesty rule (product requirement):** NorthCheck prepares evidence.
It does not certify compliance and is not legal advice. Every finding
is an *issue to review*; the signing officer / owner makes the call.
Every results page and every evidence pack carries that stamp.

## Free-tools inventory

This build uses **free / open-source tools only**:

| Piece | Tool | Cost |
|---|---|---|
| Language + runtime | Python 3 (PSF licence) | Free |
| Web server | `http.server` from the Python standard library | Free |
| HTML parsing / checks | `northcheck.py` — the Phase 1 engine, Python stdlib only (`html.parser`, `re`, `urllib`, `json`, `datetime`) | Free, built in-house |
| Pages | Server-rendered HTML with inline CSS — no JavaScript frameworks, no external CDNs, no npm packages, no paid APIs, no paid services | Free |
| Storage | JSON files under `data/` (created at runtime) | Free |
| Process | `bash run.sh` | Free |

Card data is not collected in this app. Checkout is a Stripe Payment
Link that opens in the buyer's browser. Checkout is open for the AODA
evidence pack (**$149 CAD**), AODA monitoring (**$39 CAD/month**), the
Complete Filing Pack (**$249 CAD**), and PostCheck ON (**$49
CAD/month**). The Loi25 Kit check is live; its paid plan (**$39
CAD/month** per site) has no payment link and stays on the founding
list.

## Run it

```bash
bash run.sh
```

Serves on `http://127.0.0.1:8790` by default (binds localhost only).
Override with `PORT=9000 bash run.sh` or `HOST=0.0.0.0` where a
deployment platform requires it — see `DEPLOY.md`.

## Features

- **Landing page (`/`)** — the Ontario AODA filing deadline
  (**December 31, 2026** for employers with 20+ staff; 50+ must also
  certify WCAG 2.0 Level AA websites) front and centre; all five
  modules shown live, because each checker route works; founding
  prices in **CAD** (AODA evidence pack **$149 CAD**, monitoring
  **$39 CAD/month**, Complete the Filing Pack **$249 CAD**, PostCheck
  **$49 CAD/month** — checkout open for these four; Loi25 Kit **$39
  CAD/month** per site, check live, paid plan on the founding list;
  Français Check included with a scan or monitoring plan; Email
  Authentication Check a free check, no standalone price set); and a
  founding-list email capture for the Loi25 paid plan only (email +
  timestamp stored to `data/founding.json`; **no email is sent**).
- **AODA scan (`/scan`)** — enter an http/https URL; the crawler
  follows same-domain links breadth-first up to **10 pages**, skips
  non-HTML responses, then runs the engine's deterministic WCAG 2.0
  checks per page. Results group findings by severity with rule id,
  plain-English explanation, the exact evidence snippet, and a
  suggested fix. Each scan is stored in `data/scans.json` and offers a
  **downloadable evidence pack**: one self-contained HTML file stamped
  with the DRAFT / not-legal-advice header.
- **AODA Complete the Filing (`/filing`)** — the December 31, 2026
  compliance report covers all parts of the Integrated Accessibility
  Standards Regulation (General requirements, Information and
  Communications, Employment, Transportation where applicable,
  Design of Public Spaces, Customer Service) and must be certified by
  a senior officer; the scan alone evidences only the web part.
  Three pieces: (1) **Remediation tracker** — when a site is scanned
  again, the results page compares against the previous scan for that
  site (findings verified resolved / still open / new / on pages not
  re-crawled). A finding counts as resolved *only* when the re-scan
  no longer reports it; there is deliberately no "mark as fixed"
  button, so an owner's say-so is never presented as verification.
  (2) **Checklist** — 25 owner-answered statements across the six
  standards areas (`compliant / in progress / not started / not
  applicable`), stored in `data/checklists.json`. Answers are the
  organization's own statements and are labelled "owner stated"
  everywhere — NorthCheck never verifies them. (3) **Filing Pack +
  accessibility statement** — one dated HTML pack combining the
  website findings with their status, the checklist answers by
  standard, the remaining gaps, and a prominent certification note
  (the report is filed by the organization on the Ontario government
  portal and certified by a senior officer; NorthCheck prepares
  evidence, it does not file or certify); and a publish-ready
  accessibility statement generated only from the recorded scan and
  checklist, with bracketed placeholders for anything only the
  organization can supply (e.g. the feedback contact). Presented on
  the landing page at a **$249 CAD founding price** (a hypothesis, not a
  validated price). Checkout for that pack is open. The scan and the
  checklist stay available without paying.
- **PostCheck (`/postcheck`)** — title, employer, date posted, and the
  pasted posting text are checked against Ontario's Jan 1, 2026 rules
  (O. Reg. 476/24): compensation presence, the $50,000 range-width cap
  with the over-$200,000 exemption, AI screening disclosure, vacancy
  statement, and the prohibited Canadian-experience requirement. The
  results show findings plus the engine's corrected-draft suggestions.
  Checkout for the module is open at **$49 CAD/month**.
- **Loi25 Kit (`/loi25`)** — enter a URL; the same crawler fetches up
  to 10 same-domain pages, then the engine checks what a public
  website can honestly show for Quebec's Law 25: a privacy policy
  linked from the homepage (`LOI25-PRIVACY-LINK`), a named privacy
  officer or privacy contact on the scanned pages (`LOI25-OFFICER`),
  a cookie consent mechanism visible in the served HTML
  (`LOI25-COOKIE`), and a French version of the privacy policy
  reachable from the policy page (`LOI25-POLICY-FRENCH`; an info
  finding records when the policy page itself fell outside the
  crawl). Results and a downloadable HTML evidence pack reuse the
  AODA scan's pages, pack format, and DRAFT / honesty stamp. The check
  is live. The paid plan (**$39 CAD/month** per site) has no payment
  link; that offer stays on the founding list.
- **Français Check (`/francais`)** — enter a URL; after the crawl,
  the app tries the conventional French counterparts (`/fr/…`) of
  the home, contact, and privacy pages. The engine checks for a
  French entry point from the homepage (`FR-ENTRY`), hreflang
  declarations (`FR-HREFLANG`), and that each French counterpart
  resolves (`FR-HOME` / `FR-CONTACT` / `FR-PRIVACY`) and declares
  French (`FR-*-LANG`). Existence and reachability only — translation
  quality is never assessed. Results list every French address tried;
  the evidence pack matches the other modules.
- **Vault (`/vault`)** — "Save to vault" stores a checked posting in
  `data/vault.json` with its clocks computed by the engine:
  **notify-by = date posted + 45 days** and **retention-until = date
  posted + 3 years**. The vault page lists every saved posting with
  days remaining until notify-by (overdue dates flagged).
- **Email Authentication Check (`/emailauth`)** — enter a domain;
  the engine checks its public email authentication DNS records and
  builds the same dated evidence pack. **SPF** (TXT at the domain):
  missing record, multiple records, `+all` pass-everyone, no `all`
  mechanism, `~all` softfail / `?all` neutral, unrecognized terms,
  and a lookup count (includes/redirects followed through the
  resolver, capped by depth and loop protection) over the RFC 7208
  limit of 10. **DMARC** (TXT at `_dmarc.<domain>`): missing,
  multiple, no/invalid policy, `p=none` monitor-only, `p=quarantine`
  and partial `pct=` as info, missing `rua` reporting address,
  strict alignment noted as info; `p=reject` is the pass state and
  appears in the "What was checked" table. **DKIM**: selectors
  cannot be enumerated from DNS, so the check tries a documented
  list of common selectors (`default, google, selector1, selector2,
  k1, k2, s1, s2, mail, dkim, mandrill, smtp`) at
  `<selector>._domainkey.<domain>`; found selectors are listed with
  their record text, an empty `p=` is flagged as a revoked key, and
  when none resolve the finding states plainly that no record was
  found *on the selectors checked* and DKIM may still exist under a
  different selector name — it never claims DKIM is absent.
  Resolution is DNS-over-HTTPS JSON (`https://dns.google/resolve`,
  overridable with `NORTHCHECK_DOH_URL`) behind an injectable
  resolver callable (`run_emailauth_checks(domain, resolver=…)`);
  the test suite injects fabricated answers via a
  `NORTHCHECK_DNS_FIXTURE` JSON file and runs fully offline. If the
  SPF and DMARC lookups both fail, the module reports "check could
  not be completed" and invents no findings. Free check, presented
  as included with monitoring plans; **no standalone price has been
  set** — the module copy cross-references TenantCheck 365 for the
  Microsoft 365 tenant side.

## The engine

`northcheck.py` in this folder is a copy of the verified Phase 1
engine from `../northcheck/`, so the app is self-contained. The app
imports and reuses its functions (`run_aoda_checks`, `run_postcheck`,
`corrected_draft_suggestions`, `notify_by`, `retention_until`, the
findings model and severity ordering) rather than re-implementing any
check. Regression fixtures live in `../northcheck/` (`demo_site.html`,
`demo_posting.txt`): the app's scan of the demo page produces the same
**10 findings** and its postcheck of the demo posting the same
**4 findings** as the engine CLI — verified end-to-end on 2026-11-07
(43/43 checks, including vault clocks 2026-12-22 / 2029-11-07 for a
2026-11-07 posting).

## Verification

```bash
python3 check_app.py
```

**97 / 97 end-to-end checks passed** on 2026-11-11 (74/74 before the
Email Authentication build; all 74 still pass): the Phase 1 engine
regression counts (demo AODA 10 findings, demo PostCheck 4), every
pre-existing page and flow, the Loi25 engine on three fabricated
fixture sites (bad 3 findings / good 0 / mid 1), the Français engine
(bad 4 / good 0 / mid 1, plus the resolved-but-English case), both
modules' forms, scan flows, stored records, and evidence packs —
plus 23 Email Authentication checks: fabricated DNS domains for the
fully protected case (SPF `-all`, DMARC `p=reject` with rua, DKIM
on selector1 → 0 findings, chain counted at 1 lookup), the
unprotected case (SPF/DMARC missing, DKIM not found with the
honesty wording), the partial case (`+all`, `p=none`, no rua),
multiple-SPF and 11-include over-limit records, the
resolver-failure path (no findings invented), and the full
`/emailauth` HTTP flow and evidence pack — plus 30 Complete the
Filing checks:
re-scan comparison correctness (improving fixture site: 2 resolved /
1 still open / 0 new; a page dropped from the crawl counts as
not-rechecked, never resolved; duplicate findings counted with
multiplicity), the checklist flow end to end, Filing Pack contents
(website findings, owner-stated labels, certification note, gaps),
and statement generation with marked placeholders. The checker backs
up and restores `data/`, so test entries never reach the real stores.
(The pre-build baseline, run with a temporary harness covering the
same pre-existing surface, was 20/20; the README's older 43/43 figure
was verified on 2026-11-07 but that suite was not saved in this
folder.)

## Limitations (stated plainly)

- **Crawl cap:** single-domain, breadth-first, **10 pages** maximum,
  8-second timeout per page, ~2 MB per page. No JavaScript rendering —
  pages are checked as served HTML, so content injected by client-side
  scripts is not seen.
- **Loi25 checks see only the public website.** A consent banner
  loaded entirely by JavaScript may not be visible in the served
  HTML (the finding says so and prompts a browser check), and Law 25
  duties with no website trace — incident register, privacy impact
  assessments, internal governance — are out of scope by design.
- **Français Check guesses the conventional `/fr/` address** for each
  key page. A French version living on a subdomain or another path
  will be reported as not resolving unless the homepage's own French
  link leads the crawl to it; translation quality is not assessed.
- **Checks are deterministic and phrase-based.** The AI-disclosure
  check matches disclosure phrasing patterns; compensation parsing
  reads explicit `$` amounts (including `$85k` style) only.
- **Findings are issues to review, not verdicts.** An empty findings
  list is not a guarantee of compliance, and a finding is not a
  determination of non-compliance.
- **Checklist answers are owner-stated, never verified.** The
  Complete the Filing checklist records what the organization says
  about its own non-website practices. Nothing in the app checks
  those answers against reality; they are labelled as the
  organization's own statements in the UI, the Filing Pack, and the
  generated statement.
- **Re-scan comparison keys on the scan's start address and on each
  finding's rule + evidence text.** Scanning the same site from a
  different start address starts a fresh history, and a fix that
  changes a finding's evidence snippet without removing the
  underlying problem pattern can read as one resolved plus one new
  finding rather than one still open.
- **Email Authentication Check sees DNS only, as served by the
  resolver at scan time.** The SPF lookup count counts mechanism
  terms (each `a`/`mx` counts once even though a real evaluation
  may look further) and follows includes only while the resolver
  answers, so it can be a floor — the results page marks it as such.
  DKIM coverage is limited to the common selector list by design
  (see above); a provider signing under a custom selector will read
  as "not found on the selectors checked." The check says nothing
  about whether mail actually aligns in practice — that evidence
  lives in DMARC aggregate reports, which this module does not read.
- Storage is local JSON files — fine for founding-cohort volume, not
  a multi-tenant database. No user accounts yet.

## Gating note

Jeremy stated on 2026-11-07 that the Scotiabank policies are cleared,
so selling is unblocked. Checkout is the Stripe Payment Links in
`app.py` for the AODA evidence pack, AODA monitoring, the Complete
Filing Pack, and PostCheck ON. The app stores no card data. The Loi25
paid plan remains founding-list only.
