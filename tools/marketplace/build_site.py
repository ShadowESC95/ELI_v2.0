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
:root {{
  /* Sampled from ELI's mark: canvas #001015, ring #00fefe -> #00d1fd,
     wordmark #f8f9f9. The store should look like the icon in its nav. */
  --bg:#00080b; --bg-card:#04141b; --bg-raise:#00131a;
  --line:#0d2b34; --line-soft:#071e25;
  --fg:#f2f6f7; --fg-dim:#8fa5ab; --fg-faint:#5e777e;
  --cyan:#00fefe; --blue:#00d1fd; --glow:rgba(0,209,253,.16); --danger:#ff8a7a;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--fg);-webkit-font-smoothing:antialiased;
  font:16px/1.65 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
a{{color:inherit;text-decoration:none}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 24px}}

/* nav — the way back to the rest of ELI */
nav.top{{position:sticky;top:0;z-index:50;background:rgba(8,9,11,.85);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}}
nav.top .inner{{max-width:1120px;margin:0 auto;padding:0 24px;height:64px;
  display:flex;align-items:center;justify-content:space-between}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:600;font-size:1.05rem}}
.mark{{height:24px;width:24px;border-radius:6px;
  box-shadow:0 0 18px rgba(0,209,253,.35);object-fit:cover}}
.brand .sub{{color:var(--fg-faint);font-weight:400}}
.navlinks{{display:flex;gap:24px;align-items:center;font-size:.92rem}}
.navlinks a{{color:var(--fg-dim)}} .navlinks a:hover{{color:var(--fg)}}
.btn{{display:inline-flex;align-items:center;gap:.5rem;padding:.55rem 1rem;border-radius:9px;
  font-weight:600;font-size:.9rem;border:1px solid transparent;transition:all .18s ease}}
