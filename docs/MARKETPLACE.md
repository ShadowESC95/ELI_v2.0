# Running ELI's marketplace

ELI's marketplace is **curated**. Anyone may submit a plugin or MCP server; nothing
is listed until the maintainer has read it and signed it. This document is the
runbook for the person doing that — how to stand the store up, and what each step
is actually protecting against.

The client half ships complete. What follows is the half that lives outside the
application.

---

## 1. The shape of it

```
  submitter                 quarantine              maintainer            user
  ─────────                 ──────────              ──────────            ────
  opens a PR   ──────▶   CI runs review.py   ──▶   reads the code   ──▶  installs
  with the               (same checks the          then signs it          (client
  plugin +               user's machine            with publish.py        verifies
  manifest               will run)                 --sign-key             the sig)
                              │                         │
                         blocking findings         merge = approval
                         → PR fails, never         → listing goes live
                           reaches a human
```

Four properties hold this together, and each is enforced in code rather than by
convention:

1. **A pull request is the quarantine.** A submission is proposed, not published.
   There is no upload endpoint, no queue to drain, nothing that goes live because
   a timer expired. The default state of any submission is "not listed".
2. **CI cannot approve.** `review.py` returns `REJECT` or `NEEDS_HUMAN_REVIEW` and
   has no third outcome. If a scanner could approve, the review would attest to
   nothing but the scanner's opinion.
3. **The signature is the approval.** Signing happens at publish time with a key
   only the maintainer holds. A plugin listing on the official registry that is not
   validly signed by that key is **refused by the client**, not warned about — see
   §5 (which also covers MCP server listings, which are not signature-checked).
4. **Curation is not the only door.** Operators can still add community
   registries. That keeps the curated store honest: the maintainer cannot become
   the only way to get a plugin, and cannot quietly delist a competitor.

---

## 2. Where to host it — the recommendation

**GitHub as the system of record, a custom domain as the shopfront.**

Concretely:

