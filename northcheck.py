#!/usr/bin/env python3
"""
NorthCheck — Phase 1 prototype: a combined Canadian SMB compliance platform.

One shared engine, multiple compliance modules:

    input -> deterministic rule checks -> plain-English findings
          -> dated evidence pack -> deadline clocks / monitoring

Phase 1 builds two modules on that engine, and the web app adds two
site-level modules that reuse the same findings model, evidence pack
renderer and honesty stamp (run_loi25_checks / run_francais_checks,
driven by the app's crawler):

  * loi25     : Loi25 Kit — Quebec Law 25 evidence a public website can
                honestly show (privacy policy linked from the homepage,
                named privacy officer, cookie consent, French policy).
  * francais  : Français Check — a real French version exists and its
                key pages (home, contact, privacy) resolve in French.
  * emailauth : Email Authentication Check — DMARC / SPF / DKIM from
                public DNS only (run_emailauth_checks over an
                injectable DNS-over-HTTPS resolver). DKIM selectors
                cannot be enumerated, so a documented common-selector
                list is checked and a not-found result never claims
                DKIM is absent.
  * trackers  : Tracker and Consent Check — known tracker / ad-tag
                signatures, consent-platform signatures and Google
                Consent Mode signals matched against the HTML exactly
                as served (run_trackers_checks over the crawled
                pages). No JavaScript is run, so the check reports
                what is present in the page source and never claims
                to prove when a tag fires in a real browser.
  * ada       : ADA Title II Check — US state and local government
                websites against WCAG 2.1 Level AA (run_ada_checks
                over the crawled pages): the AODA page checks
                re-issued under the WCAG 2.1 criteria they carry
                into unchanged, plus iframe titles, zoom-blocking
                viewports, WCAG 2.1's own input-purpose criterion,
                a published accessibility statement / ADA contact,
                and PDF documents named as not checked. Deadline
                dates are stated as "under the current DOJ rule"
                (see ADA_DEADLINE_* below).
  * filing    : AODA Complete the Filing — re-scan comparison
                (compare_scan_pages: a finding counts as resolved only
                when a later scan no longer reports it), an
                owner-answered checklist for the non-website IASR
                standards (FILING_CHECKLIST — answers are the
                organization's own statements, never verified), and the
                summary/gap helpers the Filing Pack is built from. The
                compliance report itself is filed by the organization
                on the Ontario portal and certified by a senior
                officer; NorthCheck prepares evidence only.

The original two CLI modules:

  * scan      : AODA web-accessibility scan (module "AODA FileReady").
                Input is a local HTML file or a URL. Applies deterministic
                HTML checks, each mapped to a WCAG 2.0 category in plain
                English, and writes a dated markdown evidence pack.
  * postcheck : Ontario job-posting check (module "PostCheck ON").
                Input is a job-posting text file. Applies deterministic
                checks against Ontario's Jan 1, 2026 posting rules
                (O. Reg. 476/24), writes a report with corrected-draft
                suggestions, and --save appends the posting to vault.json
                with its 45-day and 3-year clocks computed.
  * gen-demos : writes the FABRICATED demo inputs (demo_site.html and
                demo_posting.txt) with deliberate, documented problems
                baked in, used to verify the checkers.

Single file, standard library only (no installs needed).

Honesty rule (product requirement): findings are ISSUES TO REVIEW.
NorthCheck prepares evidence; it does not certify compliance, and nothing
it emits is legal advice. Every evidence pack carries that stamp. The
signing officer / owner makes the compliance call — never this tool.
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Shared engine — findings model
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

DRAFT_STAMP = (
    "DRAFT — prepared for the signing officer's / owner's review. "
    "This tool prepares evidence; it does not certify compliance and is "
    "not legal advice."
)

HONESTY_NOTE = (
    "Every item above is an **issue to review**, found by deterministic "
    "checks against the stated rules. A finding means the check matched "
    "something worth a human look — it is not a determination that the "
    "target is compliant or non-compliant, and an empty findings list "
    "would not be a guarantee of compliance either. The signing officer "
    "/ owner reviews the evidence and makes the call."
)


def make_finding(module, rule_id, severity, category, explanation,
                 evidence, fix):
    """One finding in the shared model used by every module."""
    return {
        "module": module,
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "explanation": explanation,
        "evidence": evidence,
        "fix": fix,
    }


def count_by_severity(findings):
    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


def severity_summary_line(findings):
    counts = count_by_severity(findings)
    parts = [f"{sev} {counts[sev]}" for sev in
             ("high", "medium", "low", "info")]
    return (f"{len(findings)} issues to review "
            f"({', '.join(parts)})")


def sort_findings(findings):
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f["severity"]],
                                           f["rule_id"], f["evidence"]))


def render_evidence_pack(module_label, meta_pairs, findings,
                         extra_sections=""):
    """Render the dated markdown evidence pack shared by all modules.

    meta_pairs: list of (key, value) shown as the target metadata block.
    extra_sections: optional markdown appended after the findings
    (e.g. posting clocks, corrected-draft suggestions).
    """
    counts = count_by_severity(findings)
    lines = []
    lines.append(f"# NorthCheck Evidence Pack — {module_label}")
    lines.append("")
    lines.append(f"**{DRAFT_STAMP}**")
    lines.append("")
    for key, value in meta_pairs:
        lines.append(f"- **{key}:** {value}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total issues to review: **{len(findings)}**")
    lines.append(
        "- By severity: "
        + " · ".join(f"{sev} {counts[sev]}"
                     for sev in ("high", "medium", "low", "info")))
    lines.append("")
    lines.append("## Issues to review")
    lines.append("")
    if not findings:
        lines.append("No issues matched the checks in this run. "
                     "See the honesty note below — this is not a "
                     "certification.")
        lines.append("")
    else:
        current_sev = None
        for f in sort_findings(findings):
            if f["severity"] != current_sev:
                current_sev = f["severity"]
                lines.append(f"### {current_sev.capitalize()}")
                lines.append("")
            lines.append(f"#### {f['rule_id']} — {f['category']}")
            lines.append("")
            lines.append(f"- **What this means:** {f['explanation']}")
            lines.append(f"- **Evidence found:** `{f['evidence']}`")
            lines.append(f"- **Suggested fix:** {f['fix']}")
            lines.append("")
    if extra_sections:
        lines.append(extra_sections.rstrip())
        lines.append("")
    lines.append("## Honesty note")
    lines.append("")
    lines.append(HONESTY_NOTE)
    lines.append("")
    lines.append("---")
    lines.append("Generated by NorthCheck (Phase 1 prototype). "
                 "Prototype only — no customers, no charging.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared engine — deadline clocks
# ---------------------------------------------------------------------------

def add_days(d, n):
    return d + datetime.timedelta(days=n)


def add_years(d, n):
    """Add whole years; Feb 29 lands on Feb 28 in a non-leap target year."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def notify_by(posted):
    """Ontario rule: interviewed applicants told the outcome within 45 days."""
    return add_days(posted, 45)


def retention_until(posted):
    """Ontario rule: posting and associated records kept for 3 years."""
    return add_years(posted, 3)


# ---------------------------------------------------------------------------
# Module AODA — deterministic HTML accessibility checks (WCAG 2.0)
# ---------------------------------------------------------------------------

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

GENERIC_LINK_TEXTS = {"click here", "here", "this link", "link"}


def _norm_text(parts):
    return " ".join("".join(parts).split())


def _snippet(tag, attrs, keys):
    bits = [tag]
    for k in keys:
        if attrs.get(k):
            bits.append(f'{k}="{attrs[k]}"')
    return "<" + " ".join(bits) + ">"


