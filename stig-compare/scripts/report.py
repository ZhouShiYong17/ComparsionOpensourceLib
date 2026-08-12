"""Self-contained HTML report. Verification-first.

Every piece of document text passes through esc(). No external assets: the
whole document -- markup, one <style> block, one <script> block -- lives in
a single file with zero network references, so it works from file:// with
no server.

render(run_dir) reads <run_dir>/final.json and writes <run_dir>/report.html,
returning its Path. Only stdlib is used (html, json, pathlib); nothing here
prints document text.
"""
import html
import json
from pathlib import Path


def esc(x):
    return html.escape(str(x if x is not None else ""))


_FEEDBACK_OPTIONS = ["", "correct", "incorrect", "wrong match",
                     "missed difference", "not meaningful",
                     "wrong classification", "other"]
_VERDICTS = ["Compliant", "Deviating", "Incomplete", "Ambiguous",
             "Cannot Assess"]
_CONFIDENCES = ["High", "Medium", "Low"]

_CSS = """
:root{--ok:#1a7f37;--bad:#b42318;--warn:#946200;--muted:#667085;
      font-family:Segoe UI,system-ui,sans-serif}
body{margin:0;padding:1.5rem;background:#f8fafc;color:#101828}
header{border-bottom:2px solid #d0d5dd;padding-bottom:1rem}
h1{font-size:1.4rem;margin:.6rem 0}
h2{border-bottom:1px solid #e4e7ec;padding-bottom:.3rem;margin-top:0}
h3{margin-bottom:.3rem}
section{margin:1.6rem 0}
.sensitive{background:#fef0c7;color:#7a2e0e;padding:.4rem .8rem;
           font-weight:600;display:inline-block;border-radius:4px}
.warning{background:#fffaeb;border-left:4px solid var(--warn);
         padding:.6rem .9rem;margin:.4rem 0}
.warning.red-banner{background:#fef3f2;border-left-color:var(--bad);
                    font-weight:700}
.tiles{display:flex;gap:.8rem;flex-wrap:wrap;margin:1rem 0}
.tile{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
      padding:.8rem 1.2rem;min-width:8rem;text-align:center}
.tile b{display:block;font-size:1.6rem}
.finding,.rollup{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
         padding:1rem;margin:.8rem 0}
.leftover-card{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
               padding:.7rem 1rem;margin:.6rem 0}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:.6rem 0}
.cols h4{margin-bottom:.3rem}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;
       font-size:.8rem;font-weight:600;margin-right:.4rem}
.badge.Compliant{background:#ecfdf3;color:var(--ok)}
.badge.Deviating{background:#fef3f2;color:var(--bad)}
.badge.Incomplete{background:#fff7e6;color:var(--warn)}
.badge.Ambiguous{background:#eef2ff;color:#3538cd}
.badge.Cannot-Assess{background:#eaecf0;color:var(--muted)}
.badge.confidence-High{background:#ecfdf3;color:var(--ok)}
.badge.confidence-Medium{background:#fff7e6;color:var(--warn)}
.badge.confidence-Low{background:#fef3f2;color:var(--bad)}
.badge.review{background:#fef0c7;color:#7a2e0e}
.badge.disputed{background:#fef3f2;color:var(--bad);border:1px solid var(--bad)}
.badge.revised{background:#eef2ff;color:#3538cd;border:1px solid #3538cd}
.badge.change-tag{background:#eef2ff;color:#3538cd}
.badge-claim{background:#7a1f1f;color:#fff;border-radius:3px;padding:1px 6px;margin-left:6px;font-size:11px}
.badge-sweep{background:#5b4a12;color:#fff;border-radius:3px;padding:1px 6px;margin-left:6px;font-size:11px}
.interpretation{background:#f2f4f7;border-left:3px solid #3538cd;
                padding:.4rem .7rem;margin:.3rem 0}
.interp{border-left:3px solid #888;padding:4px 8px;margin:6px 0;font-style:italic;opacity:.85}
.quote{background:#f2f4f7;border-left:3px solid #98a2b3;padding:.3rem .6rem;
       font-family:Consolas,monospace;font-size:.85rem;white-space:pre-wrap}
.quote-label{font-size:.75rem;color:var(--muted);text-transform:uppercase;
             letter-spacing:.04em;margin-top:.5rem}
.validation{background:#f8f9fc;border:1px solid #d0d5dd;border-left:4px solid #3538cd;
            padding:.5rem .8rem;margin:.4rem 0;border-radius:4px}
.rel-ok{color:var(--ok);font-weight:700}
.rel-bad{color:var(--bad);font-weight:700}
.rel-muted{color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:.4rem 0}
td,th{border:1px solid #e4e7ec;padding:.3rem .6rem;font-size:.85rem;
      text-align:left;vertical-align:top}
th{background:#f9fafb}
.triage-table td,.triage-table th{padding:4px 8px;border-bottom:1px solid #333}
.hidden{display:none}
.filters{margin:.6rem 0 1rem;display:flex;gap:1rem;flex-wrap:wrap;
         align-items:center;font-size:.85rem}
.filter{cursor:pointer;border:1px solid #d0d5dd;background:#fff;
        border-radius:999px;padding:.2rem .7rem;font-size:.8rem}
.filter.active{background:#101828;color:#fff;border-color:#101828}
.fb-row{display:flex;gap:.6rem;align-items:center;margin-top:.8rem;
        flex-wrap:wrap}
.fb-comment{flex:1;min-width:12rem;padding:.3rem .5rem}
.btn{background:#101828;color:#fff;border:none;border-radius:6px;
     padding:.5rem 1rem;font-size:.9rem;cursor:pointer}
details{margin:.5rem 0}
details>summary{cursor:pointer;font-weight:600}
"""