| Piece | Where | Why |
|---|---|---|
| Registry repo (`index.json`, submissions) | GitHub, public | PRs *are* the quarantine, with a permanent public audit trail of who submitted what and who approved it |
| Automated evaluation | GitHub Actions (`review-submission.yml`, in `registry_template/`) | Runs `review.py` — the checks the user's machine runs — on every `plugins/<id>/` a pull request changes, and posts the report on the PR. It installs ClamAV (with a `freshclam` update). ELI's YARA engine also needs the `yara-python` module and a ruleset (`plugin_yara_rules.yar` in ELI's config folder), which the workflow does not provide, so YARA reports as unavailable there until you add them |
| Plugin artifacts | GitHub Releases | CDN-backed, free bandwidth, immutable per tag, and the URL is stable — which matters because the `sha256` in the listing pins the file |
| Public shopfront | GitHub Pages on your own domain, built and deployed by the template's `publish-site.yml` (Cloudflare Pages or Netlify can serve the same static output) | Free static hosting, and a domain makes it *ELI's* marketplace rather than "a GitHub repo" |
| Signing key | Offline, on your machine, backed up | Never in CI. See §4 |

**Why this and not a server.** You are one person. A VPS running a store is a
service you must keep patched, backed up, and online, and it is a target
precisely because it distributes executable code to other people's machines. The
architecture above has no server to compromise: a static JSON index and signed
artifacts on a CDN. Even if someone took over the hosting, they could not forge a
listing, because they would not have the signing key — the client checks the
signature, not the origin.

**On the specific options you asked about:**

- **GitHub** — yes, as above. The decisive feature is not hosting, it is that the
  PR workflow gives you quarantine, review history and approval-by-merge for free,
  and it is the workflow contributors already know.
- **A URL / your own domain** — yes, for the shopfront, pointed at static hosting.
  Buy the domain; do not run the server behind it.
- **IndieHackers** — no, not for this. It is a community and marketing site for
  founders, not a package registry or artifact host; there is nothing there to
  serve `index.json` from or to attach signed binaries to. It is a good place to
  *announce* the marketplace and find early submitters. Treat it as a channel, not
  as infrastructure.
- **A dedicated registry service** (PyPI-like, or something self-hosted) — only if
  submission volume ever outgrows reading pull requests by hand. That is a good
  problem and a long way off; it also loses the free audit trail.

**Cost:** domain only. Everything else is inside free tiers at any plausible
early volume.

---

## 3. Standing it up

1. **Create the registry repo** from `tools/marketplace/registry_template/`. It
   contains `index.json` (two example listings: a plugin and an MCP server), a README
   (hosting a registry on GitHub Pages) and two workflows: `review-submission.yml`,
   which runs on pull requests that touch `plugins/**`, and `publish-site.yml`, which
   rebuilds the shopfront on pushes to `main`. A submission goes under
   `plugins/<id>/` — one plugin `.py` and its `eli_plugin.json` — the layout
   `review.py` and the review workflow expect; the template ships no `plugins/`
   folder of its own.
2. **Generate your signing key**, once:
   ```bash
   python tools/marketplace/publish.py --new-key ~/.eli-marketplace-key
   ```
   It prints the public key. Keep the private half offline and backed up; losing
   it means re-signing every listing, and leaking it means anyone can publish as
   you.
3. **Bake the public key into ELI.** In `eli/plugins/integrity.py`:
   ```python
   OFFICIAL_PUBLISHER_KEY = "<the base64 public key>"
   ```
   And the registry address in `eli/plugins/marketplace.py`:
   ```python
   OFFICIAL_REGISTRY_URL = "https://<your-domain>/index.json"
   ```
   This build has both set: `OFFICIAL_PUBLISHER_KEY` holds the `eli-marketplace`
   public key and `OFFICIAL_REGISTRY_URL` is `https://plugins.geteli.tech/index.json`,
   so the curated registry is listed as "ELI Marketplace" (id `eli-official`) and is
   enabled by default. With `OFFICIAL_REGISTRY_URL` empty — a build that has not
   been pointed at a store — **no official registry appears at all**: ELI does not
   invent a store it has not been pointed at. Both can be overridden with
   `ELI_MARKETPLACE_PUBLISHER_KEY` and `ELI_MARKETPLACE_URL`, which is how you test
   before shipping, and how anyone else can run their own curated registry from an
   ELI build. An empty variable falls back to the built-in value; it does not switch
   the registry off.
4. **Configure CI**: set the repo variable `ELI_REPO` to the ELI repository both
   workflows check out `tools/marketplace/` from (`ELI_REF` picks the branch or tag,
   default `main`). The shopfront build also reads `MARKETPLACE_NAME` (default
   "ELI Marketplace") and `MARKETPLACE_DOMAIN`.
5. **Publish the shopfront**: set the repo's GitHub Pages source to GitHub Actions.
   `publish-site.yml` then runs on every push to `main` that touches `index.json` or
   `plugins/**`: it refuses an index that holds an unsigned listing, builds the page
   with `tools/marketplace/build_site.py` (one self-contained HTML file, no install
   button), and deploys `index.html`, `index.json` and a `CNAME` for
   `MARKETPLACE_DOMAIN`. Point your domain at it. The deployed site carries no plugin
   sources, so serve each one from where its listing's `source` URL points (a release
   asset, say).

---

## 4. Reviewing a submission

When a PR arrives, CI has already run. Read its comment first, then:

```bash
python tools/marketplace/review.py plugins/<the-submission>
```

It prints `REJECT` (exit 1: malicious, a bad manifest, or code that uses capabilities
its manifest does not declare) or `NEEDS_HUMAN_REVIEW` (exit 0); exit 2 means the
folder could not be evaluated. `--json` gives the full report, `--strict` also fails
on non-blocking findings.

What to actually look at, in the order that catches the most:

- **Undeclared capabilities.** `review.py` blocks on these, and it is the single
  highest-signal check: the consent dialog the user sees is generated from the
  manifest, so code reaching past it is asking for less than it takes.
- **Over-declared permissions.** Not malicious, but query it. A plugin should ask
  for the least it needs, and a broad ask is often copy-paste rather than intent.
- **Does the permission set match the description?** A unit converter that wants
  `network` needs to explain itself. No scanner can judge this; it is the reason a
  human reviews at all.