class AodaParser(HTMLParser):
    """Collects everything the AODA checks need in one streaming pass.

    Label/control association is evaluated after the parse, because a
    <label for="..."> can appear after the control it names.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.html_seen = False
        self.html_lang = None
        self.title_seen = False
        self.in_title = False
        self.title_parts = []
        self.images = []      # {src, alt_present, alt}
        self.controls = []    # {tag, type, id, name, aria_label,
                              #  aria_labelledby, wrapped, attrs}
        self.label_fors = set()
        self.headings = []    # heading levels in document order
        self.id_counts = {}
        self.links = []       # evaluated {href, text, aria, title_attr}
        self.buttons = []     # evaluated {text, aria, snippet}
        self._anchors = []    # open anchor contexts
        self._buttons = []    # open button contexts

    # -- streaming handlers ------------------------------------------------

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        el_id = a.get("id")
        if el_id:
            self.id_counts[el_id] = self.id_counts.get(el_id, 0) + 1

        if tag == "html":
            self.html_seen = True
            self.html_lang = a.get("lang")
        elif tag == "title":
            self.title_seen = True
            self.in_title = True
        elif tag == "label":
            if a.get("for"):
                self.label_fors.add(a["for"])
        elif tag == "img":
            self.images.append({
                "src": a.get("src"),
                "alt_present": "alt" in a,
                "alt": a.get("alt"),
            })
            if self._anchors and a.get("alt"):
                self._anchors[-1]["parts"].append(a["alt"])
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(tag[1]))
        elif tag == "a":
            self._anchors.append({
                "href": a.get("href"),
                "aria": a.get("aria-label"),
                "title_attr": a.get("title"),
                "parts": [],
            })
        elif tag == "button":
            self._buttons.append({
                "aria": a.get("aria-label"),
                "parts": [],
                "snippet": _snippet("button", a, ("type", "class", "id")),
            })
        elif tag in ("input", "select", "textarea"):
            self.controls.append({
                "tag": tag,
                "type": (a.get("type") or "text") if tag == "input" else tag,
                "id": a.get("id"),
                "name": a.get("name"),
                "aria_label": a.get("aria-label"),
                "aria_labelledby": a.get("aria-labelledby"),
                "wrapped": "label" in self.stack,
                "value": a.get("value"),
                "attrs": a,
            })

        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "a" and self._anchors:
            ctx = self._anchors.pop()
            self.links.append({
                "href": ctx["href"],
                "text": _norm_text(ctx["parts"]),
                "aria": ctx["aria"],
                "title_attr": ctx["title_attr"],
            })
        elif tag == "button" and self._buttons:
            ctx = self._buttons.pop()
            self.buttons.append({
                "text": _norm_text(ctx["parts"]),
                "aria": ctx["aria"],
                "snippet": ctx["snippet"],
            })
        if tag in self.stack:
            while self.stack:
                if self.stack.pop() == tag:
                    break

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self._anchors:
            self._anchors[-1]["parts"].append(data)
        if self._buttons:
            self._buttons[-1]["parts"].append(data)


def run_aoda_checks(html_text):
    """Return (findings, stats) for one HTML document."""
    parser = AodaParser()
    parser.feed(html_text)
    parser.close()
    findings = []
    add = findings.append

    # AODA-LANG — WCAG 2.0 · 3.1.1 Language of Page
    if not parser.html_seen or not (parser.html_lang or "").strip():
        evidence = "<html> (no lang attribute)" if parser.html_seen \
            else "(no <html> tag found)"
        add(make_finding(
            "aoda", "AODA-LANG", "high",
            "WCAG 2.0 · 3.1.1 Language of Page",
            "The page does not declare its language. Screen readers use "
            "the declared language to pronounce words correctly; without "
            "it, the text can be read back with the wrong pronunciation "
            "rules, and a basic WCAG 2.0 item is left unanswered.",
            evidence,
            'Add a lang attribute to the <html> element, e.g. '
            '<html lang="en"> (use lang="fr" for a French page).'))

    # AODA-TITLE — WCAG 2.0 · 2.4.2 Page Titled
    title_text = _norm_text(parser.title_parts)
    if not parser.title_seen or not title_text:
        evidence = "<title></title> (empty)" if parser.title_seen \
            else "(no <title> element found)"
        add(make_finding(
            "aoda", "AODA-TITLE", "high",
            "WCAG 2.0 · 2.4.2 Page Titled",
            "The page has no usable title. The title is the first thing a "
            "screen reader announces and the label browsers show in tabs "
            "and search results; an empty or missing title leaves the "
            "page unidentified.",
            evidence,
            "Give the page a short descriptive <title>, e.g. "
            "<title>Maple Street Bakery — Toronto</title>."))

    # AODA-IMG-ALT — WCAG 2.0 · 1.1.1 Non-text Content
    decorative = 0
    for img in parser.images:
        if not img["alt_present"]:
            src = img["src"] or "(no src)"
            add(make_finding(
                "aoda", "AODA-IMG-ALT", "high",
                "WCAG 2.0 · 1.1.1 Non-text Content",
                "This image has no alt attribute at all, so a screen "
                "reader can only announce the file name or skip it "
                "silently. That is different from a decorative image, "
                "which is marked with an empty alt=\"\" on purpose.",
                f'<img src="{src}">',
                "Add alt text that conveys what the image shows, e.g. "
                'alt="Fresh sourdough loaves on a wooden rack" — or, if '
                'the image is purely decorative, set alt="" so screen '
                "readers skip it deliberately."))
        elif (img["alt"] or "").strip() == "":
            decorative += 1

    # AODA-LABEL — WCAG 2.0 · 1.3.1 / 3.3.2 (labels)
    for c in parser.controls:
        if c["type"] == "hidden":
            continue
        if c["tag"] == "input" and c["type"] in ("submit", "button",
                                                 "reset"):
            continue  # its value attribute is its accessible name
        labelled = (
            c["wrapped"]
            or (c["aria_label"] or "").strip()
            or (c["aria_labelledby"] or "").strip()
            or (c["id"] and c["id"] in parser.label_fors)
        )
        if not labelled:
            add(make_finding(
                "aoda", "AODA-LABEL", "high",
                "WCAG 2.0 · 1.3.1 Info and Relationships / "
                "3.3.2 Labels or Instructions",
                "This form field has no label connected to it in the "
                "code (no <label for>, no wrapping <label>, no "
                "aria-label). Assistive technology cannot announce what "
                "the field is for, and a placeholder alone does not "
                "count as a label.",
                _snippet(c["tag"], c["attrs"],
                         ("type", "id", "name", "placeholder")),
                'Connect a visible label to the field, e.g. '
                '<label for="fullname">Full name</label> paired with '
                'id="fullname", or wrap the field in its <label>.'))

    # AODA-HEADING-ORDER — WCAG 2.0 · 1.3.1 Info and Relationships
    for prev, nxt in zip(parser.headings, parser.headings[1:]):
        if nxt > prev + 1:
            add(make_finding(
                "aoda", "AODA-HEADING-ORDER", "medium",
                "WCAG 2.0 · 1.3.1 Info and Relationships",
                "Heading levels skip here. Screen-reader users navigate "
                "pages by their heading outline; a jump from "
                f"h{prev} to h{nxt} makes the structure look like a "
                "section is missing.",
                f"h{prev} followed by h{nxt}",
                "Renumber the headings so levels increase one step at "
                "a time (h1, then h2, then h3), using CSS — not heading "
                "level — for visual size."))

    # AODA-LINK-* — WCAG 2.0 · 2.4.4 Link Purpose (In Context)
    for link in parser.links:
        href = link["href"] or "(no href)"
        if not link["text"] and not (link["aria"] or "").strip() \
                and not (link["title_attr"] or "").strip():
            add(make_finding(
                "aoda", "AODA-LINK-EMPTY", "medium",
                "WCAG 2.0 · 2.4.4 Link Purpose (In Context)",
                "This link has no text and no accessible name, so a "
                "screen reader announces it as just \"link\" with no "
                "destination, and keyboard users tab onto an invisible "
                "target.",
                f'<a href="{href}"></a>',
                "Put text inside the link that names the destination, "
                "or add an aria-label describing where it goes."))
        elif link["text"].lower().rstrip(".!") in GENERIC_LINK_TEXTS:
            add(make_finding(
                "aoda", "AODA-LINK-GENERIC", "low",
                "WCAG 2.0 · 2.4.4 Link Purpose (In Context)",
                "This link's text is generic (\"click here\" style). "
                "Out of context — for example in a screen reader's list "
                "of all links on the page — it says nothing about where "
                "the link leads.",
                f'<a href="{href}">{link["text"]}</a>',
                "Rewrite the link text to name the destination, e.g. "
                "\"Read our story\" instead of \"click here\"."))

    # AODA-BUTTON-TEXT — WCAG 2.0 · 4.1.2 Name, Role, Value
    for btn in parser.buttons:
        if not btn["text"] and not (btn["aria"] or "").strip():
            add(make_finding(
                "aoda", "AODA-BUTTON-TEXT", "high",
                "WCAG 2.0 · 4.1.2 Name, Role, Value",
                "This button has no visible text and no aria-label, so "
                "it has no accessible name: a screen reader can only "
                "announce \"button\", and voice-control users cannot "
                "target it by name.",
                btn["snippet"],
                "Add visible text to the button, or an aria-label that "
                "states what it does, e.g. aria-label=\"Search\"."))

    # AODA-DUP-ID — WCAG 2.0 · 4.1.1 Parsing
    for el_id, n in sorted(parser.id_counts.items()):
        if n > 1:
            add(make_finding(
                "aoda", "AODA-DUP-ID", "medium",
                "WCAG 2.0 · 4.1.1 Parsing",
                "The same id is used on more than one element. Labels "
                "and ARIA references point at an id, so duplicates make "
                "those references ambiguous and assistive technology "
                "may attach them to the wrong element.",
                f'id="{el_id}" used {n} times',
                "Make every id on the page unique; use a class for "
                "shared styling instead."))

    stats = {
        "images_total": len(parser.images),
        "images_decorative": decorative,
        "controls_total": len(parser.controls),
        "links_total": len(parser.links),
        "headings_total": len(parser.headings),
    }
    return findings, stats


# ---------------------------------------------------------------------------
# Module PostCheck — Ontario job-posting checks (O. Reg. 476/24)
# ---------------------------------------------------------------------------

AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*)(?:\s?([kK]))?")

AI_DISCLOSURE_PATTERNS = [
    r"artificial intelligence",
    r"\bAI\b[^.]{0,80}\b(screen|assess|select|evaluat|rank|shortlist)",
    r"\b(screen|assess|select|evaluat|rank|shortlist)\w*[^.]{0,80}\bAI\b",
    r"automated\s+(tools|systems|screening)[^.]{0,60}"
    r"(screen|assess|select|evaluat)",
]

VACANCY_PATTERNS = [
    r"existing vacancy",
    r"current vacancy",
    r"currently available",
    r"anticipated vacancy",
    r"future vacancy",
    r"vacancy\s+(exists|is available|is anticipated)",
    r"no\s+(current\s+)?vacancy",
]

CANADIAN_EXPERIENCE_PATTERNS = [
    r"canadian\s+(work\s+)?experience",
    r"experience\s+in\s+canada\s+(is\s+)?"
    r"(required|preferred|essential|a\s+must)",
    r"local\s+canadian\s+experience",
]

RANGE_CAP = 50_000
EXEMPTION_TOP = 200_000


def _money(n):
    return f"${n:,}"


def _line_with_match(text, pattern):
    """Return the first line containing a regex match, else None."""
    rx = re.compile(pattern, re.IGNORECASE)
    for line in text.splitlines():
        if rx.search(line):
            return line.strip()
    return None


def _any_match(text, patterns):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def run_postcheck(text):
    """Return (findings, details) for one job-posting text.

    details carries the parsed compensation picture for the report.
    """
    findings = []
    add = findings.append
    details = {}

    # --- compensation ---------------------------------------------------
    amounts = []
    for m in AMOUNT_RE.finditer(text):
        value = int(m.group(1).replace(",", ""))
        if m.group(2):
            value *= 1000
        amounts.append(value)

    if not amounts:
        details["compensation"] = "No dollar amount found in the posting."
        add(make_finding(
            "postcheck", "POST-NO-COMP", "high",
            "O. Reg. 476/24 · compensation information",
            "The posting states no expected compensation at all. "
            "Ontario's posting rules require the expected compensation "
            "(or a range) to appear in every publicly advertised job "
            "posting from a covered employer.",
            "(no dollar amount found in the posting text)",
            "Add the expected compensation, e.g. \"Salary: $70,000 per "
            "year\" or a range no wider than $50,000."))
    elif len(amounts) >= 2:
        lo, hi = min(amounts), max(amounts)
        width = hi - lo
        details["compensation"] = (
            f"Range detected: {_money(lo)} – {_money(hi)} "
            f"(width {_money(width)}).")
        if width > RANGE_CAP and hi > EXEMPTION_TOP:
            add(make_finding(
                "postcheck", "POST-COMP-EXEMPT", "info",
                "O. Reg. 476/24 · compensation range (exemption)",
                "The stated range is wider than the $50,000 cap, but "
                "the top of the range exceeds $200,000, so the range "
                "cap does not apply to this posting (exempt by salary). "
                "Recorded here for the evidence trail; nothing to fix.",
                f"{_money(lo)} – {_money(hi)} (width {_money(width)})",
                "No change needed on range width. Keep this note with "
                "the posting record."))
            details["compensation"] += \
                " Exempt from the range cap (top exceeds $200,000)."
        elif width > RANGE_CAP:
            add(make_finding(
                "postcheck", "POST-RANGE-WIDTH", "high",
                "O. Reg. 476/24 · compensation range",
                f"The stated range is {_money(width)} wide, over the "
                "$50,000 maximum width Ontario allows in a job posting. "
                "The by-salary exemption does not apply because the top "
                f"of the range ({_money(hi)}) does not exceed $200,000.",
                f"{_money(lo)} – {_money(hi)} (width {_money(width)})",
                "Narrow the stated range to a width of $50,000 or "
                f"less, e.g. {_money(lo)} – {_money(lo + RANGE_CAP)}, "
                "or state a single expected salary."))
    else:
        details["compensation"] = (
            f"Single figure detected: {_money(amounts[0])}. "
            "No range-width question arises.")

    # --- AI screening disclosure -----------------------------------------
    if not _any_match(text, AI_DISCLOSURE_PATTERNS):
        add(make_finding(
            "postcheck", "POST-NO-AI", "high",
            "O. Reg. 476/24 · AI screening disclosure",
            "The posting contains no statement disclosing whether "
            "artificial intelligence is used to screen, assess or "
            "select applicants. Ontario's posting rules require that "
            "disclosure in the posting itself.",
            "(no AI disclosure statement found in the posting text)",
            "Add a disclosure line stating whether AI is used, e.g. "
            "\"Artificial intelligence is used to screen applications "
            "for this position.\" — or the equivalent statement that "
            "it is not used, if that is the case."))

    # --- vacancy statement -------------------------------------------------
    if not _any_match(text, VACANCY_PATTERNS):
        add(make_finding(
            "postcheck", "POST-NO-VACANCY", "medium",
            "O. Reg. 476/24 · vacancy statement",
            "The posting does not state whether it is for an existing "
            "vacancy. Ontario's posting rules require that statement, "
            "so candidates know whether a real, currently open "
            "position sits behind the posting.",
            "(no vacancy statement found in the posting text)",
            "Add a line such as \"This posting is for an existing "
            "vacancy.\" — or, if the role is being posted ahead of "
            "need, a statement that it is for an anticipated/future "
            "vacancy."))

    # --- Canadian experience (prohibited) ---------------------------------
    ce_line = None
    for pattern in CANADIAN_EXPERIENCE_PATTERNS:
        ce_line = _line_with_match(text, pattern)
        if ce_line:
            break
    if ce_line:
        add(make_finding(
            "postcheck", "POST-CANADIAN-EXP", "high",
            "O. Reg. 476/24 · Canadian experience (prohibited)",
            "The posting names Canadian experience. Ontario's posting "
            "rules prohibit including a requirement for Canadian "
            "experience in a publicly advertised posting or application "
            "form — stating it as a preference still puts it in the "
            "posting.",
            ce_line,
            "Remove the Canadian-experience line entirely. Assess the "
            "underlying job-related skills directly (licences, "
            "equipment, local regulations knowledge) instead."))

    return findings, details


def corrected_draft_suggestions(findings):
    """Plain-English corrected-draft suggestions for each violation."""
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f["rule_id"], f)
    lines = []
    if "POST-RANGE-WIDTH" in by_rule:
        lines.append("- **Range width:** " +
                     by_rule["POST-RANGE-WIDTH"]["fix"])
    if "POST-NO-COMP" in by_rule:
        lines.append("- **Compensation:** " +
                     by_rule["POST-NO-COMP"]["fix"])
    if "POST-NO-AI" in by_rule:
        lines.append("- **AI disclosure:** " +
                     by_rule["POST-NO-AI"]["fix"])
    if "POST-NO-VACANCY" in by_rule:
        lines.append("- **Vacancy statement:** " +
                     by_rule["POST-NO-VACANCY"]["fix"])
    if "POST-CANADIAN-EXP" in by_rule:
        lines.append("- **Canadian experience:** " +
                     by_rule["POST-CANADIAN-EXP"]["fix"])
    if not lines:
        lines.append("No corrections suggested — no violations matched. "
                     "This is not a certification; see the honesty note.")
    return "\n".join(lines)


def parse_posting_meta(text, title_override=None, employer_override=None):
    title = title_override
    employer = employer_override
    if not title:
        m = re.search(r"(?im)^\s*(?:job title|position|title)\s*:\s*(.+)$",
                      text)
        if m:
            title = m.group(1).strip()
    if not employer:
        m = re.search(r"(?im)^\s*(?:employer|company)\s*:\s*(.+)$", text)
        if m:
            employer = m.group(1).strip()
    if not title:
        for line in text.splitlines():
            if line.strip():
                title = line.strip()
                break
    return title or "Untitled posting", employer or "Not stated"


def vault_save(entry, vault_path):
    data = []
    if os.path.exists(vault_path):
        with open(vault_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    data.append(entry)
    with open(vault_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return len(data)


# ---------------------------------------------------------------------------
# Shared site parser — everything the Loi25 and Français checks need
# ---------------------------------------------------------------------------

class SiteParser(HTMLParser):
    """One streaming pass collecting site-level signals from one page.

    Collects the <html lang>, anchor hrefs with their visible text,
    <link rel="alternate" hreflang="..."> declarations, and the page's
    normalized visible text. Script/style content is excluded from the
    visible text; raw HTML stays available to the caller for marker
    checks (e.g. consent-platform script names).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html_lang = None
        self.links = []        # {href, text}
        self.hreflangs = []    # values of hreflang on <link rel=alternate>
        self.text_parts = []
        self._anchors = []
        self._skip = 0         # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "link":
            if (a.get("rel") or "").lower() == "alternate" \
                    and a.get("hreflang"):
                self.hreflangs.append(a["hreflang"])
        elif tag == "a":
            self._anchors.append({"href": a.get("href"), "parts": []})
        elif tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "a" and self._anchors:
            ctx = self._anchors.pop()
            self.links.append({
                "href": ctx["href"],
                "text": _norm_text(ctx["parts"]),
            })
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._anchors:
            self._anchors[-1]["parts"].append(data)
        if not self._skip:
            self.text_parts.append(data)

    @property
    def text(self):
        return _norm_text(self.text_parts)


def parse_site_page(html_text):
    parser = SiteParser()
    parser.feed(html_text)
    parser.close()
    return parser