_JS = """
function applyFilters(){
  var active = {};
  document.querySelectorAll('.filter.active').forEach(function(b){
    var g = b.dataset.group;
    if(!active[g]) active[g] = [];
    active[g].push(b.dataset.value);
  });
  document.querySelectorAll('.finding').forEach(function(f){
    var visible = true;
    Object.keys(active).forEach(function(g){
      var vals = active[g];
      if(vals.length && vals.indexOf(f.dataset[g]) === -1){
        visible = false;
      }
    });
    f.classList.toggle('hidden', !visible);
  });
}
document.querySelectorAll('.filter').forEach(function(b){
  b.addEventListener('click', function(){
    b.classList.toggle('active');
    applyFilters();
  });
});
function exportFeedback(){
  var items = [];
  document.querySelectorAll('.finding, .rollup').forEach(function(f){
    var sel = f.querySelector('.fb');
    var c = f.querySelector('.fb-comment');
    if(sel && sel.value){
      items.push({finding_id: f.dataset.fid, classification: sel.value,
                  comment: c ? c.value : ''});
    }
  });
  var payload = JSON.stringify({run: window.RUN_META, feedback: items}, null, 1);
  var a = document.createElement('a');
  a.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(payload);
  a.download = 'feedback.json';
  a.click();
}
var exportBtn = document.getElementById('exportBtn');
if(exportBtn){ exportBtn.addEventListener('click', exportFeedback); }
"""


def _verdict_css(verdict):
    return (verdict or "Unknown").replace(" ", "-")


def _json_for_script(obj):
    # Defense in depth: obj is a small manifest subset (filenames, hashes,
    # versions), never document content, but a hostile filename could still
    # smuggle "</script>" -- neutralize it regardless.
    return json.dumps(obj, ensure_ascii=True).replace("</", "<\\/")


def _kv_rows(pairs):
    return "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in pairs)


def _source_ref_str(ref):
    ref = ref or {}
    return ", ".join(f"{esc(k)}={esc(v)}" for k, v in ref.items()) or "n/a"


# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------

def _header_html(manifest):
    versions = manifest.get("versions", {}) or {}
    prompt_hashes = versions.get("prompt_hashes", {}) or {}
    version_rows = _kv_rows((k, v) for k, v in versions.items()
                            if k != "prompt_hashes")
    ph_rows = _kv_rows(sorted(prompt_hashes.items())) or \
        "<tr><td colspan=\"2\">none</td></tr>"
    return f"""
<header>
  <span class="sensitive">CONTAINS SENSITIVE DOCUMENT CONTENT</span>
  <h1>STIG Comparison Report</h1>
  <table>
    <tr><th>Official file</th><td>{esc(manifest.get('official_file'))}</td></tr>
    <tr><th>Official SHA-256</th><td><code>{esc(manifest.get('official_sha256'))}</code></td></tr>
    <tr><th>Company file</th><td>{esc(manifest.get('company_file'))}</td></tr>
    <tr><th>Company SHA-256</th><td><code>{esc(manifest.get('company_sha256'))}</code></td></tr>
    <tr><th>Run started</th><td>{esc(manifest.get('started'))}</td></tr>
  </table>
  <h3>Component versions</h3>
  <table>{version_rows}</table>
  <h3>Prompt hashes</h3>
  <table>{ph_rows}</table>
</header>
"""