- **Coverage.** If the report says engines were unavailable, that is *reduced
  coverage, not a pass*. Run it somewhere with ClamAV and YARA (the `yara-python`
  module plus a ruleset), or lean on the CI run for ClamAV.

Then approve by signing:

```bash
python tools/marketplace/publish.py plugins/<the-submission>/plugin.py \
    --source-url https://<your-domain>/plugins/<id>.py \
    --sign-key ~/.eli-marketplace-key \
    --publisher eli-marketplace
```

That emits the listing JSON — including `sha256` and `signature` — to paste into
`index.json`. Merge, and it is live (`publish-site.yml` rebuilds the shopfront from the
merged index). The publisher id must be `eli-marketplace`: the client refuses a curated
listing signed by any other id, however valid the signature. `publish.py` also refuses a
plugin whose own scan is not clean unless you pass `--allow-findings`, and a listing with
findings still stops every one-click install.

**Re-sign on every change.** The signature covers the file. A new version is a new
signature, and a stale `sha256` is a hard refusal on every machine that tries.

---

## 5. What the client enforces

Worth knowing precisely, because the curated and community paths differ on purpose:

| | Community registry | Official (curated) registry |
|---|---|---|
| Unsigned listing | Warning — operator decides | **Refused** |
| Signed by an unknown key | Warning | **Refused** |
| Signed by a trusted key other than `eli-marketplace` | Accepted as signed | **Refused** |
| Signature does not verify | Refused | Refused |
| `sha256` mismatch | Refused | Refused |
| Malware scan verdict *malicious* | Refused | Refused |
| Malware scan verdict *suspicious* | Warning; one-click stops and the operator decides | Same |
| Code uses a capability the manifest does not declare (static check before install) | Refused | Refused |
| Undeclared capability at runtime | Blocked by the audit hook | Blocked by the audit hook |

The asymmetry in the first three rows is the whole point. On a community registry an
unsigned plugin is ordinary. On the curated one it is evidence of tampering,
because nothing reaches that index without being signed — so treating it as a
warning would let anyone who can rewrite the index, or sit in the middle of the
download, strip the signature and be waved through with a yellow badge.

A plugin that passes is written to `<id>/` (`plugin.py`, `eli_plugin.json`,
`.integrity.json`) in ELI's plugins folder — `plugins/` in a source checkout, `plugins/`
in ELI's data folder in an installed copy, `ELI_PLUGINS_DIR` overrides — switched off and
with no permission granted.

MCP server listings (`"kind": "mcp"`) take a different path. ELI never sees a server's
source, only the command that starts it, so there is nothing to hash or scan, and in this
release no signature or curation check applies to them on either kind of registry. What
ELI checks is that the runtime exists and that the server answers a real MCP handshake —
which means starting it — before it saves the server, switched off.

Two further guards, both tested:

- A registry entry in the operator's config **cannot set `curated`** or claim the
  official id. Otherwise a config file could award itself the official badge.
- An operator-added publisher key **cannot shadow the official key**, and the
  official key cannot be removed. Otherwise "signed by the maintainer" would mean
  "signed by whoever edited your config". If you do not want the curated registry,
  switch the registry off — do not remove the key, which would stop verification
  without stopping installs. In this release the only switch that holds is
  `"disabled": ["eli-official"]` in `plugin_registries.json` in ELI's config folder
  (`config/` in a source checkout), and adding or removing a source rewrites that file
  without it. The Sources tab has no toggle, and
  `set_registry_enabled()` or `remove_registry()` on the official entry report success
  without changing anything.

---

## 6. What curation does not mean

Say this on the shopfront, plainly. Review raises the floor; it does not make a
guarantee, and a store that implies otherwise is selling a warranty it cannot
honour:

- Review means a person read the code and nothing objected. It does not prove the
  author is who they say, that the plugin does what it claims, or that a later
  version is as careful as the one that was read.
- ELI still shows the user every capability before install, installs the plugin
  switched off with none of them granted, asks for each one the first time the
  plugin uses it (and denies it where nobody can be asked), and enforces them at
  runtime through the audit hook. **Curation is a layer on top of consent, not
  a replacement for it** — an approved plugin that asks for `process_exec` is
  still asking for unlimited access, and the user still gets to say no.
- Payment is between the buyer and the seller. Review is not escrow.