PRIVACY_HREF_MARKERS = ("privacy", "confidential", "vie-priv",
                        "vie_privee", "renseignements-personnels")
PRIVACY_TEXT_MARKERS = ("privacy", "confidentialité", "confidentialite",
                        "vie privée", "vie privee")

OFFICER_PATTERNS = [
    r"privacy officer",
    r"chief privacy officer",
    r"privacy contact",
    r"data protection officer",
    r"responsable de la protection des renseignements personnels",
    r"responsable des renseignements personnels",
    r"responsable de la vie privée",
    r"personne responsable[^.]{0,60}renseignements personnels",
]

# Consent language and the script markers of common consent platforms.
# Detection runs over the HTML as served: a banner injected later by
# JavaScript may not be visible to these checks (a stated limitation).
COOKIE_TEXT_PATTERNS = [
    r"cookies?[^.]{0,80}(consent|accept|agree|manage|preference|setting)",
    r"(consent|accept|manage)[^.]{0,40}cookies?",
    r"témoins[^.]{0,80}(consentement|accepter|gérer|préférences)",
    r"(consentement|accepter)[^.]{0,40}témoins",
]
COOKIE_SCRIPT_MARKERS = ("cookiebot", "onetrust", "cookieyes", "didomi",
                         "axeptio", "termly", "osano", "trustarc")


def _find_privacy_links(parser):
    out = []
    for link in parser.links:
        href = (link["href"] or "").lower()
        text = link["text"].lower()
        if any(m in href for m in PRIVACY_HREF_MARKERS) \
                or any(m in text for m in PRIVACY_TEXT_MARKERS):
            out.append(link)
    return out


def _page_role(url):
    path = urllib.parse.urlparse(url).path.lower()
    if any(m in path for m in PRIVACY_HREF_MARKERS):
        return "privacy"
    if "contact" in path:
        return "contact"
    return "page"


# ---------------------------------------------------------------------------
# Module Loi25 Kit — Quebec Law 25 evidence from the public website
# ---------------------------------------------------------------------------
# Only what a public website can honestly show is checked: a privacy
# policy linked from the homepage, a named privacy officer / privacy
# contact published somewhere on the scanned pages, a cookie consent
# mechanism visible in the HTML as served, and a French version of the
# privacy policy being reachable from the policy page. Law 25 duties
# that leave no trace on a public website (incident register, privacy
# impact assessments, internal governance) are out of scope by design
# and are never implied by these findings.

def run_loi25_checks(pages):
    """Return (findings, stats) for a crawled site.

    pages: list of {url, html} in crawl order — pages[0] is the
    homepage the visitor entered.
    """
    findings = []
    add = findings.append
    parsed = [(p["url"], parse_site_page(p["html"]), p["html"])
              for p in pages]
    home_url, home, _home_html = parsed[0]

    # LOI25-PRIVACY-LINK — policy linked from the homepage
    privacy_links = _find_privacy_links(home)
    if not privacy_links:
        add(make_finding(
            "loi25", "LOI25-PRIVACY-LINK", "high",
            "Law 25 · privacy policy published",
            "No privacy policy link could be found on the homepage. "
            "Law 25 expects an organization to publish its governance "
            "policies for personal information, and the published "
            "privacy policy is the piece a visitor (or an assessor) "
            "looks for first. If a policy exists but is not linked "
            "from the homepage, it is effectively unpublished.",
            "(no privacy policy link found on the homepage)",
            "Publish the privacy policy and link it from the homepage "
            "(the footer is the usual place), in the same place on "
            "every page."))
    stats_privacy_pages = [u for u, _p, _h in parsed
                           if _page_role(u) == "privacy"]

    # LOI25-OFFICER — named privacy officer / contact published
    officer_evidence = None
    for _url, parser, _html in parsed:
        for pattern in OFFICER_PATTERNS:
            m = re.search(pattern, parser.text, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 40)
                officer_evidence = parser.text[start:m.end() + 40]
                break
        if officer_evidence:
            break
    if not officer_evidence:
        add(make_finding(
            "loi25", "LOI25-OFFICER", "high",
            "Law 25 · privacy officer identified",
            "None of the scanned pages names a privacy officer or "
            "privacy contact. Under Law 25 the person with the highest "
            "authority is responsible for personal information by "
            "default, and the title and contact details of the person "
            "exercising that function must be published on the "
            "organization's website.",
            "(no privacy officer or privacy contact named on the "
            "scanned pages)",
            "Name the privacy officer (or the person responsible for "
            "personal information) with a contact route and publish it "
            "on the website — the privacy policy page is the usual "
            "place."))

    # LOI25-COOKIE — consent mechanism visible in the served HTML
    cookie_evidence = None
    for _url, parser, html_text in parsed:
        raw = html_text.lower()
        for marker in COOKIE_SCRIPT_MARKERS:
            if marker in raw:
                cookie_evidence = f"consent platform marker: {marker}"
                break
        if cookie_evidence:
            break
        for pattern in COOKIE_TEXT_PATTERNS:
            m = re.search(pattern, parser.text, re.IGNORECASE)
            if m:
                cookie_evidence = m.group(0)
                break
        if cookie_evidence:
            break
    if not cookie_evidence:
        add(make_finding(
            "loi25", "LOI25-COOKIE", "medium",
            "Law 25 · cookie consent",
            "No cookie consent mechanism was visible in the HTML as "
            "served (no consent wording and no known consent-platform "
            "marker). Law 25 consent for cookies that identify, "
            "locate or profile a visitor must be requested expressly. "
            "A consent tool loaded entirely by JavaScript after the "
            "page arrives may not be visible to this check — treat "
            "this as a prompt to verify, in the browser, what a first "
            "time visitor actually sees.",
            "(no cookie consent mechanism detected in the scanned "
            "pages)",
            "Present a consent choice before non-essential cookies "
            "are set, and keep the wording where a visitor (and this "
            "scan) can see it."))

    # LOI25-POLICY-FRENCH — French privacy policy reachable
    policy_french = False
    if privacy_links:
        for url, parser, _html in parsed:
            if _page_role(url) != "privacy":
                continue
            if (parser.html_lang or "").lower().startswith("fr"):
                policy_french = True
            if any((h or "").lower().startswith("fr")
                   for h in parser.hreflangs):
                policy_french = True
            for link in parser.links:
                href = (link["href"] or "").lower()
                text = link["text"].lower()
                if "/fr/" in href or href.rstrip("/").endswith("/fr") \
                        or "français" in text or "francais" in text:
                    policy_french = True
        if stats_privacy_pages and not policy_french:
            add(make_finding(
                "loi25", "LOI25-POLICY-FRENCH", "medium",
                "Law 25 · privacy policy in French",
                "The privacy policy page was scanned, but no French "
                "version of it appears reachable from it (no French "
                "link, no hreflang declaration, and the page itself "
                "is not in French). An organization serving Quebec "
                "customers is expected to make its policy available "
                "in French.",
                stats_privacy_pages[0],
                "Publish the French version of the privacy policy "
                "and link it from the English policy page (and vice "
                "versa), ideally with hreflang declarations."))
        elif not stats_privacy_pages:
            add(make_finding(
                "loi25", "LOI25-POLICY-NOT-SCANNED", "info",
                "Law 25 · privacy policy not in this scan",
                "A privacy policy is linked from the homepage, but "
                "the policy page itself was not among the pages this "
                "scan fetched (the crawl is capped), so its contents "
                "— including whether a French version is offered — "
                "were not reviewed in this run.",
                privacy_links[0]["href"] or "(privacy link)",
                "No fix implied. Run a deeper scan, or check the "
                "policy page directly, before relying on this pack "
                "for the policy's contents."))

    stats = {
        "pages_scanned": len(pages),
        "privacy_link_found": bool(privacy_links),
        "privacy_pages_scanned": len(stats_privacy_pages),
        "officer_found": bool(officer_evidence),
        "cookie_consent_found": bool(cookie_evidence),
        "policy_french_reachable": policy_french,
    }
    return findings, stats


# ---------------------------------------------------------------------------
# Module Français Check — does a real French version exist and resolve?
# ---------------------------------------------------------------------------
# Existence and reachability only: a French entry point on the
# homepage (toggle link or /fr/ path), hreflang declarations, and the
# French counterparts of the key pages (home, contact, privacy when
# the English site has one) actually resolving with French content.
# Translation quality is not assessed and is never implied.

def french_variant_url(url):
    """The conventional French counterpart: /fr prefixed to the path."""
    parts = urllib.parse.urlparse(url)
    path = parts.path or "/"
    if path == "/fr" or path.startswith("/fr/"):
        return url
    new_path = "/fr" + (path if path != "/" else "/")
    return urllib.parse.urlunparse(parts._replace(path=new_path))


def _is_french_link(link):
    href = (link["href"] or "").lower()
    text = link["text"].strip().lower()
    if "/fr/" in href or href.rstrip("/").endswith("/fr") \
            or "://" in href and ".fr" in href.split("/")[2]:
        return True
    return text in ("fr", "français", "francais", "french") \
        or "français" in text


def run_francais_checks(pages, attempts):
    """Return (findings, stats) for a crawled site plus French probes.

    pages: list of {url, html} in crawl order (pages[0] is home).
    attempts: list of {role, url, ok, lang, error} — one entry per key
    page whose French counterpart the app tried to fetch. Roles are
    "home", "contact", "privacy". ok=True means the URL returned an
    HTML page; lang is that page's declared language when known.
    """
    findings = []
    add = findings.append
    home_url = pages[0]["url"]
    home = parse_site_page(pages[0]["html"])
    all_parsed = [(p["url"], parse_site_page(p["html"])) for p in pages]

    # FR-ENTRY — a way into the French site from the homepage
    entry_found = any(_is_french_link(link) for link in home.links) \
        or any((h or "").lower().startswith("fr")
               for h in home.hreflangs)
    if not entry_found:
        add(make_finding(
            "francais", "FR-ENTRY", "high",
            "French version · entry point",
            "The homepage offers no visible way into a French "
            "version: no French language link or toggle, and no "
            "French hreflang declaration. A French site that cannot "
            "be reached from the homepage effectively does not exist "
            "for a French speaking visitor.",
            "(no French link, toggle or hreflang on the homepage)",
            "Add a clearly labelled French link (\"Français\") on the "
            "homepage pointing at the French home page, and keep it "
            "on every page."))

    # FR-HREFLANG — declarations that tie the versions together
    hreflang_fr = any((h or "").lower().startswith("fr")
                      for _u, p in all_parsed for h in p.hreflangs)
    if not hreflang_fr:
        add(make_finding(
            "francais", "FR-HREFLANG", "low",
            "French version · hreflang declarations",
            "No page in this scan declares a French alternate with "
            "hreflang. Search engines use hreflang to send French "
            "speakers to the French page instead of the English one; "
            "without it the versions compete with each other.",
            "(no hreflang=\"fr\" declaration found)",
            "Add <link rel=\"alternate\" hreflang=\"fr\" ...> (and "
            "the matching \"en\") declarations naming each version's "
            "own URL."))

    # FR-<ROLE> — each key page's French counterpart must resolve
    role_labels = {"home": ("FR-HOME", "high"),
                   "contact": ("FR-CONTACT", "medium"),
                   "privacy": ("FR-PRIVACY", "medium")}
    for attempt in attempts:
        role = attempt["role"]
        rule_id, severity = role_labels[role]
        if not attempt["ok"]:
            add(make_finding(
                "francais", rule_id, severity,
                f"French version · {role} page",
                f"The French counterpart of the {role} page did not "
                "resolve as an HTML page in this check "
                f"({attempt.get('error') or 'not fetched'}). Either "
                "the French version of this page does not exist, or "
                "it lives at an address this check did not guess — "
                "the conventional /fr/ address was tried.",
                attempt["url"],
                f"Publish the French {role} page, or point the "
                "language toggle at the address where it actually "
                "lives."))
        elif attempt.get("lang") is not None \
                and not attempt["lang"].lower().startswith("fr"):
            add(make_finding(
                "francais", rule_id + "-LANG", "medium",
                f"French version · {role} page language",
                f"The French address for the {role} page resolves, "
                f"but the page declares lang=\"{attempt['lang']}\" "
                "instead of French. Assistive technology and search "
                "engines will treat it as an English page, which "
                "usually means the English page was copied to the "
                "French address without being declared (or written) "
                "in French.",
                attempt["url"],
                "Declare lang=\"fr\" on the French page and make "
                "sure its content is the French version."))

    stats = {
        "pages_scanned": len(pages),
        "french_entry_found": entry_found,
        "hreflang_fr_found": hreflang_fr,
        "attempts": len(attempts),
        "attempts_ok": sum(1 for a in attempts if a["ok"]),
    }
    return findings, stats


# ---------------------------------------------------------------------------
# Module ADA Title II Check — US state and local government websites
# ---------------------------------------------------------------------------
# The US Department of Justice's ADA Title II web and mobile app rule
# requires state and local government web content to conform to
# WCAG 2.1 Level AA. The compliance dates, as revised by the
# Department's April 2026 Interim Final Rule, are April 26, 2027 for
# public entities serving a population of 50,000 or more and
# April 26, 2028 for smaller public entities and special district
# governments. The 2026 revision is known to this codebase through
# secondary reporting rather than a read of the Federal Register
# text, so every surface that states the dates words them as "under
# the current DOJ rule" and tells the reader to confirm the date
# that applies to their entity.
#
# What the served HTML can honestly show, and what this module
# checks: the per-page criteria the AODA checker already tests are
# WCAG 2.0 Level A/AA criteria carried unchanged into WCAG 2.1 (same
# numbers, same intent), so run_aoda_checks does the detection and
# this module re-issues its findings under ADA rule ids with
# WCAG 2.1 categories and the page URL prefixed to the evidence.
# Added checks cover only what else the markup itself shows: frames
# without titles, a viewport that blocks zoom, WCAG 2.1's own
# Identify Input Purpose criterion (1.3.5 — no WCAG 2.0
# equivalent), whether an accessibility statement / ADA contact is
# published on the scanned pages, and PDF documents, which are web
# content under the rule but cannot be read by an HTML scan and are
# therefore named as not checked. Everything that needs rendering,
# a keyboard, a screen reader or the inside of a document (contrast,
# focus order, motion, app behaviour) is out of scope by design and
# is never implied by these findings.

