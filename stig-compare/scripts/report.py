"""Self-contained HTML report. Verification-first (spec section 8).

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
_VERDICTS = ["Compliant", "Non-Compliant", "Cannot Assess"]
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
.finding{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
         padding:1rem;margin:.8rem 0}
.leftover-card{background:#fff;border:1px solid #d0d5dd;border-radius:8px;
               padding:.7rem 1rem;margin:.6rem 0}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:.6rem 0}
.cols h4{margin-bottom:.3rem}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;
       font-size:.8rem;font-weight:600;margin-right:.4rem}
.badge.Compliant{background:#ecfdf3;color:var(--ok)}
.badge.Non-Compliant{background:#fef3f2;color:var(--bad)}
.badge.Cannot-Assess{background:#eaecf0;color:var(--muted)}
.badge.confidence-High{background:#ecfdf3;color:var(--ok)}
.badge.confidence-Medium{background:#fff7e6;color:var(--warn)}
.badge.confidence-Low{background:#fef3f2;color:var(--bad)}
.badge.review{background:#fef0c7;color:#7a2e0e}
.badge.disputed{background:#fef3f2;color:var(--bad);border:1px solid var(--bad)}
.badge.finding-type{background:#eef2ff;color:#3538cd}
.interpretation{background:#f2f4f7;border-left:3px solid #3538cd;
                padding:.4rem .7rem;margin:.3rem 0}
.quote{background:#f2f4f7;border-left:3px solid #98a2b3;padding:.3rem .6rem;
       font-family:Consolas,monospace;font-size:.85rem;white-space:pre-wrap}
.quote-label{font-size:.75rem;color:var(--muted);text-transform:uppercase;
             letter-spacing:.04em;margin-top:.5rem}
.rel-ok{color:var(--ok);font-weight:700}
.rel-bad{color:var(--bad);font-weight:700}
.rel-muted{color:var(--muted)}
table{border-collapse:collapse;width:100%;margin:.4rem 0}
td,th{border:1px solid #e4e7ec;padding:.3rem .6rem;font-size:.85rem;
      text-align:left}
th{background:#f9fafb}
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
  document.querySelectorAll('.finding').forEach(function(f){
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
    <tr><th>Rule registry version</th><td>{esc(manifest.get('registry_version'))}</td></tr>
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

    tiles = "".join([
        _tile("Compliant", verdict_counts.get("Compliant", 0)),
        _tile("Non-Compliant", verdict_counts.get("Non-Compliant", 0)),
        _tile("Cannot Assess", verdict_counts.get("Cannot Assess", 0)),
        _tile("Ambiguous", company_cov.get(
            "ambiguous", len(final.get("ambiguous", []) or []))),
        _tile("Unmatched rows", company_cov.get(
            "unmatched", len(final.get("unmatched_rows", []) or []))),
        _tile("Unaddressed rules", official_cov.get(
            "unaddressed", len(final.get("unaddressed_rules", []) or []))),
    ])

    company_rows = list(company_cov.items())
    official_rows = []
    for k, v in official_cov.items():
        if k == "duplicate_coverage_rule_ids":
            v = ", ".join(v) if v else "none"
        official_rows.append((k, v))

    return f"""
<section id="dashboard">
  <h2>Dashboard</h2>
  <div class="tiles">{tiles}</div>
  <h3>Company row coverage</h3>
  <table>{_kv_rows(company_rows)}</table>
  <h3>Official rule coverage</h3>
  <table>{_kv_rows(official_rows)}</table>