# --------------------------------------------------------------------------
# warnings (always rendered, never collapsible)
# --------------------------------------------------------------------------

def _warning_item(w):
    if not isinstance(w, dict):
        return f'<div class="warning">{esc(w)}</div>'
    code = w.get("code", "unknown")
    cls = "warning red-banner" if code == "low-coverage-red-banner" else "warning"
    extras = {k: v for k, v in w.items() if k != "code"}
    extras_html = "".join(
        f' <span><b>{esc(k)}:</b> {esc(v)}</span>' for k, v in extras.items())
    return f'<div class="{cls}"><strong>{esc(code)}</strong>{extras_html}</div>'


def _warnings_html(final):
    top = final.get("warnings", []) or []
    cov_warnings = (final.get("coverage", {}) or {}).get("warnings", []) or []
    combined = list(top)
    for w in cov_warnings:
        if w not in combined:
            combined.append(w)
    if not combined:
        body = '<div class="warning">No warnings.</div>'
    else:
        body = "".join(_warning_item(w) for w in combined)
    return f'<section id="warnings"><h2>Warnings</h2>{body}</section>'


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

def _tile(label, value):
    return f'<div class="tile"><b>{esc(value)}</b>{esc(label)}</div>'


def _dashboard_html(final):
    findings = final.get("findings", []) or []
    coverage = final.get("coverage", {}) or {}
    company_cov = coverage.get("company", {}) or {}
    official_cov = coverage.get("official", {}) or {}

    verdict_counts = {}
    for f in findings:
        v = f.get("verdict") or "Unknown"
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    tiles = "".join(
        [_tile(v, verdict_counts.get(v, 0)) for v in _VERDICTS] +
        [_tile("Unmatched rows", company_cov.get(
            "unmatched", len(final.get("unmatched_rows", []) or []))),
         _tile("Unresolved", company_cov.get("unresolved", 0)),
         _tile("Unaddressed rules", official_cov.get(
             "unaddressed", len(final.get("unaddressed_rules", []) or [])))])

    company_rows = list(company_cov.items())
    official_rows = []
    for k, v in official_cov.items():
        if k == "multi_matched_row_ids":
            v = ", ".join(v) if v else "none"
        official_rows.append((k, v))

    return f"""
<section id="dashboard">
  <h2>Dashboard</h2>
  <div class="tiles">{tiles}</div>
  <h3>Company row coverage</h3>
  <table>{_kv_rows(company_rows)}</table>
  <h3>Official row coverage</h3>
  <table>{_kv_rows(official_rows)}</table>
</section>
"""


# --------------------------------------------------------------------------
# triage
# --------------------------------------------------------------------------

def _triage_html(final):
    rows = []
    for t in final.get("table_triage", []):
        cls = esc(str(t.get("classification")))
        rows.append(
            f"<tr><td>{t['table_index']}</td>"
            f"<td>{esc(t.get('sheet_or_section', ''))}</td>"
            f"<td>{cls}</td>"
            f"<td>{esc(t.get('irrelevant_reason', ''))}</td>"
            f"<td>{esc(t.get('context_grouping', ''))}</td>"
            f"<td>{t.get('row_count', 0)}</td></tr>")
    if not rows:
        return ""
    return ("<section><h2>Table triage</h2>"
            "<table class='triage-table'><tr><th>#</th><th>Location</th>"
            "<th>Classification</th><th>Reason</th><th>Grouping</th>"
            "<th>Rows</th></tr>" + "".join(rows) + "</table></section>")


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------