ADA_DEADLINE_LARGE = "April 26, 2027"   # population 50,000 or more
ADA_DEADLINE_SMALL = "April 26, 2028"   # smaller / special districts

# The AODA rule ids carry into WCAG 2.1 unchanged; only the prefix
# and the standard named in the category change.
_ADA_RULE_IDS = {
    "AODA-LANG": "ADA-LANG",
    "AODA-TITLE": "ADA-TITLE",
    "AODA-IMG-ALT": "ADA-IMG-ALT",
    "AODA-LABEL": "ADA-LABEL",
    "AODA-HEADING-ORDER": "ADA-HEADING-ORDER",
    "AODA-LINK-EMPTY": "ADA-LINK-EMPTY",
    "AODA-LINK-GENERIC": "ADA-LINK-GENERIC",
    "AODA-BUTTON-TEXT": "ADA-BUTTON-TEXT",
    "AODA-DUP-ID": "ADA-DUP-ID",
}

# Field names / ids that say a form control collects the kind of
# personal information WCAG 2.1 · 1.3.5 (Identify Input Purpose)
# covers. Matched as whole tokens against the control's name and id.
_ADA_INPUT_PURPOSE_TOKENS = {
    "email", "phone", "tel", "telephone", "mobile", "name", "fname",
    "lname", "firstname", "lastname", "fullname", "address", "street",
    "city", "state", "province", "zip", "postal", "country",
    "username", "birth", "dob",
}

_ADA_STATEMENT_TEXT_PATTERNS = [
    r"ada coordinator",
    r"accessibility coordinator",
    r"accessibility statement",
    r"section 504 coordinator",
]


class AdaParser(AodaParser):
    """AodaParser plus the collections the ADA checks add: iframes,
    the viewport meta, and a count of links to PDF documents."""

    def __init__(self):
        super().__init__()
        self.iframes = []      # {src, title}
        self.viewport = None   # content of <meta name="viewport">
        self.pdf_links = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "iframe":
            self.iframes.append({"src": a.get("src"),
                                 "title": a.get("title")})
        elif tag == "meta" \
                and (a.get("name") or "").lower() == "viewport":
            self.viewport = a.get("content") or ""
        elif tag == "a":
            href = (a.get("href") or "").split("?")[0].split("#")[0]
            if href.lower().endswith(".pdf"):
                self.pdf_links += 1
        super().handle_starttag(tag, attrs)


def run_ada_checks(pages):
    """Return (findings, stats) for a crawled US public-sector site.

    pages: list of {url, html} in crawl order — pages[0] is the
    homepage the visitor entered.
    """
    findings = []
    add = findings.append
    if not pages:
        return findings, {"pages_scanned": 0, "pages_with_findings": 0,
                          "statement_found": False, "pdf_links": 0}
    statement_found = False
    pdf_links = 0
    pages_with_findings = 0

    for p in pages:
        url = p["url"]
        carried, _aoda_stats = run_aoda_checks(p["html"])
        parser = AdaParser()
        parser.feed(p["html"])
        parser.close()
        extra = []

        for f in carried:
            extra.append(make_finding(
                "ada", _ADA_RULE_IDS[f["rule_id"]], f["severity"],
                f["category"].replace("WCAG 2.0", "WCAG 2.1"),
                f["explanation"].replace("WCAG 2.0", "WCAG 2.1"),
                f"{url} :: {f['evidence']}",
                f["fix"].replace("WCAG 2.0", "WCAG 2.1")))

        # ADA-IFRAME-TITLE — WCAG 2.1 · 4.1.2 Name, Role, Value
        for frame in parser.iframes:
            if not (frame["title"] or "").strip():
                src = frame["src"] or "(no src)"
                extra.append(make_finding(
                    "ada", "ADA-IFRAME-TITLE", "medium",
                    "WCAG 2.1 · 4.1.2 Name, Role, Value",
                    "This embedded frame (a video, map or form pulled "
                    "into the page) has no title. Assistive technology "
                    "announces a frame by its title; without one, a "
                    "screen reader user moving through the page hears "
                    "only \"frame\" and cannot tell what it is or "
                    "decide to skip it.",
                    f'{url} :: <iframe src="{src}">',
                    "Give the frame a short descriptive title, e.g. "
                    "<iframe title=\"City council meeting video\" "
                    "...>."))

        # ADA-VIEWPORT — WCAG 2.1 · 1.4.4 Resize Text
        if parser.viewport:
            squashed = parser.viewport.lower().replace(" ", "")
            blocks_zoom = "user-scalable=no" in squashed
            m = re.search(r"maximum-scale=([0-9.]+)", squashed)
            if m and float(m.group(1)) < 2:
                blocks_zoom = True
            if blocks_zoom:
                extra.append(make_finding(
                    "ada", "ADA-VIEWPORT", "medium",
                    "WCAG 2.1 · 1.4.4 Resize Text",
                    "The page's viewport settings block or cap zoom "
                    "(user-scalable=no, or a maximum scale below "
                    "200%). Residents who enlarge text to read it — "
                    "the readers the resize text criterion exists "
                    "for — are prevented from doing so on phones and "
                    "tablets.",
                    f'{url} :: <meta name="viewport" '
                    f'content="{parser.viewport}">',
                    "Remove user-scalable=no and any maximum-scale "
                    "below 2 from the viewport meta tag, so the page "
                    "can be enlarged to at least 200%."))

        # ADA-INPUT-PURPOSE — WCAG 2.1 · 1.3.5 Identify Input Purpose
        for c in parser.controls:
            if c["type"] == "hidden":
                continue
            if c["tag"] == "input" and c["type"] in (
                    "submit", "button", "reset"):
                continue
            if (c["attrs"].get("autocomplete") or "").strip():
                continue
            tokens = set(re.split(
                r"[^a-z0-9]+",
                ((c["name"] or "") + " " + (c["id"] or "")).lower()))
            if c["type"] in ("email", "tel") \
                    or tokens & _ADA_INPUT_PURPOSE_TOKENS:
                extra.append(make_finding(
                    "ada", "ADA-INPUT-PURPOSE", "medium",
                    "WCAG 2.1 · 1.3.5 Identify Input Purpose",
                    "This field appears to collect personal "
                    "information (its type or name says so) but "
                    "carries no autocomplete attribute. Identify "
                    "Input Purpose is new in WCAG 2.1, with no 2.0 "
                    "equivalent: the field's purpose must be "
                    "available in code so browsers and assistive "
                    "technology can offer the resident's own details "
                    "and present the field in a familiar way.",
                    f"{url} :: " + _snippet(
                        c["tag"], c["attrs"], ("type", "id", "name")),
                    "Add the matching autocomplete token, e.g. "
                    "autocomplete=\"email\" on an email field, "
                    "autocomplete=\"tel\" on a phone field, or "
                    "autocomplete=\"street-address\" on an address "
                    "field."))

        pdf_links += parser.pdf_links
        if extra:
            pages_with_findings += 1
        findings.extend(extra)

        if not statement_found:
            site_page = parse_site_page(p["html"])
            for link in site_page.links:
                if "accessib" in (link["href"] or "").lower():
                    statement_found = True
                    break
            if not statement_found:
                for pattern in _ADA_STATEMENT_TEXT_PATTERNS:
                    if re.search(pattern, site_page.text,
                                 re.IGNORECASE):
                        statement_found = True
                        break

    # ADA-STATEMENT — an accessibility contact published on the site
    if not statement_found:
        add(make_finding(
            "ada", "ADA-STATEMENT", "low",
            "ADA Title II · accessibility contact published",
            "None of the scanned pages publishes an accessibility "
            "statement, names an ADA coordinator, or explains how to "
            "request an alternate format or raise an accessibility "
            "grievance. Title II entities with 50 or more employees "
            "must designate an ADA coordinator and adopt grievance "
            "procedures, and residents look for exactly this page "
            "first when something does not work for them. This is an "
            "issue to review, not a determination that no "
            "coordinator exists — only that none is published where "
            "this scan looked.",
            "(no accessibility statement, ADA coordinator or "
            "grievance route found on the scanned pages)",
            "Publish an accessibility page naming the ADA "
            "coordinator and how to request accessible formats or "
            "report a barrier, and link it from the site footer."))

    # ADA-PDF-UNCHECKED — documents are covered; this scan reads HTML
    if pdf_links:
        add(make_finding(
            "ada", "ADA-PDF-UNCHECKED", "info",
            "ADA Title II · documents not checked",
            f"The scanned pages link to {pdf_links} PDF "
            "document(s). Documents a public entity posts are web "
            "content under the Title II rule, but this scan reads "
            "HTML only and cannot check inside a PDF — its tags, "
            "reading order and image descriptions were not "
            "reviewed.",
            f"{pdf_links} PDF link(s) on the scanned pages",
            "Check posted PDFs with a PDF accessibility checker, "
            "and consider an HTML version for long or frequently "
            "used documents."))

    stats = {
        "pages_scanned": len(pages),
        "pages_with_findings": pages_with_findings,
        "statement_found": statement_found,
        "pdf_links": pdf_links,
    }
    return findings, stats


# ---------------------------------------------------------------------------
# Module Email Authentication Check — DMARC / SPF / DKIM from public DNS
# ---------------------------------------------------------------------------
# Deterministic checks over the domain's public DNS TXT records only:
# the SPF record at the domain, the DMARC record at _dmarc.<domain>,
# and DKIM records under a documented list of common selectors (DKIM
# selectors cannot be enumerated from DNS, so a domain whose DKIM uses
# another selector name will read as "not found on the selectors
# checked" — the finding says exactly that and never claims DKIM is
# absent). Resolution goes through DNS-over-HTTPS JSON (Google) via an
# injectable resolver callable: resolver(name) -> list of TXT record
# strings, raising DnsLookupError when the lookup itself fails. Tests
# pass a fake resolver and run fully offline.

DOH_ENDPOINT = "https://dns.google/resolve"
DNS_TIMEOUT = 6          # seconds per DoH query
DKIM_COMMON_SELECTORS = [
    "default", "google", "selector1", "selector2", "k1", "k2",
    "s1", "s2", "mail", "dkim", "mandrill", "smtp",
]

EMAILAUTH_STAMP = (
    "This check reports what the domain's public DNS records showed "
    "at scan time. NorthCheck prepares evidence; it does not certify "
    "compliance and is not legal advice."
)


class DnsLookupError(Exception):
    """A DNS lookup itself failed (resolver unreachable / error)."""


