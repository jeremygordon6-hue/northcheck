# NorthCheck — production web app

NorthCheck is a Canadian SMB compliance platform. One engine —
input → deterministic rule checks → plain-English findings → dated
evidence pack → deadline clocks — with modules switched on per rule
book. This build ships four scanner modules (AODA FileReady,
PostCheck ON, Loi25 Kit, and Français Check) plus the **AODA
Complete the Filing** expansion on top of the AODA scan: a
remediation tracker with re-scan verification, an owner-answered
checklist for the non-website accessibility standards, a combined
Filing Pack, and an accessibility statement generator.

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

The **only** future paid-adjacent piece is **payment processing** (a
processor such as Stripe) when charging starts — it is explicitly
**not** included in this build. No payments are collected anywhere in
this app.

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
  certify WCAG 2.0 Level AA websites) front and centre; all four
  modules shown live; founding prices (AODA evidence pack **$149**,
  monitoring **$39/month**; Complete the Filing Pack **$249**
  founding; PostCheck **$49/month**; Loi25 Kit
  **$39/month** per site; Français Check included with a scan or
  monitoring plan); and a founding-list email capture (email +
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
  the landing page at a **$249 founding price** (a hypothesis, not a
  validated price); interest routes to the free scan and the founding
  list — no payment links.
- **PostCheck (`/postcheck`)** — title, employer, date posted, and the
  pasted posting text are checked against Ontario's Jan 1, 2026 rules
  (O. Reg. 476/24): compensation presence, the $50,000 range-width cap
  with the over-$200,000 exemption, AI screening disclosure, vacancy
  statement, and the prohibited Canadian-experience requirement. The
  results show findings plus the engine's corrected-draft suggestions.
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
  AODA scan's pages, pack format, and DRAFT / honesty stamp. No
  payment links yet — interest routes to the check itself and the
  founding list.
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

**74 / 74 end-to-end checks passed** on 2026-11-11 (the pre-existing
suite was 44/44 before the Complete the Filing build; all 44 still
pass): the Phase 1 engine regression counts (demo AODA 10 findings,
demo PostCheck 4), every pre-existing page and flow, the Loi25 engine
on three fabricated fixture sites (bad 3 findings / good 0 / mid 1),
the Français engine (bad 4 / good 0 / mid 1, plus the
resolved-but-English case), both modules' forms, scan flows, stored
records, and evidence packs — plus 30 Complete the Filing checks:
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
- Storage is local JSON files — fine for founding-cohort volume, not
  a multi-tenant database. No user accounts yet.

## Gating note

Jeremy stated on 2026-11-07 that the Scotiabank policies are cleared,
so selling is unblocked. This build still includes **no payment
collection** — charging starts only when a payment processor is added
deliberately (see `DEPLOY.md`).