def _filters_html():
    def _btns(group, values, labels=None):
        labels = labels or values
        return "".join(
            f'<button type="button" class="filter" data-group="{esc(group)}" '
            f'data-value="{esc(v)}">{esc(l)}</button>'
            for v, l in zip(values, labels))
    return f"""
<div class="filters">
  <span>Verdict:</span> {_btns('verdict', _VERDICTS)}
  <span>Confidence:</span> {_btns('confidence', _CONFIDENCES)}
  <span>Review:</span> {_btns('review', ['true', 'false'],
                              ['Needs review', 'No review needed'])}
</div>
"""


def _company_row_html(company):
    """The COMPLETE company row: header/cells table, continuation rows,
    narrative context, and the additive canonical-field aids."""
    company = company or {}
    headers = company.get("header_row", []) or []
    cells = company.get("cells", []) or []
    ncols = max(len(headers), len(cells))
    head = "".join(f"<th>{esc(headers[i] if i < len(headers) else '')}</th>"
                   for i in range(ncols))
    body = "".join(f"<td>{esc(cells[i] if i < len(cells) else '')}</td>"
                   for i in range(ncols))
    rows = [f"<tr>{head}</tr>", f"<tr>{body}</tr>"]
    for cont in company.get("continuation_cells", []) or []:
        cont_cells = cont.get("cells", []) or []
        body = "".join(
            f"<td>{esc(cont_cells[i] if i < len(cont_cells) else '')}</td>"
            for i in range(ncols))
        rows.append(f"<tr>{body}</tr>")
    table = f"<table>{''.join(rows)}</table>"
    narrative = company.get("preceding_narrative", "")
    narrative_html = (f'<p><b>Context:</b> {esc(narrative)}</p>'
                      if narrative else "")
    aids = company.get("canonical_fields", {}) or {}
    aids_html = ""
    if aids:
        aids_html = (
            "<details><summary>Canonical field aids</summary>"
            f"<table>{_kv_rows(sorted(aids.items()))}</table></details>")
    return (f"{narrative_html}{table}"
            f"<p><b>Source:</b> {_source_ref_str(company.get('source_reference'))}"
            f" &mdash; <b>Claim reading:</b> "
            f"{esc(company.get('company_claim_reading'))}</p>{aids_html}")


def _official_row_html(official):
    """The COMPLETE official row: every column verbatim."""
    official = official or {}
    raw = official.get("raw_record", {}) or {}
    rows = _kv_rows(raw.items()) or "<tr><td colspan=\"2\">none</td></tr>"
    prov = official.get("provenance", {}) or {}
    return (f"<table>{rows}</table>"
            f"<p><b>Location:</b> {esc(prov.get('source_file'))} "
            f"({esc(prov.get('locator'))})</p>")


def _alignment_html(field_alignment):
    if not field_alignment:
        return ""
    rows = []
    for a in field_alignment:
        if not isinstance(a, dict):
            continue
        rel = a.get("relation")
        cls = {"identical": "rel-ok", "equivalent": "rel-ok",
               "differs": "rel-bad", "company-missing": "rel-bad",
               "official-missing": "rel-muted"}.get(rel, "rel-muted")
        rows.append(
            f"<tr><td>{esc(a.get('company_ref'))}</td>"
            f"<td class='quote'>{esc(a.get('company_quote'))}</td>"
            f"<td>{esc(a.get('official_column'))}</td>"
            f"<td class='quote'>{esc(a.get('official_quote'))}</td>"
            f"<td><span class='{cls}'>{esc(rel)}</span></td></tr>")
    return ("<h4>Field alignment</h4>"
            "<table><tr><th>Company field</th><th>Company text</th>"
            "<th>Official column</th><th>Official text</th>"
            f"<th>Relation</th></tr>{''.join(rows)}</table>")


def _validation_html(validation):
    if not validation:
        return '<div class="validation">No validation recorded.</div>'
    if "status" in validation:
        return (f'<div class="validation"><b>Status:</b> '
                f'{esc(validation["status"])}</div>')
    parts = [f"<b>Outcome:</b> {esc(validation.get('outcome'))}",
             f"<b>Independent verdict:</b> "
             f"{esc(validation.get('independent_verdict'))}"]
    if validation.get("revised_verdict"):
        parts.append(f"<b>Revised verdict:</b> "
                     f"{esc(validation.get('revised_verdict'))}")
    if validation.get("reason"):
        parts.append(f"<b>Reason:</b> {esc(validation.get('reason'))}")
    body = "<br>".join(parts)
    quote = validation.get("evidence_quote")
    quote_html = (f'<div class="quote-label">Evidence quote</div>'
                  f'<div class="quote">{esc(quote)}</div>' if quote else "")
    return f'<div class="validation">{body}{quote_html}</div>'