def _clean_txt_data(data):
    """Google DoH returns TXT data as quoted segments; join them."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', data or "")
    if parts:
        return "".join(p.replace('\\"', '"') for p in parts)
    return (data or "").strip()


def doh_txt_resolver(name, endpoint=None, timeout=DNS_TIMEOUT):
    """Default resolver: TXT records for name via DNS-over-HTTPS.

    Returns a list of record strings (empty when the name has no TXT
    records). Raises DnsLookupError when the lookup cannot be
    completed — callers must not treat that as "no records".
    """
    endpoint = endpoint or os.environ.get("NORTHCHECK_DOH_URL") \
        or DOH_ENDPOINT
    query = urllib.parse.urlencode({"name": name, "type": "TXT"})
    req = urllib.request.Request(
        f"{endpoint}?{query}",
        headers={"Accept": "application/dns-json",
                 "User-Agent": "NorthCheck/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DnsLookupError(f"DNS lookup for {name} failed ({exc})")
    status = payload.get("Status", 0)
    if status == 3:                       # NXDOMAIN — name does not exist
        return []
    if status != 0:
        raise DnsLookupError(
            f"DNS lookup for {name} returned status {status}")
    records = []
    for answer in payload.get("Answer", []) or []:
        if answer.get("type") == 16:     # TXT
            records.append(_clean_txt_data(answer.get("data", "")))
    return records


_SPF_MECHANISMS = {"all", "include", "a", "mx", "ptr", "ip4", "ip6",
                   "exists"}
_SPF_MODIFIERS = {"redirect", "exp"}
_SPF_LOOKUP_MECHS = {"include", "a", "mx", "ptr", "exists"}


def _spf_terms(record):
    """Yield (qualifier, name, value) for each term after v=spf1."""
    for token in record.split()[1:]:
        qualifier = ""
        term = token
        if term[:1] in "+-~?":
            qualifier, term = term[0], term[1:]
        if "=" in term:
            name, _, value = term.partition("=")
            yield qualifier, name.lower(), value
            continue
        name = re.split(r"[:/]", term)[0].lower()
        value = term[len(name):].lstrip(":/")
        yield qualifier, name, value


def _spf_lookup_count(record, domain, resolver, visited=None, depth=0):
    """Count DNS-lookup terms in an SPF record, following includes.

    Counts include/a/mx/ptr/exists mechanisms and redirect modifiers
    in this record plus, recursively, in the SPF records of include /
    redirect targets this resolver can fetch. Returns (count,
    complete): complete is False when some target could not be
    resolved or the chain was cut (depth / revisit), so the count is
    a floor, not the full chain.
    """
    if visited is None:
        visited = set()
    visited.add(domain.lower())
    count = 0
    complete = True
    for _qual, name, value in _spf_terms(record):
        target = None
        if name in _SPF_LOOKUP_MECHS:
            count += 1
            if name == "include":
                target = value
        elif name == "redirect":
            count += 1
            target = value
        if target:
            target = target.split("/")[0].strip().lower()
            if not target or target in visited or depth >= 5:
                complete = False
                continue
            try:
                nested = [r for r in resolver(target)
                          if r.strip().lower().startswith("v=spf1")]
            except DnsLookupError:
                complete = False
                continue
            if nested:
                sub, sub_complete = _spf_lookup_count(
                    nested[0].strip(), target, resolver, visited,
                    depth + 1)
                count += sub
                complete = complete and sub_complete
    return count, complete


def _check_spf(domain, txt_records, resolver, findings):
    """SPF findings + stats for the TXT records found at the domain."""
    add = findings.append
    spf_records = [r.strip() for r in txt_records
                   if r.strip().lower().startswith("v=spf1")]
    stats = {"spf_records": spf_records, "spf_record": None,
             "spf_dns_lookups": None, "spf_lookup_complete": None}
    if not spf_records:
        add(make_finding(
            "emailauth", "EMAIL-SPF-MISSING", "high",
            "Email authentication · SPF missing",
            "No SPF record (a TXT record starting with v=spf1) is "
            "published at this domain. SPF is how receiving mail "
            "servers check whether a sender is allowed to send for "
            "the domain; without it, anyone can spoof the domain and "
            "nothing in DNS says otherwise.",
            f"(no v=spf1 TXT record at {domain})",
            "Publish one SPF TXT record at the domain naming the "
            "services that send your mail (for example your Microsoft "
            "365 or Google Workspace include) and ending in -all."))
        return stats
    record = spf_records[0]
    stats["spf_record"] = record
    if len(spf_records) > 1:
        add(make_finding(
            "emailauth", "EMAIL-SPF-MULTIPLE", "high",
            "Email authentication · multiple SPF records",
            "More than one SPF record is published at this domain. "
            "The SPF specification says a domain must publish exactly "
            "one; with two or more, receivers treat the result as an "
            "error (PermError) and the records protect nothing.",
            " · ".join(spf_records),
            "Merge everything into a single v=spf1 record and delete "
            "the extras."))
    terms = list(_spf_terms(record))
    all_terms = [(q, v) for q, n, v in terms if n == "all"]
    if any(q == "+" for q, _v in all_terms):
        add(make_finding(
            "emailauth", "EMAIL-SPF-PASSALL", "high",
            "Email authentication · SPF passes everyone (+all)",
            "The SPF record ends in +all, which tells every receiving "
            "server that ANY sender on the internet is authorized to "
            "send mail as this domain. That is worse than a stern "
            "warning — it affirmatively authorizes spoofing. This is "
            "the single most dangerous SPF state this check can find.",
            record,
            "Change +all to -all (or ~all while you are still "
            "inventorying senders) so only the listed services pass."))
    elif not all_terms:
        add(make_finding(
            "emailauth", "EMAIL-SPF-NOALL", "medium",
            "Email authentication · SPF has no all mechanism",
            "The SPF record never says what to do with senders it "
            "does not list: there is no -all, ~all, ?all or +all "
            "mechanism. Unlisted senders get a neutral result, which "
            "most receivers treat as a pass for filtering purposes.",
            record,
            "End the record with -all once every legitimate sender "
            "is listed (or ~all while you are still checking)."))
    elif any(q == "~" for q, _v in all_terms):
        add(make_finding(
            "emailauth", "EMAIL-SPF-SOFTFAIL", "low",
            "Email authentication · SPF softfail (~all)",
            "The SPF record ends in ~all (softfail): unlisted "
            "senders are flagged as suspicious rather than rejected. "
            "That is a reasonable step while inventorying senders, "
            "but it is weaker protection than -all.",
            record,
            "Move to -all when you are confident every legitimate "
            "sender is listed in the record."))
    elif any(q == "?" for q, _v in all_terms):
        add(make_finding(
            "emailauth", "EMAIL-SPF-NEUTRAL", "medium",
            "Email authentication · SPF neutral (?all)",
            "The SPF record ends in ?all (neutral): the domain "
            "explicitly takes no position on unlisted senders, so "
            "SPF gives receivers no basis to reject spoofed mail.",
            record,
            "Change ?all to -all (or ~all while inventorying "
            "senders) so the record actually decides."))
    unknown = sorted({n for _q, n, _v in terms
                      if n not in _SPF_MECHANISMS
                      and n not in _SPF_MODIFIERS and "%" not in n})
    if unknown:
        add(make_finding(
            "emailauth", "EMAIL-SPF-SYNTAX", "medium",
            "Email authentication · SPF syntax problem",
            "The SPF record contains term(s) that are not recognized "
            "SPF mechanisms or modifiers: " + ", ".join(unknown)
            + ". An unrecognized mechanism makes the whole record a "
            "permanent error at many receivers.",
            record,
            "Remove or correct the unrecognized term(s) and validate "
            "the record; keep only documented mechanisms (all, "
            "include, a, mx, ptr, ip4, ip6, exists) and modifiers "
            "(redirect, exp)."))
    count, complete = _spf_lookup_count(record, domain, resolver)
    stats["spf_dns_lookups"] = count
    stats["spf_lookup_complete"] = complete
    if count > 10:
        add(make_finding(
            "emailauth", "EMAIL-SPF-LOOKUPS", "high",
            "Email authentication · SPF over the 10 lookup limit",
            f"The SPF record's mechanism chain needs {count} DNS "
            "lookups (counted through the includes this check could "
            "resolve). SPF allows at most 10; past that, receivers "
            "return a permanent error and the record protects "
            "nothing, however good it looks.",
            record,
            "Flatten the chain: replace nested includes with the "
            "senders' ip4/ip6 ranges where stable, and drop includes "
            "for services that no longer send your mail."))
    return stats


def _check_dmarc(domain, resolver, lookup_errors, findings):
    """DMARC findings + stats for the record at _dmarc.<domain>."""
    add = findings.append
    stats = {"dmarc_record": None, "dmarc_policy": None}
    name = f"_dmarc.{domain}"
    try:
        txt_records = resolver(name)
    except DnsLookupError as exc:
        lookup_errors.append(str(exc))
        stats["dmarc_lookup_failed"] = True
        return stats
    dmarc_records = [r.strip() for r in txt_records
                     if r.strip().lower().startswith("v=dmarc1")]
    if not dmarc_records:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-MISSING", "high",
            "Email authentication · DMARC missing",
            "No DMARC record is published at _dmarc." + domain + ". "
            "DMARC is what lets the domain tell receivers to reject "
            "or quarantine mail that fails SPF and DKIM alignment — "
            "and what gets the domain's own reports about who is "
            "sending as it. Without DMARC, spoofed mail that fails "
            "checks can still be delivered.",
            f"(no v=DMARC1 TXT record at {name})",
            "Publish a DMARC TXT record at _dmarc." + domain
            + " — start at p=none with an rua reporting address to "
            "see who sends as you, then move to p=reject."))
        return stats
    record = dmarc_records[0]
    stats["dmarc_record"] = record
    if len(dmarc_records) > 1:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-MULTIPLE", "high",
            "Email authentication · multiple DMARC records",
            "More than one DMARC record is published at _dmarc."
            + domain + ". Receivers ignore DMARC entirely when a "
            "domain publishes more than one record, so the domain "
            "effectively has no DMARC policy.",
            " · ".join(dmarc_records),
            "Keep exactly one DMARC record at _dmarc." + domain
            + " and delete the rest."))
    tags = {}
    for part in record.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            tags[key.strip().lower()] = value.strip()
    policy = (tags.get("p") or "").lower()
    stats["dmarc_policy"] = policy or None
    if not policy:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-NOPOLICY", "medium",
            "Email authentication · DMARC record has no policy",
            "The DMARC record has no p= tag, so it states no policy "
            "and receivers treat the record as invalid.",
            record,
            "Add a p= tag — p=none to monitor, p=quarantine or "
            "p=reject to protect."))
    elif policy == "none":
        add(make_finding(
            "emailauth", "EMAIL-DMARC-MONITORING", "medium",
            "Email authentication · DMARC is monitor only (p=none)",
            "The DMARC policy is p=none: receivers report on failing "
            "mail but are told to deliver it anyway. That is the "
            "right first step when DMARC is new — it is not "
            "protection yet.",
            record,
            "Once the DMARC reports show every legitimate sender "
            "aligned, move the policy to p=quarantine, then "
            "p=reject."))
    elif policy == "quarantine":
        add(make_finding(
            "emailauth", "EMAIL-DMARC-QUARANTINE", "info",
            "Email authentication · DMARC quarantine (partial)",
            "The DMARC policy is p=quarantine: failing mail is "
            "treated as suspicious (usually sent to spam) rather "
            "than rejected outright. Real protection, one step "
            "short of the strongest setting.",
            record,
            "Move to p=reject when the reports show no legitimate "
            "sender would be caught."))
    elif policy == "reject":
        pass  # strongest policy — the stats table shows it as the pass
    else:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-BADPOLICY", "medium",
            "Email authentication · DMARC policy not recognized",
            f"The DMARC p= value is \"{policy}\", which is not one "
            "of none, quarantine or reject. Receivers treat an "
            "unrecognized policy as an invalid record.",
            record,
            "Set p= to none, quarantine or reject."))
    pct = tags.get("pct")
    if pct and pct.isdigit() and int(pct) < 100:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-PARTIAL", "info",
            "Email authentication · DMARC applies to some mail only",
            f"The DMARC record sets pct={pct}, so the policy is "
            "applied to only that percentage of failing mail. That "
            "is a rollout setting, not a finished one.",
            record,
            "Raise pct to 100 (or remove the tag) once the rollout "
            "is complete."))
    strict = [f"{tag}={tags[tag]}" for tag in ("adkim", "aspf")
              if tags.get(tag, "").lower() == "s"]
    if strict:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-ALIGNMENT", "info",
            "Email authentication · strict alignment set",
            "The DMARC record sets strict alignment ("
            + ", ".join(strict) + ") instead of the default relaxed "
            "alignment. That is a deliberate, stronger setting — "
            "noted here so it is on the record, and worth knowing "
            "about before blaming DMARC for a delivery problem.",
            record,
            "No change needed if strict alignment was set on "
            "purpose; otherwise remove the tag to return to relaxed "
            "alignment."))
    if "rua" not in tags:
        add(make_finding(
            "emailauth", "EMAIL-DMARC-NOREPORTING", "low",
            "Email authentication · no DMARC reporting address",
            "The DMARC record has no rua= reporting address, so the "
            "domain receives no aggregate reports about who is "
            "sending mail as it — the evidence that makes moving to "
            "a stronger policy safe.",
            record,
            "Add rua=mailto:an address you monitor (or a DMARC "
            "reporting service) to the record."))
    return stats


def _check_dkim(domain, resolver, lookup_errors, findings):
    """DKIM findings + stats over the common selector list."""
    add = findings.append
    found = []
    failed = 0
    for selector in DKIM_COMMON_SELECTORS:
        name = f"{selector}._domainkey.{domain}"
        try:
            txt_records = resolver(name)
        except DnsLookupError as exc:
            lookup_errors.append(str(exc))
            failed += 1
            continue
        for record in txt_records:
            text = record.strip()
            tags = {}
            for part in text.split(";"):
                if "=" in part:
                    key, _, value = part.partition("=")
                    tags[key.strip().lower()] = value.strip()
            if text.lower().startswith("v=dkim1") or "p" in tags:
                found.append({"selector": selector, "record": text})
                if "p" in tags and not tags["p"]:
                    add(make_finding(
                        "emailauth", "EMAIL-DKIM-REVOKED", "medium",
                        "Email authentication · DKIM key revoked",
                        f"The DKIM record under the \"{selector}\" "
                        "selector has an empty public key (p=), which "
                        "is how a key is revoked: mail signed with "
                        "that selector cannot verify. If a sending "
                        "service still uses this selector, its mail "
                        "is failing DKIM.",
                        text,
                        "If the service still sends for you, republish "
                        "its current public key; if it was retired on "
                        "purpose, this note is your confirmation."))
                break
    stats = {"dkim_found": found,
             "dkim_selectors_checked": list(DKIM_COMMON_SELECTORS),
             "dkim_lookups_failed": failed}
    if not found:
        add(make_finding(
            "emailauth", "EMAIL-DKIM-NOTFOUND", "medium",
            "Email authentication · no DKIM on common selectors",
            "No DKIM record was found on the common selectors "
            "checked (" + ", ".join(DKIM_COMMON_SELECTORS) + "). "
            "DKIM selectors cannot be enumerated from DNS, so this "
            "does not prove DKIM is absent: DKIM may still exist "
            "under a different selector name. It does mean the "
            "selectors used by the biggest senders (Google "
            "Workspace, Microsoft 365 and the major mailing "
            "services) show no key — if the domain sends through "
            "one of them, its mail is very likely not being signed.",
            f"(no v=DKIM1 record at any <selector>._domainkey."
            f"{domain} for the selectors checked)",
            "Check each sending service's DKIM settings: turn DKIM "
            "signing on and publish the selector record it gives "
            "you, then re-run this check."))
    return stats


def normalize_domain(value):
    """Reduce user input (bare domain or URL) to a bare domain."""
    text = (value or "").strip().lower()
    if "://" in text:
        text = urllib.parse.urlparse(text).hostname or ""
    text = text.split("/")[0].split(":")[0].rstrip(".")
    return text


def run_emailauth_checks(domain, resolver=None):
    """Return (findings, stats) for a domain's email authentication.

    resolver: callable(name) -> list of TXT record strings, raising
    DnsLookupError on lookup failure. Defaults to the DNS-over-HTTPS
    resolver. When the lookups needed to judge SPF and DMARC both
    fail, stats["resolution_failed"] is True and findings is empty:
    the caller must present "check could not be completed", never
    findings invented from missing data.
    """
    if resolver is None:
        resolver = doh_txt_resolver
    domain = normalize_domain(domain)
    findings = []
    lookup_errors = []
    stats = {"domain": domain, "resolution_failed": False,
             "lookup_errors": lookup_errors}
    try:
        apex_records = resolver(domain)
        apex_failed = False
    except DnsLookupError as exc:
        apex_records, apex_failed = [], True
        lookup_errors.append(str(exc))
    spf_stats = _check_spf(domain, apex_records, resolver, findings) \
        if not apex_failed else {"spf_records": [], "spf_record": None,
                                 "spf_dns_lookups": None,
                                 "spf_lookup_complete": None}
    stats.update(spf_stats)
    dmarc_stats = _check_dmarc(domain, resolver, lookup_errors,
                               findings)
    stats.update(dmarc_stats)
    dkim_stats = _check_dkim(domain, resolver, lookup_errors, findings)
    stats.update(dkim_stats)
    if apex_failed and dmarc_stats.get("dmarc_lookup_failed"):
        stats["resolution_failed"] = True
        findings = []
    return findings, stats


# ---------------------------------------------------------------------------
# Module Tracker and Consent Check — trackers vs consent, served HTML
# ---------------------------------------------------------------------------
# Deterministic detection over the HTML exactly as served (the pages
# the app's crawler fetched — no JavaScript is run, nothing is
# rendered). Known tracker / marketing-tag signatures, known
# consent-platform signatures and Google Consent Mode signals are
# matched against the raw markup of each scanned page.
#
# Honesty limits, repeated in the findings themselves: served HTML
# shows which tags and consent tools are PRESENT in the page source.
# It cannot prove when a tag fires in a real visitor's browser — a
# tag manager container, a consent tool injected at runtime, or
# server-side tagging can all change the order — so no finding here
# claims a tracker fires before consent, and a consent banner's
# presence is never reported as proof that tags wait for consent.

TRACKERS_STAMP = (
    "This check reports the tracker and consent signals found in "
    "the HTML exactly as served at scan time. The page's JavaScript "
    "was not run, so the check cannot show when a tag actually "
    "fires in a visitor's browser. NorthCheck prepares evidence; "
    "it does not certify compliance and is not legal advice."
)

# (key, display name, is a Google tag, substring markers, regexes).
# Substrings are matched against the lowercased markup; regexes run
# case-insensitively over the markup as served, and the matched text
# is recorded as the evidence.
TRACKER_SIGNATURES = [
    ("google-analytics", "Google Analytics", True,
     ("google-analytics.com", "gtag/js?id=", "googletagmanager.com/gtag",
      "analytics.js"),
     (r"\bua-\d{4,}-\d+\b",
      r"gtag\(\s*['\"]config['\"]\s*,\s*['\"]g-[a-z0-9]{4,}")),
    ("google-tag-manager", "Google Tag Manager", True,
     ("googletagmanager.com/gtm.js", "gtm.start"),
     (r"\bgtm-[a-z0-9]{6,}\b",)),
    ("meta-pixel", "Meta (Facebook) Pixel", False,
     ("connect.facebook.net", "fbevents.js", "fbq("),
     ()),
    ("google-ads", "Google Ads", True,
     ("googleadservices.com", "googleads.g.doubleclick.net",
      "google_conversion"),
     (r"\baw-\d{6,}\b",)),
    ("tiktok-pixel", "TikTok Pixel", False,
     ("analytics.tiktok.com", "ttq.load", "ttq.track"),
     ()),
    ("linkedin-insight", "LinkedIn Insight Tag", False,
     ("snap.licdn.com", "_linkedin_partner_id",
      "_linkedin_data_partner_ids"),
     ()),
    ("hotjar", "Hotjar", False,
     ("static.hotjar.com", "_hjsettings", "hjbootstrap"),
     ()),
    ("microsoft-clarity", "Microsoft Clarity", False,
     ("clarity.ms",),
     ()),
    ("hubspot", "HubSpot Tracking", False,
     ("js.hs-scripts.com", "js.hs-analytics.net", "js.hubspot.com"),
     ()),
    ("matomo", "Matomo / Piwik", False,
     ("matomo.js", "piwik.js", "_paq.push", "matomo.cloud"),
     ()),
    ("segment", "Segment", False,
     ("cdn.segment.com", "analytics.load("),
     ()),
]

# (key, display name, substring markers) for consent management
# platforms. Detection means the platform's code is present in the
# served HTML — nothing more (see the honesty note above).
CONSENT_PLATFORM_SIGNATURES = [
    ("onetrust", "OneTrust",
     ("onetrust.com", "otsdkstub", "optanon")),
    ("cookiebot", "Cookiebot",
     ("cookiebot.com", "consent.cookiebot.com")),
    ("cookieyes", "CookieYes",
     ("cookieyes.com", "cdn-cookieyes.com")),
    ("termly", "Termly",
     ("termly.io", "app.termly.io")),
    ("osano", "Osano",
     ("osano.com", "cmp.osano.com")),
    ("trustarc", "TrustArc",
     ("trustarc.com", "consent.trustarc.com", "truste.com")),
    ("didomi", "Didomi",
     ("didomi.io", "sdk.privacy-center.org")),
    ("axeptio", "Axeptio",
     ("static.axept.io", "axeptio.eu")),
    ("iubenda", "iubenda",
     ("iubenda.com", "cdn.iubenda.com")),
    ("usercentrics", "Usercentrics",
     ("usercentrics.eu", "app.usercentrics.eu")),
    ("consentmanager", "consentmanager",
     ("consentmanager.net", "cdn.consentmanager.net")),
    ("quantcast", "Quantcast Choice",
     ("quantcast.com/choice", "qc-cmp2-ui")),
]

# Class / id / file names that typically mark a home-grown cookie
# banner in the served markup (no platform behind it).
BANNER_MARKERS = ("cookie-banner", "cookie-consent", "cookiebanner",
                  "cookie-notice", "cookie_notice", "cookie-popup",
                  "cookie-modal", "cookie-bar", "cookie-law",
                  "cookie-alert", "cookie-message", "consent-banner",
                  "gdpr-banner")

CONSENT_MODE_PARAMS = ("ad_storage", "analytics_storage",
                       "ad_user_data", "ad_personalization")

_CONSENT_CALL_RE = re.compile(
    r"gtag\(\s*['\"]consent['\"]\s*,\s*['\"](default|update)['\"]",
    re.IGNORECASE)


def _match_signature(html_text, raw_lower, substrings, regexes):
    """First matching marker for one signature, else None."""
    for marker in substrings:
        if marker in raw_lower:
            return marker
    for pattern in regexes:
        m = re.search(pattern, html_text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def run_trackers_checks(pages):
    """Return (findings, stats) for a crawled site.

    pages: list of {url, html} in crawl order — pages[0] is the
    homepage the visitor entered. Detection runs over every scanned
    page: a tracker or consent tool loaded site-wide is reported
    once, with the pages it was seen on.
    """
    detected = {}        # signature key -> detail dict
    platforms = {}       # signature key -> detail dict
    banner_marker = None
    consent_wording = None
    consent_call_kinds = set()
    consent_params = []
    for p in pages:
        url, html_text = p["url"], p["html"]
        raw_lower = html_text.lower()
        for key, name, is_google, substrings, regexes in \
                TRACKER_SIGNATURES:
            marker = _match_signature(html_text, raw_lower,
                                      substrings, regexes)
            if marker is None:
                continue
            entry = detected.setdefault(key, {
                "key": key, "name": name, "google": is_google,
                "pages": [], "markers": []})
            if url not in entry["pages"]:
                entry["pages"].append(url)
            if marker not in entry["markers"]:
                entry["markers"].append(marker)
        for key, name, substrings in CONSENT_PLATFORM_SIGNATURES:
            marker = _match_signature(html_text, raw_lower,
                                      substrings, ())
            if marker is None:
                continue
            entry = platforms.setdefault(key, {
                "key": key, "name": name, "pages": [], "markers": []})
            if url not in entry["pages"]:
                entry["pages"].append(url)
            if marker not in entry["markers"]:
                entry["markers"].append(marker)
        if banner_marker is None:
            for marker in BANNER_MARKERS:
                if marker in raw_lower:
                    banner_marker = marker
                    break
        if consent_wording is None:
            text = parse_site_page(html_text).text
            for pattern in COOKIE_TEXT_PATTERNS:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    consent_wording = m.group(0)
                    break
        for m in _CONSENT_CALL_RE.finditer(html_text):
            consent_call_kinds.add(m.group(1).lower())
        for param in CONSENT_MODE_PARAMS:
            if param in raw_lower and param not in consent_params:
                consent_params.append(param)

    tracker_list = [detected[key] for key, *_rest
                    in TRACKER_SIGNATURES if key in detected]
    platform_list = [platforms[key] for key, *_rest
                     in CONSENT_PLATFORM_SIGNATURES if key in platforms]
    consent_mode_found = bool(consent_call_kinds) \
        or len(consent_params) >= 2
    consent_mechanism = bool(platform_list) or banner_marker is not None \
        or consent_wording is not None
    google_found = any(t["google"] for t in tracker_list)
    names = ", ".join(t["name"] for t in tracker_list)

    findings = []
    add = findings.append
    if not tracker_list:
        add(make_finding(
            "trackers", "TRACK-NONE-FOUND", "info",
            "Trackers · none detected in the page source",
            "None of the known tracker or marketing-tag signatures "
            "this check looks for (Google Analytics, Google Tag "
            "Manager, Meta Pixel, Google Ads, TikTok, LinkedIn, "
            "Hotjar, Microsoft Clarity and similar) matched in the "
            "HTML as served on the scanned pages. That is the clean "
            "result this check can give — with two limits. Tags can "
            "also be loaded at runtime by JavaScript or fired "
            "server-side, neither of which leaves a signature in "
            "the served HTML, and pages beyond the crawl cap were "
            "not read.",
            f"(no known tracker signature matched on "
            f"{len(pages)} scanned page(s))",
            "No fix implied. Re-run this check after adding any "
            "marketing, analytics or chat tool, since each one "
            "usually brings its own tracker."))
    else:
        evidence = "; ".join(
            f"{t['name']} (signature: {t['markers'][0]})"
            for t in tracker_list)
        if not consent_mechanism:
            add(make_finding(
                "trackers", "TRACK-NO-CONSENT", "high",
                "Trackers · no consent mechanism in the page source",
                f"The page source loads these trackers: {names}. "
                "No consent mechanism of any kind was found with "
                "them — no known consent platform, no cookie banner "
                "markup, and no consent wording on the scanned "
                "pages. Quebec's Law 25 expects express consent for "
                "cookies that identify, locate or profile a visitor, "
                "and European rules expect consent before "
                "non-essential tracking runs; regulators there fined "
                "Google and Shein in 2025 over cookies placed before "
                "consent. Read this finding for exactly what it "
                "shows: the tags are present in the source and no "
                "consent mechanism is visible there. It does not "
                "prove the tags fire before consent in a real "
                "browser — a tag manager or a script this crawl "
                "cannot execute could still hold them back — so "
                "confirm in the browser what loads before a first "
                "time visitor makes any choice.",
                evidence,
                "Put a consent mechanism in front of the tags: run "
                "a consent platform (or an equivalent banner), set "
                "the trackers to wait for the visitor's consent "
                "before they load, and keep the banner in the "
                "served page, where visitors — and this scan — can "
                "see it."))
        else:
            mech = []
            if platform_list:
                mech.append("consent platform: "
                            + ", ".join(p["name"]
                                        for p in platform_list))
            if banner_marker:
                mech.append(f"banner markup: {banner_marker}")
            if consent_wording:
                mech.append(f"consent wording: “{consent_wording}”")
            add(make_finding(
                "trackers", "TRACK-CONSENT-UNVERIFIED", "info",
                "Trackers · consent mechanism present, blocking "
                "not verified",
                f"The page source loads these trackers: {names}. "
                "A consent mechanism is present in the source ("
                + "; ".join(mech) + "). That is the right shape — "
                "and it is all this check can confirm. A banner's "
                "presence does not prove the tags wait for consent: "
                "many banners load every tag immediately and only "
                "record the visitor's choice afterwards. Whether "
                "these tags hold back until a visitor accepts can "
                "only be settled in a real browser, by watching "
                "which requests fire before any choice is made.",
                evidence,
                "Verify, do not assume: in a clean browser profile "
                "with cookies cleared, load the homepage and watch "
                "the network requests before clicking anything — "
                "no tracker should fire before consent, and none "
                "should fire at all after a decline. Repeat after "
                "any change to the banner or the tag setup."))
        if google_found and not consent_mode_found:
            google_names = ", ".join(t["name"] for t in tracker_list
                                     if t["google"])
            add(make_finding(
                "trackers", "TRACK-NO-CONSENT-MODE", "medium",
                "Trackers · Google Consent Mode signals not found",
                f"Google tags are present ({google_names}), but no "
                "Google Consent Mode signals were found in the page "
                "source: no gtag consent default or update call, "
                "and the Consent Mode storage settings (ad_storage, "
                "analytics_storage, ad_user_data, "
                "ad_personalization) do not appear. Google has "
                "required Consent Mode v2 for advertising "
                "personalization in Europe since March 2024 and "
                "began restricting conversion tracking and audience "
                "building for accounts without it in July 2025 — "
                "the cost lands on your own ad measurement first. "
                "One limit: a consent platform may inject these "
                "calls at runtime through JavaScript this crawl "
                "does not run, so confirm in the browser or in "
                "Google Tag Assistant before treating them as "
                "missing for good.",
                f"(no consent default/update call or Consent Mode "
                f"storage settings in {len(pages)} scanned page(s))",
                "Set Consent Mode v2 defaults before the Google "
                "tags load (all four storage settings, denied until "
                "the visitor chooses), and update them from the "
                "visitor's consent choice — most consent platforms "
                "can emit these calls once the setting is switched "
                "on."))

    stats = {
        "pages_scanned": len(pages),
        "trackers_found": [t["name"] for t in tracker_list],
        "trackers_detail": tracker_list,
        "tracker_count": len(tracker_list),
        "google_tags_found": google_found,
        "consent_platforms": [p["name"] for p in platform_list],
        "consent_platforms_detail": platform_list,
        "banner_detected": banner_marker is not None,
        "banner_marker": banner_marker,
        "consent_wording_found": consent_wording is not None,
        "consent_mechanism_found": consent_mechanism,
        "consent_mode_found": consent_mode_found,
        "consent_mode_calls": sorted(consent_call_kinds),
        "consent_mode_params": consent_params,
    }
    return findings, stats


# ---------------------------------------------------------------------------
# AODA Complete the Filing — re-scan comparison (remediation tracker)
# ---------------------------------------------------------------------------
#
# The December 31, 2026 accessibility compliance report covers all parts
# of the Integrated Accessibility Standards Regulation (IASR) and must
# be certified by a senior officer. The website scan evidences only the
# web-content part, so Complete the Filing adds: (1) this re-scan
# comparison, which is the only source of "fixed" status — a finding is
# resolved only when a later scan no longer reports it; (2) an
# owner-answered checklist for the non-website standards; and (3) the
# helpers that summarise both for the Filing Pack.

from collections import Counter


def _norm_page_url(url):
    """Normalise a crawled page URL for cross-scan comparison."""
    url = urllib.parse.urldefrag(url or "")[0]
    parts = urllib.parse.urlsplit(url)
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path,
         parts.query, ""))


def finding_key(page_url, finding):
    """Identity of one finding on one page across scans."""
    return (_norm_page_url(page_url), finding["rule_id"],
            finding["evidence"])


def compare_scan_pages(previous_pages, current_pages):
    """Compare two AODA page-result lists ({url, findings} per page).

    Returns a dict of entry lists — each entry is {"page_url", "finding"}
    — in four buckets:

      resolved       in the previous scan, gone from the new scan of the
                     same page — the ONLY way a finding earns "fixed"
                     status in NorthCheck
      still_open     reported by both scans of the same page
      new            reported only by the new scan (including findings
                     on pages scanned for the first time)
      not_rechecked  the previous scan saw this page but the new scan
                     did not crawl it, so nothing can be claimed about
                     those findings either way

    Duplicate identical findings on one page are counted with
    multiplicity: if a page had three of a finding and now has one, two
    count as resolved and one as still open.
    """
    prev_pages = {_norm_page_url(p["url"]) for p in previous_pages}
    curr_pages = {_norm_page_url(p["url"]) for p in current_pages}

    def index(pages, restrict=None):
        by_key = {}
        for p in pages:
            if restrict is not None \
                    and _norm_page_url(p["url"]) not in restrict:
                continue
            for f in p["findings"]:
                by_key.setdefault(finding_key(p["url"], f), []).append(
                    {"page_url": p["url"], "finding": f})
        return by_key

    prev_idx = index(previous_pages, restrict=curr_pages)
    curr_idx = index(current_pages)
    prev_counts = Counter({k: len(v) for k, v in prev_idx.items()})
    curr_counts = Counter({k: len(v) for k, v in curr_idx.items()})

    def take(idx, counts, other_counts):
        out = []
        for key in idx:
            n = counts[key] - other_counts.get(key, 0)
            if n > 0:
                out.extend(idx[key][:n])
        return out

    still_open = []
    for key in curr_idx:
        n = min(curr_counts[key], prev_counts.get(key, 0))
        if n > 0:
            still_open.extend(curr_idx[key][:n])
    resolved = take(prev_idx, prev_counts, curr_counts)
    new = take(curr_idx, curr_counts, prev_counts)
    not_rechecked = []
    for p in previous_pages:
        if _norm_page_url(p["url"]) not in curr_pages:
            not_rechecked.extend(
                {"page_url": p["url"], "finding": f}
                for f in p["findings"])

    def order(entry):
        f = entry["finding"]
        return (SEVERITY_ORDER[f["severity"]], f["rule_id"],
                entry["page_url"])

    result = {
        "resolved": sorted(resolved, key=order),
        "still_open": sorted(still_open, key=order),
        "new": sorted(new, key=order),
        "not_rechecked": sorted(not_rechecked, key=order),
    }
    result["counts"] = {
        "resolved": len(result["resolved"]),
        "still_open": len(result["still_open"]),
        "new": len(result["new"]),
        "not_rechecked": len(result["not_rechecked"]),
        "previous_total": sum(len(p["findings"])
                              for p in previous_pages),
        "current_total": sum(len(p["findings"])
                             for p in current_pages),
    }
    return result


# ---------------------------------------------------------------------------
# AODA Complete the Filing — checklist for the non-website standards
# ---------------------------------------------------------------------------
#
# Every status here is an OWNER-ANSWERED statement. NorthCheck never
# verifies checklist answers; anywhere they are shown they must be
# labelled as the organization's own statements. The website itself is
# NOT a checklist item — web content is evidenced by the AODA scan.

CHECKLIST_STATUSES = ("compliant", "in_progress", "not_started",
                      "not_applicable")

CHECKLIST_STATUS_LABELS = {
    "compliant": "Compliant (owner stated)",
    "in_progress": "In progress (owner stated)",
    "not_started": "Not started (owner stated)",
    "not_applicable": "Not applicable (owner stated)",
    "unanswered": "Not answered yet",
}

FILING_CHECKLIST = [
    {
        "id": "general",
        "standard": "General requirements",
        "applies": "Applies to every organization filing the report.",
        "items": [
            {"id": "GEN-POLICY",
             "text": "We have developed, implemented and maintain "
                     "accessibility policies, including a statement of "
                     "organizational commitment to meeting the "
                     "accessibility needs of people with disabilities "
                     "in a timely manner."},
            {"id": "GEN-PLAN",
             "text": "We have established, implemented, maintained "
                     "and documented a multi-year accessibility plan, "
                     "posted it (including on our website if we have "
                     "one) in an accessible format, and we review and "
                     "update it at least once every five years."},
            {"id": "GEN-TRAINING",
             "text": "Everyone who provides goods, services or "
                     "facilities on our behalf (staff, volunteers and "
                     "third parties) has been trained on the IASR and "
                     "on the Human Rights Code as it relates to people "
                     "with disabilities, and we keep a record of the "
                     "training, including the dates and the number of "
                     "people trained."},
            {"id": "GEN-FEEDBACK",
             "text": "Our process for receiving and responding to "
                     "feedback is accessible to people with "
                     "disabilities, and we let the public know about "
                     "that process."},
            {"id": "GEN-KIOSK",
             "text": "When we design, procure or acquire self-service "
                     "kiosks, we incorporate their accessibility "
                     "features and criteria. (Mark Not applicable if "
                     "we have no self-service kiosks and do not plan "
                     "to acquire any.)"},
        ],
    },
    {
        "id": "info_comm",
        "standard": "Information and Communications — beyond the "
                    "website",
        "applies": "The website itself is covered by the AODA scan, "
                   "not this section. These items cover the rest of "
                   "the standard.",
        "items": [
            {"id": "IC-FORMATS",
             "text": "On request, we provide (or arrange to provide) "
                     "accessible formats and communication supports "
                     "for our information and communications in a "
                     "timely manner, at a cost no more than the "
                     "regular cost charged to others, and we consult "
                     "the person making the request."},
            {"id": "IC-NOTIFY",
             "text": "We notify the public about the availability of "
                     "accessible formats and communication supports."},
            {"id": "IC-EMERGENCY",
             "text": "Emergency procedures, plans and public safety "
                     "information that we make available to the public "
                     "are provided, on request, in an accessible "
                     "format or with appropriate communication "
                     "supports as soon as practicable."},
        ],
    },
    {
        "id": "customer_service",
        "standard": "Customer Service",
        "applies": "Applies to organizations that provide goods, "
                   "services or facilities to the public or to other "
                   "third parties in Ontario.",
        "items": [
            {"id": "CS-POLICIES",
             "text": "We have policies, practices and procedures for "
                     "providing goods, services or facilities to "
                     "people with disabilities, consistent with the "
                     "principles of dignity, independence, integration "
                     "and equal opportunity."},
            {"id": "CS-DEVICES",
             "text": "People with disabilities may use their own "
                     "personal assistive devices on our premises, "
                     "and our staff are trained on any assistive "
                     "devices we provide."},
            {"id": "CS-SUPPORT",
             "text": "We welcome support persons, let people know in "
                     "advance about any fee charged for a support "
                     "person, and obtain consent where the law "
                     "requires it before discussing confidential "
                     "matters in a support person's presence."},
            {"id": "CS-ANIMALS",
             "text": "We welcome service animals in the parts of our "
                     "premises that are open to the public (subject "
                     "to legal exclusions, such as some food "
                     "preparation areas)."},
            {"id": "CS-DISRUPTION",
             "text": "When there is a temporary disruption to the "
                     "facilities or services people with disabilities "
                     "usually use, we give notice — including the "
                     "reason, how long it is expected to last, and "
                     "alternative facilities or services where "
                     "available — on our premises and website."},
            {"id": "CS-TRAINING",
             "text": "Our customer-service staff and everyone who "
                     "deals with the public on our behalf has been "
                     "trained on serving people with disabilities, "
                     "and we keep training records."},
        ],
    },
    {
        "id": "employment",
        "standard": "Employment",
        "applies": "Applies to organizations with employees. "
                   "Obligations are owed to employees and to job "
                   "applicants.",
        "items": [
            {"id": "EMP-NOTIFY",
             "text": "We notify our employees and the public about "
                     "the availability of accommodation for applicants "
                     "with disabilities in our recruitment processes."},
            {"id": "EMP-SELECTION",
             "text": "We notify job applicants who are individually "
                     "selected for an assessment or selection process "
                     "that accommodations are available on request, "
                     "and we provide suitable accommodation when asked."},
            {"id": "EMP-INFORM",
             "text": "We inform successful applicants and all "
                     "employees of our policies for supporting "
                     "employees with disabilities, and we update "
                     "employees whenever those policies change."},
            {"id": "EMP-FORMATS",
             "text": "On request, we provide accessible formats and "
                     "communication supports for information an "
                     "employee with a disability needs to do their job "
                     "and for information generally available to "
                     "employees, after consulting the employee."},
            {"id": "EMP-PLAN",
             "text": "We have a process for developing documented "
                     "individual accommodation plans for employees "
                     "with disabilities, and plans are in place for "
                     "employees who have asked for them."},
            {"id": "EMP-RETURN",
             "text": "We have a documented return-to-work process "
                     "for employees who have been absent because of a "
                     "disability and need disability-related "
                     "accommodation to return."},
            {"id": "EMP-PERF",
             "text": "Our performance management, career development "
                     "and advancement, and redeployment practices "
                     "take into account the accessibility needs and "
                     "any individual accommodation plans of employees "
                     "with disabilities."},
        ],
    },
    {
        "id": "transportation",
        "standard": "Transportation",
        "applies": "Applies ONLY if your organization provides "
                   "conventional or specialized transportation "
                   "services in Ontario. If it does not, mark every "
                   "item in this section Not applicable.",
        "items": [
            {"id": "TRANS-FEATURES",
             "text": "Our vehicles and their accessibility features, "
                     "equipment and services meet the Transportation "
                     "Standard's requirements (including signage, "
                     "stops, lighting, fare parity and priority "
                     "seating, as applicable to our service)."},
            {"id": "TRANS-PLANS",
             "text": "Accessibility for our transportation services "
                     "is included in our accessibility plan, and we "
                     "consult people with disabilities in developing "
                     "it as the Standard requires."},
        ],
    },
    {
        "id": "public_spaces",
        "standard": "Design of Public Spaces",
        "applies": "Applies when your organization builds or "
                   "re-develops public spaces covered by the "
                   "standard (outdoor paths, outdoor eating and play "
                   "areas, accessible parking, service counters and "
                   "waiting areas). If you neither own nor redevelop "
                   "such spaces, mark the items Not applicable.",
        "items": [
            {"id": "DPS-BUILD",
             "text": "When we build or redevelop public spaces, the "
                     "work meets the Design of Public Spaces "
                     "requirements for those spaces."},
            {"id": "DPS-MAINTAIN",
             "text": "Our accessibility plan includes procedures for "
                     "preventative and emergency maintenance of the "
                     "accessible elements of our public spaces, and "
                     "for dealing with temporary disruptions to them."},
        ],
    },
]

FILING_CERTIFICATION_NOTE = (
    "The accessibility compliance report itself is filed by your "
    "organization through the Ontario government's Accessibility "
    "Compliance Reporting portal, and it must be certified by a "
    "senior officer of the organization. NorthCheck does not file "
    "the report and does not certify anything: this pack prepares "
    "the evidence a senior officer reviews before signing. Checklist "
    "answers in this pack are your organization's own statements, "
    "recorded as given — NorthCheck has not verified them."
)


def checklist_items():
    """Flat list of (section, item) across the whole checklist."""
    return [(section, item) for section in FILING_CHECKLIST
            for item in section["items"]]


def checklist_summary(answers):
    """Summarise owner-answered checklist statuses.

    answers: {item_id: status}. Items not in answers count as
    "unanswered" — never as compliant.
    """
    per_standard = []
    totals = {s: 0 for s in CHECKLIST_STATUSES + ("unanswered",)}
    for section in FILING_CHECKLIST:
        row = {"standard": section["standard"], "total": 0}
        for status in CHECKLIST_STATUSES + ("unanswered",):
            row[status] = 0
        for item in section["items"]:
            status = answers.get(item["id"])
            if status not in CHECKLIST_STATUSES:
                status = "unanswered"
            row[status] += 1
            row["total"] += 1
            totals[status] += 1
        per_standard.append(row)
    totals["total"] = sum(v for k, v in totals.items() if k != "total")
    return {"per_standard": per_standard, "totals": totals}


def filing_gaps(answers, comparison=None, latest_total=None):
    """Plain-language remaining-gaps lines for the Filing Pack.

    Website gaps come from scan evidence (latest scan totals and, when
    present, the re-scan comparison). Checklist gaps come only from
    owner answers — stated as such.
    """
    lines = []
    if comparison is not None:
        c = comparison["counts"]
        if c["still_open"]:
            lines.append(
                f"Website: {c['still_open']} finding(s) from the "
                "previous scan are still open in the latest re-scan.")
        if c["new"]:
            lines.append(
                f"Website: {c['new']} new finding(s) appeared in the "
                "latest scan.")
        if c["not_rechecked"]:
            lines.append(
                f"Website: {c['not_rechecked']} finding(s) sit on "
                "pages the latest scan did not crawl, so their status "
                "is unknown — re-scan those pages before relying on "
                "them.")
        if not (c["still_open"] or c["new"] or c["not_rechecked"]):
            lines.append(
                "Website: every finding from the previous scan is "
                "verified resolved by the latest re-scan. Automated "
                "checks cover only part of WCAG — this is not a "
                "guarantee the site is compliant.")
    elif latest_total:
        lines.append(
            f"Website: the latest scan reports {latest_total} "
            "issue(s) to review. No earlier scan is on file for this "
            "site, so no fix can be shown as verified yet — scan "
            "again after remediation to verify.")
    summary = checklist_summary(answers)
    t = summary["totals"]
    if t["not_started"]:
        lines.append(
            f"Checklist (owner stated): {t['not_started']} item(s) "
            "are marked Not started.")
    if t["in_progress"]:
        lines.append(
            f"Checklist (owner stated): {t['in_progress']} item(s) "
            "are marked In progress — not yet in place at filing "
            "time unless finished first.")
    if t["unanswered"]:
        lines.append(
            f"Checklist: {t['unanswered']} item(s) have not been "
            "answered. The report asks about every standard that "
            "applies to you — answer or mark Not applicable for each "
            "before filing.")
    return lines


# ---------------------------------------------------------------------------
# Fabricated demo inputs (clearly labelled; problems seeded on purpose)
# ---------------------------------------------------------------------------

# Fictional business: "Maple Street Bakery", a made-up Toronto bakery.
# Seeded AODA issues (verify against the scan output — they must match):
#   * <html> with NO lang attribute            -> AODA-LANG (high)
#   * empty <title></title>                    -> AODA-TITLE (high)
#   * storefront <img> with NO alt attribute   -> AODA-IMG-ALT (high)
#   * divider <img alt=""> is decorative       -> counted, NOT a finding
#   * bread <img> with real alt text           -> clean
#   * "fullname" text input, no label          -> AODA-LABEL (high)
#   * "pickup" <select>, no label              -> AODA-LABEL (high)
#   * phone input has <label for>              -> clean
#   * email input wrapped in its <label>       -> clean
#   * notes <textarea> has aria-label          -> clean
#   * headings h1 then h3 (h2 skipped)         -> AODA-HEADING-ORDER (med)
#   * empty <a href="/specials"></a>           -> AODA-LINK-EMPTY (medium)
#   * "click here" link                        -> AODA-LINK-GENERIC (low)
#   * icon-only <button> with no aria-label    -> AODA-BUTTON-TEXT (high)
#   * id="promo" used twice                    -> AODA-DUP-ID (medium)
# Expected totals: 10 findings — high 6, medium 3, low 1, info 0.
DEMO_SITE_HTML = """<!DOCTYPE html>
<!-- FABRICATED DEMO PAGE for a fictional business (Maple Street Bakery).
     Accessibility problems are seeded on purpose to verify the scanner.
     See northcheck.py for the seeded-issue inventory. -->
