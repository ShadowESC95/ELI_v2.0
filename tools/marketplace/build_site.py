#!/usr/bin/env python3
"""Generate the public marketplace shopfront from a registry index.

The store users browse is a STATIC SITE built from the same `index.json` the ELI
client fetches. One file is the source of truth for both, so the page can never
advertise a plugin the client would refuse, or describe permissions that differ
from the ones the consent dialog will ask for.

The page is discovery only, and is built that way on purpose: there is no install
button, because a website must never be able to trigger one. If a page could push
an install, the browser would become the attack surface and the consent dialog
would be spoofable. The page hands out an id; the desktop client does the
fetching, verifying, scanning and asking.

Output is a single self-contained HTML file — no CDN, no external fonts, no
analytics. A store that distributes executable code should not also be shipping
third-party JavaScript to the people evaluating it.

Usage
-----
    build_site.py index.json --out site/ [--name "ELI Marketplace"] \
                  [--domain plugins.geteli.tech] [--submit-url https://github.com/...]
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Kept in step with eli/plugins/permissions.py. Only the wording differs: this is
# the shopfront's plain-English summary, the client shows the full description.
PERMISSION_BLURB = {
    "network": "Connects to the internet",
    "filesystem_read": "Reads files",
    "filesystem_write": "Writes or deletes files",
    "process_exec": "Runs other programs — unlimited access",
    "clipboard": "Reads or sets the clipboard",
    "screen_capture": "Takes screenshots",
    "audio_record": "Records audio",
    "camera": "Uses the camera",
    "notifications": "Shows notifications",
    "location": "Reads your location",
    "contacts": "Reads contacts",
    "credentials": "Reads stored credentials",
    "system_settings": "Changes system settings",
}
HIGH_RISK = {"process_exec", "credentials", "camera", "audio_record",
             "screen_capture", "system_settings"}


def _risk_of(perms):
    if not perms:
        return "low"
    if any(p in HIGH_RISK for p in perms):
        return "high"
    if any(p in ("network", "filesystem_write", "location", "contacts") for p in perms):
        return "medium"
    return "low"


def _card(p: dict) -> str:
    e = html.escape
    pid = str(p.get("id", ""))
    perms = [str(x) for x in (p.get("permissions") or [])]
    risk = _risk_of(perms)
    kind = "MCP server" if (p.get("kind") == "mcp" or p.get("mcp")) else "Plugin"
    price = p.get("price") or 0
    price_s = "Free" if not price else f"{price} {e(str(p.get('currency') or 'EUR'))}"

    if perms:
        chips = "".join(
            f'<li class="perm perm-{"hi" if x in HIGH_RISK else "lo"}">'
            f'{e(PERMISSION_BLURB.get(x, x))}</li>' for x in sorted(perms))
        perm_block = f'<ul class="perms">{chips}</ul>'
    else:
        perm_block = '<p class="perms-none">Asks for no permissions.</p>'

    signed = ('<span class="badge badge-ok" title="Reviewed and signed by the '
              'maintainer">signed</span>' if p.get("signature") else
              '<span class="badge badge-warn" title="Not signed — the client will '
              'refuse this on the official registry">unsigned</span>')

    return f'''<article class="card" data-risk="{risk}" data-name="{e(pid.lower())} {e(str(p.get("name","")).lower())} {e(str(p.get("description","")).lower())}">
  <header>
    <h3>{e(str(p.get("name") or pid))}</h3>
    <span class="kind">{kind}</span>
  </header>
  <p class="desc">{e(str(p.get("description") or ""))}</p>
  {perm_block}
  <footer>
    <span class="meta">v{e(str(p.get("version") or "?"))} · {e(str(p.get("author") or "unknown"))} · {e(str(p.get("license") or "—"))}</span>
    <span class="tags"><span class="risk risk-{risk}">{risk} risk</span>{signed}<span class="price">{price_s}</span></span>
  </footer>
  <details>
    <summary>How to install</summary>
    <p>In ELI: <strong>Settings &rsaquo; Marketplace</strong>, search for
       <code>{e(pid)}</code>, and click Install. ELI verifies the checksum and
       signature, scans the file, and asks you about every permission before
       anything is written to disk.</p>
    <p class="muted">This page cannot install anything, by design.</p>
  </details>
</article>'''


def build(index_path: str, out_dir: str, name: str, domain: str, submit_url: str) -> Path:
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    plugins = [p for p in (data.get("plugins") or []) if isinstance(p, dict)]
    plugins.sort(key=lambda p: (RISK_ORDER.get(_risk_of(p.get("permissions") or []), 9),
                                str(p.get("name") or p.get("id") or "").lower()))

    e = html.escape
    registry_url = f"https://{domain}/index.json" if domain else "index.json"
    cards = "\n".join(_card(p) for p in plugins) or (
        '<p class="empty">No plugins are listed yet. '
        '<a href="' + e(submit_url or "#") + '">Submit the first one.</a></p>')
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(name)}</title>
<meta name="description" content="Plugins and MCP servers for ELI. Every listing is reviewed and signed before it appears.">
<style>
:root {{
  --bg:#fbfbfd; --fg:#16161a; --muted:#5b5b66; --line:#e3e3ea; --card:#fff;
  --accent:#2f6f4f; --warn:#8a5a00; --hi:#a13b2f; --chip:#f1f1f6;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme=light]) {{
    --bg:#0f1013; --fg:#e9e9ee; --muted:#a0a0ad; --line:#26262e; --card:#16171b;
    --accent:#7fc7a1; --warn:#e0ac54; --hi:#e8897c; --chip:#1e1f25;
  }}
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:0 20px}}
header.top{{border-bottom:1px solid var(--line);padding:56px 0 32px}}
h1{{margin:0 0 8px;font-size:2.1rem;letter-spacing:-.02em}}
.tagline{{margin:0;color:var(--muted);font-size:1.05rem;max-width:62ch}}
.controls{{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0 8px}}
input[type=search]{{flex:1;min-width:220px;padding:10px 14px;border:1px solid var(--line);
  border-radius:8px;background:var(--card);color:var(--fg);font-size:1rem}}
select{{padding:10px 12px;border:1px solid var(--line);border-radius:8px;
  background:var(--card);color:var(--fg)}}
.grid{{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  padding:28px 0 8px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}}
.card header{{display:flex;align-items:baseline;justify-content:space-between;gap:10px}}
.card h3{{margin:0;font-size:1.12rem}}
.kind{{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}}
.desc{{margin:10px 0 14px;color:var(--fg)}}
.perms{{list-style:none;margin:0 0 14px;padding:0;display:flex;flex-wrap:wrap;gap:6px}}
.perm{{font-size:.8rem;padding:3px 9px;border-radius:999px;background:var(--chip);color:var(--muted)}}
.perm-hi{{color:var(--hi);font-weight:600}}
.perms-none{{margin:0 0 14px;color:var(--accent);font-size:.88rem}}
.card footer{{display:flex;flex-direction:column;gap:8px;border-top:1px solid var(--line);padding-top:12px}}
.meta{{color:var(--muted);font-size:.82rem}}
.tags{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.risk,.badge,.price{{font-size:.75rem;padding:2px 9px;border-radius:999px;border:1px solid var(--line)}}
.risk-low{{color:var(--accent)}} .risk-medium{{color:var(--warn)}} .risk-high{{color:var(--hi)}}
.badge-ok{{color:var(--accent)}} .badge-warn{{color:var(--warn)}}
details{{margin-top:12px}} summary{{cursor:pointer;color:var(--muted);font-size:.86rem}}
details p{{font-size:.9rem}} .muted{{color:var(--muted)}}
code{{background:var(--chip);padding:1px 6px;border-radius:5px;font-size:.9em}}
section.note{{border-top:1px solid var(--line);margin-top:40px;padding:32px 0 56px}}
section.note h2{{font-size:1.15rem;margin:0 0 12px}}
section.note li{{margin-bottom:8px;color:var(--muted)}}
.empty{{color:var(--muted);padding:40px 0}}
a{{color:var(--accent)}}
footer.foot{{border-top:1px solid var(--line);padding:24px 0;color:var(--muted);font-size:.85rem}}
</style>
</head><body>
<div class="wrap">
<header class="top">
  <h1>{e(name)}</h1>
  <p class="tagline">Plugins and MCP servers for ELI. Every listing here was read
     by a person and signed before it appeared — and ELI still asks you about each
     permission before it installs anything.</p>
  <div class="controls">
    <input type="search" id="q" placeholder="Search plugins…" aria-label="Search plugins">
    <select id="risk" aria-label="Filter by risk">
      <option value="">Any risk</option>
      <option value="low">Low risk only</option>
      <option value="medium">Low + medium</option>
    </select>
  </div>
</header>

<main class="grid" id="grid">
{cards}
</main>

<section class="note">
  <h2>What review means — and what it doesn't</h2>
  <ul>
    <li>A person read the code and nothing objected. That raises the floor; it is
        not a guarantee.</li>
    <li>It does not prove the author is who they say, that a plugin does what it
        claims, or that a later version is as careful as the one that was read.</li>
    <li>ELI asks you about every capability at install and enforces them while the
        plugin runs. <strong>Review is a layer on top of your consent, not a
        replacement for it.</strong></li>
    <li>Paid plugins are sold by their authors. Review is not escrow.</li>
  </ul>
  <h2>Submitting a plugin</h2>
  <p class="muted">Open a pull request against the registry. Automated checks run
     the same scanners a user's machine runs, then a maintainer reads it. Nothing
     goes live because a timer expired.
     {'<a href="' + e(submit_url) + '">Submit here.</a>' if submit_url else ''}</p>
  <h2>For the technically minded</h2>
  <p class="muted">The registry is a static JSON index at
     <code>{e(registry_url)}</code>. Artifacts are pinned by SHA-256 and signed
     with the marketplace key; ELI refuses an unsigned or altered listing from
     this registry outright.</p>
</section>

<footer class="foot">Built {built} · {len(plugins)} listing{'' if len(plugins)==1 else 's'}</footer>
</div>
<script>
(function () {{
  var q = document.getElementById('q'), r = document.getElementById('risk'),
      cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var allow = {{ '': ['low','medium','high'], low: ['low'], medium: ['low','medium'] }};
  function apply() {{
    var term = (q.value || '').toLowerCase().trim(), risks = allow[r.value] || allow[''];
    cards.forEach(function (c) {{
      var okRisk = risks.indexOf(c.dataset.risk) !== -1;
      var okTerm = !term || (c.dataset.name || '').indexOf(term) !== -1;
      c.style.display = (okRisk && okTerm) ? '' : 'none';
    }});
  }}
  q.addEventListener('input', apply); r.addEventListener('change', apply);
}})();
</script>
</body></html>'''

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page_path = out / "index.html"
    page_path.write_text(page, encoding="utf-8")
    # The client fetches the same file the page was built from.
    (out / "index.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return page_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("index", help="the registry index.json")
    ap.add_argument("--out", default="site", help="output directory (default: site/)")
    ap.add_argument("--name", default="ELI Marketplace")
    ap.add_argument("--domain", default="", help="e.g. plugins.geteli.tech")
    ap.add_argument("--submit-url", default="", help="where submitters open a PR")
    a = ap.parse_args(argv)
    try:
        p = build(a.index, a.out, a.name, a.domain, a.submit_url)
    except Exception as exc:
        print(f"could not build the site: {exc}", file=sys.stderr)
        return 1
    print(f"built {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
