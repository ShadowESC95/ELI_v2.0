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

    signed = ('<span class="badge badge-ok">signed</span>' if p.get("signature")
              else '<span class="badge badge-warn">unsigned</span>')

    return f'''<article class="card" data-risk="{risk}" data-name="{e(pid.lower())} {e(str(p.get("name","")).lower())} {e(str(p.get("description","")).lower())}">
  <header>
    <h3>{e(str(p.get("name") or pid))}</h3>
    <span class="kind">{kind}</span>
  </header>
  <p class="desc">{e(str(p.get("description") or ""))}</p>
  {perm_block}
  <div class="tags">
    <span class="risk risk-{risk}">{risk} risk</span>{signed}<span class="price">{price_s}</span>
  </div>
  <footer>
    <span class="meta">v{e(str(p.get("version") or "?"))} &middot; {e(str(p.get("author") or "unknown"))} &middot; {e(str(p.get("license") or "&mdash;"))}</span>
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


def build(index_path: str, out_dir: str, name: str, domain: str, submit_url: str,
          home_url: str = "https://geteli.tech", logo_path: str = "") -> Path:
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    plugins = [p for p in (data.get("plugins") or []) if isinstance(p, dict)]
    plugins.sort(key=lambda p: (RISK_ORDER.get(_risk_of(p.get("permissions") or []), 9),
                                str(p.get("name") or p.get("id") or "").lower()))

    e = html.escape
    registry_url = f"https://{domain}/index.json" if domain else "index.json"
    # The store is a room in ELI's house, not a separate building: every page
    # keeps a way back to the product it belongs to.
    home_url = (home_url or "https://geteli.tech").rstrip("/")

    # The mark is embedded as a data URI rather than linked: this page must not
    # make a single outbound request, and an <img src> to anywhere would be one.
    logo_tag = ('<span class="mark" aria-hidden></span>')
    if logo_path:
        try:
            import base64, mimetypes
            raw = Path(logo_path).read_bytes()
            mime = mimetypes.guess_type(logo_path)[0] or "image/png"
            uri = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
            logo_tag = f'<img class="mark" src="{uri}" alt="" width="26" height="26">'
        except Exception as exc:
            print(f"warning: could not embed the logo ({exc}); using the fallback mark",
                  file=sys.stderr)
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
/* Same visual language as geteli.tech: cyan #22d3ee with a magenta counterpoint
   and a violet mid-stop, layered blooms over a 34px grid, glass panels, film
   grain. Kept in step deliberately — the store is a room in ELI's house, and a
   different palette makes it read as somebody else's site. */
:root {{
  --bg:#04060c; --bg2:#070a12; --grid:rgba(34,211,238,.045);
  --card:rgba(12,19,32,.58); --card2:rgba(20,28,44,.5);
  --line:rgba(64,224,255,.14); --line-str:rgba(64,224,255,.34);
  --fg:#e3edfb; --fg-dim:#8aa4c8; --mut:#5b6b86;
  --accent:#22d3ee; --accent2:#f637ec; --violet:#7c5cff; --press:#06b6d4;
  --ok:#34f5c5; --warn:#ffd166; --bad:#ff5d73;
  --glow:0 0 0 1px rgba(34,211,238,.3), 0 0 18px rgba(34,211,238,.2);
  --shadow:0 2px 10px rgba(0,0,0,.5), 0 18px 54px rgba(0,0,0,.45);
  --radius:16px; --fast:.2s cubic-bezier(.4,0,.2,1);
  --mono:ui-monospace,"JetBrains Mono",Menlo,Consolas,monospace;
}}
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
body{{margin:0;color:var(--fg);-webkit-font-smoothing:antialiased;
  font:16px/1.65 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  background:
    radial-gradient(1200px 620px at 78% -14%, rgba(34,211,238,.11), transparent 62%),
    radial-gradient(1000px 560px at -14% 106%, rgba(246,55,236,.075), transparent 62%),
    linear-gradient(var(--grid) 1px,transparent 1px) 0 0/34px 34px,
    linear-gradient(90deg,var(--grid) 1px,transparent 1px) 0 0/34px 34px,
    var(--bg);
  background-attachment:fixed;}}
body::after{{content:"";position:fixed;inset:0;pointer-events:none;z-index:1;opacity:.035;
  mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");}}
a{{color:inherit;text-decoration:none}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 24px;position:relative;z-index:2}}

nav.top{{position:sticky;top:0;z-index:50;background:rgba(4,6,12,.72);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  border-bottom:1px solid var(--line)}}
nav.top .inner{{max-width:1180px;margin:0 auto;padding:0 24px;height:64px;
  display:flex;align-items:center;justify-content:space-between}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.05rem}}
.mark{{height:28px;width:28px;border-radius:8px;object-fit:cover;
  filter:drop-shadow(0 0 14px rgba(34,211,238,.6))}}
.brandtext{{letter-spacing:.16em;background:linear-gradient(100deg,var(--accent),var(--violet) 55%,var(--accent2));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent}}
.brand .sub{{color:var(--mut);font-weight:400;letter-spacing:0;-webkit-text-fill-color:var(--mut)}}
.navlinks{{display:flex;gap:24px;align-items:center;font-size:.92rem}}
.navlinks a{{color:var(--fg-dim);transition:var(--fast)}} .navlinks a:hover{{color:var(--accent)}}
.btn{{display:inline-flex;align-items:center;gap:.5rem;padding:.6rem 1.1rem;border-radius:11px;
  font-weight:600;font-size:.9rem;border:1px solid transparent;transition:var(--fast)}}
.btn-primary{{background:linear-gradient(135deg,var(--accent),var(--press));color:#03121a;
  box-shadow:0 0 0 1px rgba(34,211,238,.4),0 0 30px rgba(34,211,238,.34)}}
.btn-primary:hover{{filter:brightness(1.1);transform:translateY(-2px)}}
.btn-ghost{{border-color:var(--line);color:var(--fg);background:var(--card2)}}
.btn-ghost:hover{{border-color:var(--accent);color:var(--accent);box-shadow:var(--glow)}}

header.hero{{position:relative;overflow:hidden}}
header.hero .bg{{position:absolute;inset:0;pointer-events:none}}
header.hero .bg::before{{content:"";position:absolute;left:62%;top:-300px;width:900px;height:600px;
  transform:translateX(-50%);
  background:radial-gradient(ellipse at center,rgba(34,211,238,.15),transparent 66%);filter:blur(36px)}}
header.hero .inner{{position:relative;padding:76px 0 52px;z-index:2}}
.kicker{{font-family:var(--mono);font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;
  color:var(--accent);text-shadow:0 0 14px rgba(34,211,238,.5);margin:0 0 22px;
  display:inline-flex;align-items:center;gap:.7rem}}
.kicker::before{{content:"";width:26px;height:1px;background:var(--accent);box-shadow:0 0 8px var(--accent)}}
h1{{margin:0;font-size:clamp(2.1rem,5.4vw,3.7rem);line-height:.98;letter-spacing:-.035em;
  font-weight:800;text-transform:uppercase;max-width:17ch}}
.grad{{background:linear-gradient(100deg,var(--accent),var(--violet) 55%,var(--accent2));
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent}}
.tagline{{margin:26px 0 0;color:var(--fg-dim);font-size:1.06rem;max-width:60ch}}

.controls{{display:flex;gap:12px;flex-wrap:wrap;padding:34px 0 0}}
input[type=search],select{{padding:.75rem 1.1rem;border:1px solid var(--line);border-radius:11px;
  background:var(--card);backdrop-filter:blur(18px);color:var(--fg);font-size:.95rem;font-family:inherit}}
input[type=search]{{flex:1;min-width:230px}}
input[type=search]:focus,select:focus{{outline:none;border-color:var(--accent);box-shadow:var(--glow)}}

.grid{{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));padding:40px 0 8px}}
.card{{position:relative;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:24px;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  box-shadow:var(--shadow);transition:var(--fast)}}
.card::before{{content:"";position:absolute;inset-inline:18%;top:-1px;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:0;transition:var(--fast)}}
.card:hover{{border-color:var(--line-str);transform:translateY(-4px);box-shadow:var(--shadow),var(--glow)}}
.card:hover::before{{opacity:1}}
.card header{{display:flex;align-items:baseline;justify-content:space-between;gap:10px}}
.card h3{{margin:0;font-size:1.12rem;letter-spacing:-.015em;font-weight:650}}
.kind{{color:var(--mut);font-size:.68rem;text-transform:uppercase;letter-spacing:.12em;
  font-family:var(--mono);white-space:nowrap}}
.desc{{margin:13px 0 17px;color:var(--fg-dim);font-size:.95rem}}
.perms{{list-style:none;margin:0 0 17px;padding:0;display:flex;flex-wrap:wrap;gap:7px}}
.perm{{font-size:.77rem;padding:4px 11px;border-radius:999px;background:rgba(20,28,44,.6);
  border:1px solid var(--line);color:var(--fg-dim)}}
.perm-hi{{color:var(--bad);border-color:rgba(255,93,115,.32);background:rgba(255,93,115,.06)}}
.perms-none{{margin:0 0 17px;color:var(--ok);font-size:.86rem}}
.tags{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:15px}}
.risk,.badge,.price{{font-size:.7rem;padding:3px 11px;border-radius:999px;border:1px solid var(--line);
  font-family:var(--mono);letter-spacing:.06em;text-transform:uppercase}}
.risk-low{{color:var(--ok);border-color:rgba(52,245,197,.3)}}
.risk-medium{{color:var(--warn);border-color:rgba(255,209,102,.3)}}
.risk-high{{color:var(--bad);border-color:rgba(255,93,115,.32)}}
.badge-ok{{color:var(--accent);border-color:rgba(34,211,238,.32)}}
.badge-warn{{color:var(--warn);border-color:rgba(255,209,102,.3)}}
.price{{color:var(--mut)}}
.card footer{{border-top:1px solid var(--line);padding-top:13px}}
.meta{{color:var(--mut);font-size:.79rem;font-family:var(--mono)}}
details{{margin-top:13px}}
summary{{cursor:pointer;color:var(--mut);font-size:.85rem;transition:var(--fast)}}
summary:hover{{color:var(--accent)}}
details p{{font-size:.88rem;color:var(--fg-dim)}}
.muted{{color:var(--mut)}}
code{{background:rgba(20,28,44,.7);border:1px solid var(--line);padding:2px 7px;border-radius:6px;
  font-size:.88em;font-family:var(--mono);color:var(--accent)}}
.empty{{color:var(--fg-dim);padding:72px 0;text-align:center;font-size:1.02rem}}

hr.fade{{height:1px;border:0;margin:0;
  background:linear-gradient(90deg,transparent,var(--line-str),transparent)}}
section.note{{padding:52px 0}}
section.note h2{{font-size:1.5rem;margin:0 0 18px;letter-spacing:-.02em;font-weight:700}}
section.note h2:not(:first-of-type){{margin-top:44px}}
section.note li,section.note p{{color:var(--fg-dim);margin-bottom:11px}}
section.note strong{{color:var(--fg)}}
footer.foot{{padding:30px 0 56px;color:var(--mut);font-size:.85rem;
  display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between;align-items:center}}
footer.foot a{{color:var(--fg-dim);transition:var(--fast)}} footer.foot a:hover{{color:var(--accent)}}
@media (max-width:640px){{ .navlinks .hide-sm{{display:none}} }}
@media (prefers-reduced-motion:reduce){{ html{{scroll-behavior:auto}} .card,.btn{{transition:none}}
  .card:hover,.btn-primary:hover{{transform:none}} }}
</style>
</head><body>

<nav class="top"><div class="inner">
  <a class="brand" href="{e(home_url)}">
    {logo_tag}
    <span class="brandtext">ELI <span class="sub">/ Marketplace</span></span>
  </a>
  <div class="navlinks">
    <a class="hide-sm" href="{e(home_url)}#what">What ELI does</a>
    <a class="hide-sm" href="{e(submit_url) if submit_url else "#submit"}">Publish</a>
    <a class="btn btn-ghost" href="{e(home_url)}">&larr; geteli.tech</a>
  </div>
</div></nav>

<header class="hero"><div class="bg" aria-hidden></div>
  <div class="wrap inner">
    <p class="kicker">Reviewed &middot; Signed &middot; Sandboxed</p>
    <h1>Tools for ELI,<br><span class="grad">read by a person first.</span></h1>
    <p class="tagline">Plugins and MCP servers built by the community. Every listing
       here was reviewed and signed before it appeared &mdash; and ELI still asks you
       about each permission before it installs anything.</p>
    <div class="controls">
      <input type="search" id="q" placeholder="Search plugins&hellip;" aria-label="Search plugins">
      <select id="risk" aria-label="Filter by risk">
        <option value="">Any risk</option>
        <option value="low">Low risk only</option>
        <option value="medium">Low + medium</option>
      </select>
    </div>
  </div>
</header>

<div class="wrap">
<main class="grid" id="grid">
{cards}
</main>

<hr class="fade">
<section class="note" id="submit">
  <h2>What review means &mdash; and what it doesn&rsquo;t</h2>
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
  <p>Open a pull request against the registry. Automated checks run the same
     scanners a user&rsquo;s machine runs, then a maintainer reads it. Nothing goes
     live because a timer expired.</p>
  {'<p><a class="btn btn-primary" href="' + e(submit_url) + '">Submit a plugin</a></p>' if submit_url else ''}
  <h2>For the technically minded</h2>
  <p>The registry is a static JSON index at <code>{e(registry_url)}</code> &mdash;
     the same file this page was built from, so nothing here can be advertised that
     the client would refuse. Artifacts are pinned by SHA-256 and signed with the
     marketplace key; ELI refuses an unsigned or altered listing from this registry
     outright.</p>
</section>

<hr class="fade">
<footer class="foot">
  <span>Built {built} &middot; {len(plugins)} listing{'' if len(plugins)==1 else 's'}</span>
  <span><a href="{e(home_url)}">geteli.tech</a> &middot; <a href="{e(home_url)}#private">Privacy</a>{' &middot; <a href="' + e(submit_url) + '">Registry</a>' if submit_url else ''}</span>
</footer>
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
    # GitHub Pages reads the custom domain from a CNAME file inside the PUBLISHED
    # artifact, not from the repository root. A CNAME sitting beside the workflow
    # is invisible to the deployment: the domain binding never completes and no
    # certificate is ever issued, so the site answers on http and hangs on https
    # with no error anywhere to explain it.
    if domain:
        (out / "CNAME").write_text(domain.strip() + "\n", encoding="utf-8")
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
    ap.add_argument("--home", default="https://geteli.tech",
                    help="the main ELI site the store links back to")
    ap.add_argument("--logo", default="",
                    help="PNG/SVG to embed as the brand mark (inlined, not linked)")
    a = ap.parse_args(argv)
    try:
        p = build(a.index, a.out, a.name, a.domain, a.submit_url, a.home, a.logo)
    except Exception as exc:
        print(f"could not build the site: {exc}", file=sys.stderr)
        return 1
    print(f"built {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