<html>
<head>
<meta charset="utf-8">
<title></title>
</head>
<body>
<header>
  <h1>Maple Street Bakery</h1>
  <nav>
    <a href="/menu">Our menu</a>
    <a href="/specials"></a>
    <a href="/story">click here</a>
  </nav>
</header>
<main>
  <h3>Our story</h3>
  <p id="promo">Family owned since 1998, baking every morning at 5 a.m.</p>
  <img src="images/storefront.jpg">
  <img src="images/divider.png" alt="">
  <img src="images/bread.jpg" alt="Fresh sourdough loaves on a wooden rack">
  <h3>Today at the counter</h3>
  <p id="promo">Weekend special: maple butter tarts, two for one.</p>
  <button type="button" class="search-toggle"></button>
  <button type="button">Order ahead</button>
  <h2>Visit us</h2>
  <form action="/order" method="post">
    <label for="phone">Phone</label>
    <input type="text" id="phone" name="phone">
    <input type="text" id="fullname" name="fullname" placeholder="Your name">
    <label>Email address <input type="email" id="email" name="email"></label>
    <select id="pickup" name="pickup">
      <option>Morning</option>
      <option>Afternoon</option>
    </select>
    <textarea id="notes" name="notes" aria-label="Order notes"></textarea>
    <input type="submit" value="Send order">
  </form>