</section>
"""


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


def _score_table(candidates):
    if not candidates:
        return "<p>No candidate rules were scored.</p>"
    rows = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        feats = c.get("features")
        feat_str = ", ".join(f"{esc(k)}={esc(v)}" for k, v in feats.items()) \
            if isinstance(feats, dict) else ""
        rows.append(f"<tr><td>{esc(c.get('rule_id'))}</td>"
                    f"<td>{esc(c.get('score'))}</td><td>{feat_str}</td></tr>")
    return ("<table><tr><th>Candidate rule ID</th><th>Score</th>"
            f"<th>Features (why matched)</th></tr>{''.join(rows)}</table>")


def _observation_html(observation):
    if not observation:
        return "<p>No observation recorded.</p>"
    parts = []
    for k, v in observation.items():
        if k in ("row_quote", "rule_quote") and v:
            label = "Row quote" if k == "row_quote" else "Rule quote"
            parts.append(f'<div class="quote-label">{esc(label)}</div>'
                        f'<div class="quote">{esc(v)}</div>')
        elif k == "relation":
            cls = {"satisfies": "rel-ok",
                  "violates": "rel-bad"}.get(v, "rel-muted")
            parts.append(f'<div><b>Relation:</b> '
                        f'<span class="{cls}">{esc(v)}</span></div>')
        else:
            parts.append(f"<div><b>{esc(str(k).replace('_', ' ').title())}:"
                        f"</b> {esc(v)}</div>")
    return "".join(parts)


def _finding_html(f):
    verdict = f.get("verdict") or "Unknown"
    confidence = f.get("confidence") or "Unknown"
    review = bool(f.get("human_review_needed"))
    disputed = bool(f.get("disputed"))
    finding_type = f.get("finding_type")
    interpretation = f.get("interpretation")
    company = f.get("company_row", {}) or {}
    official = f.get("official_rule", {}) or {}
    match = f.get("match", {}) or {}
    skeptic = f.get("skeptic")
    applied_rules = f.get("applied_rules", []) or []

    badges = [
        f'<span class="badge {esc(_verdict_css(verdict))}">{esc(verdict)}</span>',
        f'<span class="badge confidence-{esc(confidence)}">'
        f'confidence: {esc(confidence)}</span>',
    ]
    if finding_type:
        # Surfaces the semantic classification (spec section 5) -- without
        # this, the "wrong classification" feedback option has nothing on
        # the card for a reviewer to judge as right or wrong.
        badges.append(
            f'<span class="badge finding-type">type: {esc(finding_type)}</span>')
    if review:
        badges.append('<span class="badge review">HUMAN REVIEW NEEDED</span>')
    if disputed:
        badges.append(
            '<span class="badge disputed">DISPUTED &mdash; skeptic refuted'
            '</span>')

    if skeptic:
        skeptic_html = (f"<p><b>Outcome:</b> {esc(skeptic.get('outcome'))}"
                        f"<br><b>Reason:</b> {esc(skeptic.get('reason'))}</p>")
    else:
        skeptic_html = "<p>No skeptic review recorded.</p>"

    applied_html = ", ".join(esc(r) for r in applied_rules) if applied_rules \
        else "none"

    interpretation_html = (
        f'<h4>Interpretation</h4><div class="interpretation">'
        f'{esc(interpretation)}</div>' if interpretation else "")

    fb_options = "".join(
        f'<option value="{esc(o)}">{esc(o) if o else "(select)"}</option>'
        for o in _FEEDBACK_OPTIONS)

    return f"""
<article class="finding" data-fid="{esc(f.get('finding_id'))}" data-verdict="{esc(verdict)}" data-confidence="{esc(confidence)}" data-review="{'true' if review else 'false'}">
  <div>{"".join(badges)}</div>
  <p><b>Finding ID:</b> {esc(f.get('finding_id'))} &mdash;
     <b>Row:</b> {esc(f.get('row_id'))} &mdash;
     <b>Rule:</b> {esc(f.get('rule_id'))} &mdash;
     <b>Basis:</b> {esc(f.get('basis'))}</p>
  <div class="cols">
    <div>
      <h4>Company submission</h4>
      <div class="quote-label">Original text</div>
      <div class="quote">{esc(company.get('original_company_text'))}</div>
      <p><b>Source:</b> {_source_ref_str(company.get('source_reference'))}</p>
    </div>
    <div>
      <h4>Official rule {esc(official.get('rule_id'))}</h4>
      <p><b>Title:</b> {esc(official.get('title'))}</p>
      <p><b>Check text:</b> {esc(official.get('check_text'))}</p>
      <p><b>Expected value:</b> {esc(official.get('expected_value'))}</p>
    </div>
  </div>
  <h4>Evidence</h4>
  {_observation_html(f.get('observation'))}
  {interpretation_html}
  <h4>Match</h4>
  <p><b>Tier:</b> {esc(match.get('tier'))}</p>
  {_score_table(match.get('candidates'))}
  <h4>Skeptic review</h4>
  {skeptic_html}
  <h4>Applied rules</h4>
  <p>{applied_html}</p>
  <div class="fb-row">
    <label>Feedback:
      <select class="fb">{fb_options}</select>
    </label>
    <input class="fb-comment" type="text" placeholder="Comment (optional)">
  </div>