def _feedback_row_html():
    fb_options = "".join(
        f'<option value="{esc(o)}">{esc(o) if o else "(select)"}</option>'
        for o in _FEEDBACK_OPTIONS)
    return f"""
  <div class="fb-row">
    <label>Feedback:
      <select class="fb">{fb_options}</select>
    </label>
    <input class="fb-comment" type="text" placeholder="Comment (optional)">
  </div>
"""


def _finding_html(f):
    verdict = f.get("verdict") or "Unknown"
    confidence = f.get("confidence") or "Unknown"
    review = bool(f.get("human_review_needed"))
    disputed = bool(f.get("disputed"))
    company = f.get("company_row", {}) or {}
    official = f.get("official_row", {}) or {}

    badges = [
        f'<span class="badge {esc(_verdict_css(verdict))}">{esc(verdict)}</span>',
        f'<span class="badge confidence-{esc(confidence)}">'
        f'confidence: {esc(confidence)}</span>',
    ]
    if f.get("verdict_source") == "validation-revised":
        badges.append(
            f'<span class="badge revised">REVISED by validation &mdash; '
            f'first pass: {esc(f.get("first_pass_verdict"))}</span>')
    for tag in f.get("change_analysis", []) or []:
        badges.append(f'<span class="badge change-tag">{esc(tag)}</span>')
    if review:
        badges.append('<span class="badge review">HUMAN REVIEW NEEDED</span>')
    if disputed:
        badges.append(
            '<span class="badge disputed">DISPUTED &mdash; validation '
            'refuted</span>')
    claim_badges = ""
    if f.get("claim_reading") == "deviation":
        claim_badges += '<span class="badge-claim">company-declared-deviation</span>'
    if f.get("claim_consistency") == "contradicted":
        claim_badges += '<span class="badge-claim">claim-contradicted</span>'
    sweep_badge = (
        '<span class="badge-sweep">sweep-originated</span>'
        if f.get("sweep_originated") else '')

    reasons = f.get("review_reasons", []) or []
    reasons_html = (f"<p><b>Review reasons:</b> "
                    f"{', '.join(esc(r) for r in reasons)}</p>"
                    if reasons else "")

    note = f.get("company_row", {}).get("interpretation_note", "")
    note_html = (f'<div class="interp"><b>Interpretation (not evidence):</b> '
                 f'{esc(note)}</div>' if note else "")
    record_notes = f.get("record_notes", "")
    record_notes_html = (
        f'<div class="interp"><b>Record notes:</b> {esc(record_notes)}</div>'
        if record_notes else "")

    display_id = f.get("display_id") or f.get("official_row_id")
    return f"""
<article class="finding" data-fid="{esc(f.get('finding_id'))}" data-verdict="{esc(verdict)}" data-confidence="{esc(confidence)}" data-review="{'true' if review else 'false'}">
  <div>{"".join(badges)}{claim_badges}{sweep_badge}</div>
  <p><b>Finding ID:</b> {esc(f.get('finding_id'))} &mdash;
     <b>Row:</b> {esc(f.get('record_id'))} &mdash;
     <b>Official row:</b> {esc(display_id)}</p>
  <div class="cols">
    <div>
      <h4>Company submission (complete row)</h4>
      {_company_row_html(company)}
    </div>
    <div>
      <h4>Official row {esc(display_id)} (all columns)</h4>
      {_official_row_html(official)}
    </div>
  </div>
  <h4>Evidence quotes</h4>
  <div class="quote-label">Company row quote</div>
  <div class="quote">{esc(f.get('row_quote'))}</div>
  <div class="quote-label">Official row quote</div>
  <div class="quote">{esc(f.get('official_quote'))}</div>
  {_alignment_html(f.get('field_alignment'))}
  <h4>Match rationale</h4>
  <div class="interpretation">{esc(f.get('match_rationale'))}</div>
  <h4>Semantic differences</h4>
  <div class="interpretation">{esc(f.get('semantic_differences'))}</div>
  <h4>Reasoning</h4>
  <div class="interpretation">{esc(f.get('reasoning'))}</div>
  {note_html}
  {record_notes_html}
  <h4>Validation</h4>
  {_validation_html(f.get('validation'))}
  {reasons_html}
  {_feedback_row_html()}
</article>
"""