</main>
</body>
</html>
"""

# Fictional employer: "Lakeside Logistics Inc." — a made-up company.
# Seeded PostCheck violations (must match the postcheck output exactly):
#   * range $60,000 - $130,000: width $70,000 > $50,000 cap, and the top
#     does NOT exceed $200,000, so the exemption does not apply
#                                                -> POST-RANGE-WIDTH (high)
#   * no AI screening disclosure anywhere        -> POST-NO-AI (high)
#   * no vacancy statement anywhere              -> POST-NO-VACANCY (medium)
#   * "Canadian experience preferred." line      -> POST-CANADIAN-EXP (high)
# Expected totals: 4 findings — high 3, medium 1, low 0, info 0.
# NOTE: this text is matched by the checkers as-is, so it deliberately
# contains no explanatory header — the inventory lives here in code.
DEMO_POSTING_TXT = """Position: Warehouse Operations Supervisor
Company: Lakeside Logistics Inc.
Location: Toronto, Ontario (on site, five days a week)

About the role
Lakeside Logistics runs a 24-hour distribution centre near the Port of
Toronto. We are hiring a Warehouse Operations Supervisor to lead a team
of 18 shippers, receivers, and forklift operators on the afternoon
shift.

What you will do
- Plan daily outbound loads and assign dock doors
- Coach the team on safe lifting and equipment checks
- Track inventory accuracy in our warehouse system and close out
  discrepancies before end of shift