</article>
"""


def _findings_section_html(final):
    findings = final.get("findings", []) or []
    body = "".join(_finding_html(f) for f in findings) or "<p>No findings.</p>"
    return (f'<section id="findings"><h2>Findings</h2>{_filters_html()}'
           f'<div id="findingsList">{body}</div></section>')


# --------------------------------------------------------------------------
# leftovers -- ambiguous / unresolved always visible; bulk lists collapsible
# --------------------------------------------------------------------------

def _ambiguous_html(final):
    items = final.get("ambiguous", []) or []
    if not items:
        return "<p>No ambiguous matches.</p>"
    cards = []
    for a in items:
        ids = ", ".join(esc(r) for r in a.get("ambiguous_rule_ids", []) or [])
        cards.append(f"""
<div class="leftover-card">
  <span class="badge review">HUMAN REVIEW NEEDED</span>
  <p><b>Row:</b> {esc(a.get('row_id'))} &mdash;
     <b>Source:</b> {_source_ref_str(a.get('source_reference'))}</p>
  <div class="quote">{esc(a.get('original_company_text'))}</div>
  <p><b>Ambiguous between:</b> {ids}</p>
  {_score_table(a.get('candidates'))}
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
  <p><b>Row:</b> {esc(r.get('row_id'))} &mdash;
     <b>Status:</b> {esc(r.get('status'))} &mdash;
     <b>Source:</b> {_source_ref_str(r.get('source_reference'))}</p>
  <p><b>Notes:</b> {esc(r.get('notes'))}</p>
  <div class="quote">{esc(r.get('original_company_text'))}</div>
</div>
""")
    return "".join(cards)


def _unmatched_html(final):
    items = final.get("unmatched_rows", []) or []
    if not items:
        return "<p>No unmatched company rows.</p>"
    cards = []
    for r in items:
        warns = ", ".join(esc(w) for w in r.get("warnings", []) or []) or "none"
        cards.append(f"""
<div class="leftover-card">
  <p><b>Row:</b> {esc(r.get('row_id'))} &mdash;
     <b>Source:</b> {_source_ref_str(r.get('source_reference'))}</p>
  <div class="quote">{esc(r.get('original_company_text'))}</div>
  <p><b>Warnings:</b> {warns}</p>
</div>
""")
    return "".join(cards)


def _unaddressed_html(final):
    items = final.get("unaddressed_rules", []) or []
    if not items:
        return "<p>No unaddressed official rules.</p>"
    rows = "".join(
        f"<tr><td>{esc(r.get('rule_id'))}</td><td>{esc(r.get('title'))}</td>"
        f"<td>{esc(r.get('check_text'))}</td>"
        f"<td>{esc(r.get('expected_value'))}</td></tr>"
        for r in items)
    return ("<table><tr><th>Rule ID</th><th>Title</th><th>Check text</th>"
           f"<th>Expected value</th></tr>{rows}</table>")


def _leftovers_html(final):
    coverage = final.get("coverage", {}) or {}
    ignored_count = (coverage.get("company", {}) or {}).get("ignored_by_rule", 0)
    n_unmatched = len(final.get("unmatched_rows", []) or [])
    n_unaddressed = len(final.get("unaddressed_rules", []) or [])
    return f"""
<section id="leftovers">
  <h2>Leftovers</h2>

  <h3>Ambiguous matches</h3>
  {_ambiguous_html(final)}

  <h3>Unresolved rows (needs-structuring-unresolved / extraction-failed)</h3>
  {_unresolved_html(final)}

  <details>
    <summary>Unmatched company rows ({esc(n_unmatched)})</summary>
    {_unmatched_html(final)}
  </details>

  <details>
    <summary>Unaddressed official rules ({esc(n_unaddressed)})</summary>
    {_unaddressed_html(final)}
  </details>

  <details>
    <summary>Ignored content ({esc(ignored_count)})</summary>
    <p>{esc(ignored_count)} company row(s) were excluded by an ignore-field
       rule. Per-row detail for ignored rows is not persisted in this run's
       artifacts.</p>
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
        + _findings_section_html(final)
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