def _findings_section_html(final):
    findings = final.get("findings", []) or []
    body = "".join(_finding_html(f) for f in findings) or "<p>No findings.</p>"
    return (f'<section id="findings"><h2>Findings</h2>{_filters_html()}'
           f'<div id="findingsList">{body}</div></section>')


# --------------------------------------------------------------------------
# rule rollups
# --------------------------------------------------------------------------

def _rollup_html(r):
    verdict = r.get("verdict")
    status = r.get("status")
    review = bool(r.get("human_review_needed"))
    badges = []
    if verdict:
        badges.append(
            f'<span class="badge {esc(_verdict_css(verdict))}">joint: '
            f'{esc(verdict)}</span>')
        badges.append(
            f'<span class="badge change-tag">'
            f'{esc(r.get("coverage_of_requirement"))}</span>')
    if status:
        badges.append(f'<span class="badge Cannot-Assess">{esc(status)}</span>')
    if review:
        badges.append('<span class="badge review">HUMAN REVIEW NEEDED</span>')
    contributors = ", ".join(esc(c) for c in
                             r.get("contributing_record_ids", []) or [])
    reasoning_html = (f'<div class="interpretation">{esc(r.get("reasoning"))}'
                      f'</div>' if r.get("reasoning") else "")
    reasons = r.get("review_reasons", []) or []
    reasons_html = (f"<p><b>Review reasons:</b> "
                    f"{', '.join(esc(x) for x in reasons)}</p>"
                    if reasons else "")
    return f"""
<article class="rollup" data-fid="{esc(r.get('rollup_id'))}">
  <div>{"".join(badges)}</div>
  <p><b>Rollup:</b> {esc(r.get('rollup_id'))} &mdash;
     <b>Official row:</b> {esc(r.get('display_id') or r.get('official_row_id'))}
     &mdash; <b>Contributing rows:</b> {contributors}</p>
  {reasoning_html}
  <h4>Validation</h4>
  {_validation_html(r.get('validation'))}
  {reasons_html}
  {_feedback_row_html()}
</article>
"""


def _rollups_section_html(final):
    rollups = final.get("rule_rollups", []) or []
    if not rollups:
        return ""
    body = "".join(_rollup_html(r) for r in rollups)
    return (f'<section id="rollups"><h2>Rule rollups '
            f'(one official row, several company rows)</h2>{body}</section>')


# --------------------------------------------------------------------------
# leftovers -- ambiguous / unresolved always visible; bulk lists collapsible
# --------------------------------------------------------------------------

def _ambiguous_html(final):
    items = final.get("ambiguous", []) or []
    if not items:
        return "<p>No ambiguous matches.</p>"
    cards = []
    for a in items:
        ids = ", ".join(esc(r) for r in
                        a.get("ambiguous_official_row_ids", []) or [])
        cards.append(f"""
<div class="leftover-card">
  <span class="badge review">HUMAN REVIEW NEEDED</span>
  <p><b>Row:</b> {esc(a.get('record_id', ''))} &mdash;
     <b>Source:</b> {_source_ref_str(a.get('source_reference'))}</p>
  <div class="quote">{esc(a.get('original_company_text'))}</div>
  <p><b>Ambiguous between:</b> {ids}</p>
  <p><b>Basis:</b> {esc(a.get('basis'))}</p>
</div>
""")
    return "".join(cards)


def _unresolved_html(final):
    items = final.get("unresolved_rows", []) or []
    if not items:
        return "<p>No unresolved rows.</p>"
    cards = []
    for r in items:
        cards.append(f"""
<div class="leftover-card">
  <span class="badge review">HUMAN REVIEW NEEDED</span>
  <p><b>Row:</b> {esc(r.get('record_id', ''))} &mdash;
     <b>Status:</b> {esc(r.get('status'))} &mdash;
     <b>Source:</b> {_source_ref_str(r.get('source_reference'))}</p>
  <p><b>Notes:</b> {esc(r.get('notes'))}</p>
  <div class="quote">{esc(r.get('original_company_text'))}</div>
</div>
""")
    return "".join(cards)