What we are looking for
- Three or more years supervising in a warehouse or distribution setting
- A valid forklift licence and comfort with handheld scanners
- Canadian experience preferred.
- Clear communication skills and a calm approach when the dock gets busy

Compensation
Salary range: $60,000 - $130,000 per year, depending on background.

How to apply
Send your resume to careers@lakesidelogistics.example by December 1, 2026.
"""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _parse_date(value):
    return datetime.date.fromisoformat(value)


def cmd_gen_demos(args):
    site_path = os.path.join(SCRIPT_DIR, "demo_site.html")
    posting_path = os.path.join(SCRIPT_DIR, "demo_posting.txt")
    with open(site_path, "w", encoding="utf-8") as fh:
        fh.write(DEMO_SITE_HTML)
    with open(posting_path, "w", encoding="utf-8") as fh:
        fh.write(DEMO_POSTING_TXT)
    print(f"Wrote fabricated demo inputs:\n  {site_path}\n  {posting_path}")
    return 0


def cmd_scan(args):
    today = _parse_date(args.today) if args.today \
        else datetime.date.today()
    target = args.target
    is_url = target.startswith(("http://", "https://"))
    if is_url:
        req = urllib.request.Request(
            target, headers={"User-Agent": "NorthCheck-Prototype/0.1"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html_text = resp.read().decode("utf-8", errors="replace")
        source_label = target
        out_dir = os.getcwd()
        stem = re.sub(r"[^A-Za-z0-9]+", "_", target).strip("_")[:40] \
            or "page"
    else:
        if not os.path.isfile(target):
            print(f"error: no such file: {target}", file=sys.stderr)
            return 2
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            html_text = fh.read()
        source_label = os.path.abspath(target)
        out_dir = os.path.dirname(os.path.abspath(target))
        stem = os.path.splitext(os.path.basename(target))[0]

    findings, stats = run_aoda_checks(html_text)
    meta = [
        ("Module", "AODA — web accessibility (WCAG 2.0)"),
        ("Target", source_label),
        ("Date scanned", today.isoformat()),
        ("Scan stats",
         f"{stats['images_total']} images "
         f"({stats['images_decorative']} decorative with empty alt), "
         f"{stats['controls_total']} form controls, "
         f"{stats['links_total']} links, "
         f"{stats['headings_total']} headings"),
    ]
    pack = render_evidence_pack("AODA web accessibility scan", meta,
                                findings)
    out_path = args.out or os.path.join(out_dir, f"{stem}_evidence_pack.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(pack)
    print(f"Scanned {target}")
    print(f"  {severity_summary_line(findings)}")
    print(f"  Evidence pack: {out_path}")
    return 0


def cmd_postcheck(args):
    if not os.path.isfile(args.file):
        print(f"error: no such file: {args.file}", file=sys.stderr)
        return 2
    with open(args.file, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    posted = _parse_date(args.date) if args.date \
        else (datetime.date.today())
    today = _parse_date(args.today) if args.today \
        else datetime.date.today()
    title, employer = parse_posting_meta(text, args.title, args.employer)
    nb = notify_by(posted)
    ru = retention_until(posted)

    findings, details = run_postcheck(text)
    meta = [
        ("Module", "PostCheck ON — Ontario job-posting rules "
                   "(O. Reg. 476/24)"),
        ("Posting", f"{title} — {employer}"),
        ("Source file", os.path.abspath(args.file)),
        ("Date posted", posted.isoformat()),
        ("Date checked", today.isoformat()),
        ("Compensation detected", details["compensation"]),
    ]
    extra = (
        "## Posting clocks (shared engine)\n\n"
        f"- **Interview-outcome notify-by:** {nb.isoformat()} "
        f"(date posted + 45 days) — every interviewed applicant must "
        "be told the outcome by this date.\n"
        f"- **Retention-until:** {ru.isoformat()} "
        "(date posted + 3 years) — keep this posting and its associated "
        "records at least until this date.\n\n"
        "## Corrected-draft suggestions\n\n"
        + corrected_draft_suggestions(findings)
    )
    report = render_evidence_pack("PostCheck ON job-posting check", meta,
                                  findings, extra_sections=extra)
    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.file)),
        os.path.splitext(os.path.basename(args.file))[0] + "_report.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(report)

    print(f"Checked {args.file}")
    print(f"  {severity_summary_line(findings)}")
    print(f"  Report: {out_path}")
    print(f"  Clocks: notify interviewed applicants by {nb.isoformat()}; "
          f"retain records until {ru.isoformat()}")
    if args.save:
        entry = {
            "title": title,
            "employer": employer,
            "date_posted": posted.isoformat(),
            "notify_by": nb.isoformat(),
            "retention_until": ru.isoformat(),
            "source_file": os.path.basename(args.file),
        }
        vault_path = os.path.join(SCRIPT_DIR, "vault.json")
        n = vault_save(entry, vault_path)
        print(f"  Saved to vault: {vault_path} ({n} posting(s) stored)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="northcheck",
        description="NorthCheck Phase 1 prototype — shared compliance "
                    "engine with AODA scan and PostCheck ON modules.")
    sub = ap.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser(
        "scan", help="AODA accessibility scan of an HTML file or URL")
    p_scan.add_argument("target", help="local HTML file path or http(s) URL")
    p_scan.add_argument("--out", help="evidence pack output path")
    p_scan.add_argument("--today",
                        help="scan date override (YYYY-MM-DD)")
    p_scan.set_defaults(func=cmd_scan)

    p_post = sub.add_parser(
        "postcheck", help="Ontario job-posting check (O. Reg. 476/24)")
    p_post.add_argument("file", help="job-posting text file")
    p_post.add_argument("--out", help="report output path")
    p_post.add_argument("--save", action="store_true",
                        help="append the posting to vault.json")
    p_post.add_argument("--date",
                        help="date posted (YYYY-MM-DD; default today)")
    p_post.add_argument("--today",
                        help="check date override (YYYY-MM-DD)")
    p_post.add_argument("--title", help="posting title override")
    p_post.add_argument("--employer", help="employer override")
    p_post.set_defaults(func=cmd_postcheck)

    p_demo = sub.add_parser(
        "gen-demos", help="write the fabricated demo inputs")
    p_demo.set_defaults(func=cmd_gen_demos)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