.btn-primary{{background:linear-gradient(135deg,var(--cyan),var(--blue));color:#001015}}
.btn-primary:hover{{filter:brightness(1.12)}}
.btn-ghost{{border-color:var(--line);color:var(--fg)}}
.btn-ghost:hover{{border-color:var(--fg-faint);background:var(--bg-raise)}}

/* hero */
header.hero{{position:relative;overflow:hidden;border-bottom:1px solid var(--line)}}
header.hero .bg{{position:absolute;inset:0;pointer-events:none}}
header.hero .bg::before{{content:"";position:absolute;inset:-1px;
  background-image:linear-gradient(to right,var(--line-soft) 1px,transparent 1px),
    linear-gradient(to bottom,var(--line-soft) 1px,transparent 1px);
  background-size:56px 56px;
  -webkit-mask-image:radial-gradient(ellipse 80% 70% at 50% 0%,#000 40%,transparent 100%);
  mask-image:radial-gradient(ellipse 80% 70% at 50% 0%,#000 40%,transparent 100%)}}
header.hero .bg::after{{content:"";position:absolute;left:50%;top:-240px;width:820px;height:480px;
  transform:translateX(-50%);
  background:radial-gradient(ellipse at center,var(--glow),transparent 68%);filter:blur(30px)}}
header.hero .inner{{position:relative;padding:72px 0 56px}}
.kicker{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;
  letter-spacing:.16em;text-transform:uppercase;color:var(--cyan);margin:0 0 18px}}
h1{{margin:0;font-size:2.6rem;line-height:1.08;letter-spacing:-.03em;font-weight:600;max-width:18ch}}
h1 .accent{{color:var(--cyan)}}
.tagline{{margin:22px 0 0;color:var(--fg-dim);font-size:1.08rem;max-width:60ch}}

/* controls */
.controls{{display:flex;gap:12px;flex-wrap:wrap;padding:28px 0 0}}
input[type=search],select{{padding:.7rem 1rem;border:1px solid var(--line);border-radius:9px;
  background:var(--bg-card);color:var(--fg);font-size:.95rem;font-family:inherit}}
input[type=search]{{flex:1;min-width:220px}}
input[type=search]:focus,select:focus{{outline:none;border-color:var(--blue)}}

/* grid */
.grid{{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));padding:36px 0 8px}}
.card{{background:var(--bg-card);border:1px solid var(--line);border-radius:14px;padding:22px;
  transition:border-color .18s ease,transform .18s ease}}
.card:hover{{border-color:var(--blue);transform:translateY(-2px)}}
.card header{{display:flex;align-items:baseline;justify-content:space-between;gap:10px}}
.card h3{{margin:0;font-size:1.1rem;letter-spacing:-.01em}}
.kind{{color:var(--fg-faint);font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
  font-family:ui-monospace,monospace;white-space:nowrap}}
.desc{{margin:12px 0 16px;color:var(--fg-dim);font-size:.95rem}}
.perms{{list-style:none;margin:0 0 16px;padding:0;display:flex;flex-wrap:wrap;gap:6px}}
.perm{{font-size:.78rem;padding:3px 10px;border-radius:999px;background:var(--bg-raise);
  border:1px solid var(--line);color:var(--fg-dim)}}
.perm-hi{{color:var(--danger);border-color:#3a2320}}
.perms-none{{margin:0 0 16px;color:var(--cyan);font-size:.86rem}}
.tags{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}}
.risk,.badge,.price{{font-size:.72rem;padding:3px 10px;border-radius:999px;border:1px solid var(--line);
  font-family:ui-monospace,monospace}}
.risk-low{{color:var(--cyan)}} .risk-medium{{color:var(--blue)}} .risk-high{{color:var(--danger)}}
.badge-ok{{color:var(--cyan)}} .badge-warn{{color:var(--blue)}} .price{{color:var(--fg-faint)}}
.card footer{{border-top:1px solid var(--line);padding-top:12px}}
.meta{{color:var(--fg-faint);font-size:.8rem}}
details{{margin-top:12px}}
summary{{cursor:pointer;color:var(--fg-faint);font-size:.85rem}}
summary:hover{{color:var(--fg-dim)}}
details p{{font-size:.88rem;color:var(--fg-dim)}}
.muted{{color:var(--fg-faint)}}
code{{background:var(--bg-raise);border:1px solid var(--line);padding:1px 6px;border-radius:5px;
  font-size:.88em;font-family:ui-monospace,monospace}}
.empty{{color:var(--fg-dim);padding:56px 0;text-align:center}}

/* notes */
section.note{{border-top:1px solid var(--line);margin-top:48px;padding:48px 0}}
section.note h2{{font-size:1.35rem;margin:0 0 16px;letter-spacing:-.02em}}
section.note h2:not(:first-child){{margin-top:40px}}
section.note li,section.note p{{color:var(--fg-dim);margin-bottom:10px}}
section.note strong{{color:var(--fg)}}
footer.foot{{border-top:1px solid var(--line);padding:28px 0 48px;color:var(--fg-faint);font-size:.85rem;
  display:flex;flex-wrap:wrap;gap:16px;justify-content:space-between}}
footer.foot a{{color:var(--fg-dim)}} footer.foot a:hover{{color:var(--fg)}}
@media (max-width:640px){{ h1{{font-size:2rem}} .navlinks .hide-sm{{display:none}} }}
@media (prefers-reduced-motion:reduce){{ html{{scroll-behavior:auto}} .card{{transition:none}} }}
</style>
</head><body>

<nav class="top"><div class="inner">
  <a class="brand" href="{e(home_url)}">
    {logo_tag}
    <span>ELI <span class="sub">/ Marketplace</span></span>
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
    <h1>Tools for ELI, <span class="accent">read by a person</span> first.</h1>
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
     live because a timer expired.
     {'<a class="btn btn-primary" style="margin-top:12px" href="' + e(submit_url) + '">Submit a plugin</a>' if submit_url else ''}</p>
  <h2>For the technically minded</h2>
  <p>The registry is a static JSON index at <code>{e(registry_url)}</code> &mdash;
     the same file this page was built from, so nothing here can be advertised that
     the client would refuse. Artifacts are pinned by SHA-256 and signed with the
     marketplace key; ELI refuses an unsigned or altered listing from this registry
     outright.</p>
</section>

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