def _unresolved_pairs_html(final):
    items = final.get("unresolved_pairs", []) or []
    if not items:
        return "<p>No unresolved pairs.</p>"
    rows = "".join(
        f"<tr><td>{esc(p.get('record_id'))}</td>"
        f"<td>{esc(p.get('official_row_id'))}</td>"
        f"<td>{esc(p.get('status'))}</td></tr>"
        for p in items)
    return ("<table><tr><th>Record</th><th>Official row</th><th>Status</th>"
            f"</tr>{rows}</table>")


def _unmatched_html(final):
    items = final.get("unmatched_rows", []) or []
    if not items:
        return "<p>No unmatched company rows.</p>"
    cards = []
    for r in items:
        warns = ", ".join(esc(w) for w in r.get("warnings", []) or []) or "none"
        cards.append(f"""
<div class="leftover-card">
  <p><b>Row:</b> {esc(r.get('record_id', ''))} &mdash;
     <b>Source:</b> {_source_ref_str(r.get('source_reference'))}</p>
  <div class="quote">{esc(r.get('original_company_text'))}</div>
  <p><b>Basis:</b> {esc(r.get('basis'))} &mdash; <b>Warnings:</b> {warns}</p>
</div>
""")
    return "".join(cards)


def _unaddressed_html(final):
    items = final.get("unaddressed_rules", []) or []
    if not items:
        return "<p>No unaddressed official rows.</p>"
    rows = []
    for r in items:
        raw = r.get("raw_record", {}) or {}
        content = "; ".join(f"{k}: {v}" for k, v in raw.items())
        prov = r.get("provenance", {}) or {}
        rows.append(
            f"<tr><td>{esc(r.get('display_id') or r.get('official_row_id'))}"
            f"</td><td>{esc(prov.get('locator'))}</td>"
            f"<td>{esc(content)}</td></tr>")
    return ("<table><tr><th>ID</th><th>Location</th><th>Content "
            f"(all columns)</th></tr>{''.join(rows)}</table>")


def _leftovers_html(final):
    n_unmatched = len(final.get("unmatched_rows", []) or [])
    n_unaddressed = len(final.get("unaddressed_rules", []) or [])
    return f"""
<section id="leftovers">
  <h2>Leftovers</h2>

  <h3>Ambiguous matches</h3>
  {_ambiguous_html(final)}

  <h3>Unresolved rows</h3>
  {_unresolved_html(final)}

  <h3>Unresolved pairs</h3>
  {_unresolved_pairs_html(final)}

  <details>
    <summary>Unmatched company rows ({esc(n_unmatched)})</summary>
    {_unmatched_html(final)}
  </details>

  <details>
    <summary>Unaddressed official rows ({esc(n_unaddressed)})</summary>
    {_unaddressed_html(final)}
  </details>
</section>
"""


# --------------------------------------------------------------------------
# feedback export
# --------------------------------------------------------------------------

def _feedback_export_html():
    return """
<section id="feedback-export">
  <h2>Feedback export</h2>
  <p>Select a classification (and optional comment) on any finding above,
     then export. The file downloads via a data URI -- no server needed,
     works even when this report was opened directly from disk.</p>
  <button type="button" id="exportBtn" class="btn">Export feedback</button>
</section>
"""


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def render(run_dir):
    run_dir = Path(run_dir)
    final = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
    manifest = final.get("manifest", {}) or {}

    run_meta = {
        "official_file": manifest.get("official_file"),
        "company_file": manifest.get("company_file"),
        "official_sha256": manifest.get("official_sha256"),
        "company_sha256": manifest.get("company_sha256"),
        "started": manifest.get("started"),
        "versions": manifest.get("versions"),
    }

    body = (
        _header_html(manifest)
        + _warnings_html(final)
        + _dashboard_html(final)
        + _triage_html(final)
        + _findings_section_html(final)
        + _rollups_section_html(final)
        + _leftovers_html(final)
        + _feedback_export_html()
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>STIG Comparison Report</title>
<style>{_CSS}</style>
</head>
<body>
{body}
<script>
window.RUN_META = {_json_for_script(run_meta)};
{_JS}
</script>
</body>
</html>
"""
    out_path = run_dir / "report.html"
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
