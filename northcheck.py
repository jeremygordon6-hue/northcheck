#!/usr/bin/env python3
"""
NorthCheck — Phase 1 prototype: a combined Canadian SMB compliance platform.

One shared engine, multiple compliance modules:

    input -> deterministic rule checks -> plain-English findings
          -> dated evidence pack -> deadline clocks / monitoring

Phase 1 builds two modules on that engine:

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
