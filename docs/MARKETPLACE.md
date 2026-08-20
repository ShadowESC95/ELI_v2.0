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
   only the maintainer holds. A listing on the official registry that is not
   validly signed by that key is **refused by the client**, not warned about — see
   §5.
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
| Automated evaluation | GitHub Actions (`review-submission.yml`, in `registry_template/`) | Runs the same checks the user's machine runs — with ClamAV and YARA actually installed, so coverage is better than most users get |
| Plugin artifacts | GitHub Releases | CDN-backed, free bandwidth, immutable per tag, and the URL is stable — which matters because the `sha256` in the listing pins the file |
| Public shopfront | Cloudflare Pages (or Netlify/GitHub Pages) on your own domain | Free static hosting, and a domain makes it *ELI's* marketplace rather than "a GitHub repo" |
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
   contains `index.json`, a `plugins/` directory, the README submitters read, and
   the CI workflow.
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
   Both are empty in a stock build, and while they are empty **no official
   registry appears at all** — ELI does not invent a store it has not been
   pointed at. Both can be overridden with `ELI_MARKETPLACE_PUBLISHER_KEY` and
   `ELI_MARKETPLACE_URL`, which is how you test before shipping, and how anyone
   else can run their own curated registry from an ELI build.
4. **Configure CI**: set the repo variable `ELI_REPO` to the ELI repository the
   workflow should pull `review.py` from.
5. **Publish the shopfront** on your domain, pointing at the same `index.json`.

---

## 4. Reviewing a submission

When a PR arrives, CI has already run. Read its comment first, then:

```bash
python tools/marketplace/review.py plugins/<the-submission>
```

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
  coverage, not a pass*. Run it somewhere with ClamAV and YARA, or lean on the CI
  run, which has both.

Then approve by signing:

```bash
python tools/marketplace/publish.py plugins/<the-submission>/plugin.py \
    --source-url https://<your-domain>/plugins/<id>.py \
    --sign-key ~/.eli-marketplace-key \
    --publisher eli-marketplace
```

That emits the listing JSON — including `sha256` and `signature` — to paste into
`index.json`. Merge, and it is live.

**Re-sign on every change.** The signature covers the file. A new version is a new
signature, and a stale `sha256` is a hard refusal on every machine that tries.

---

## 5. What the client enforces

Worth knowing precisely, because the curated and community paths differ on purpose:

| | Community registry | Official (curated) registry |
|---|---|---|
| Unsigned listing | Warning — operator decides | **Refused** |
| Signed by an unknown key | Warning | **Refused** |
| Signature does not verify | Refused | Refused |
| `sha256` mismatch | Refused | Refused |
| Malware scan finds indicators | Refused | Refused |
| Undeclared capability at runtime | Blocked by the audit hook | Blocked by the audit hook |

The asymmetry in the first two rows is the whole point. On a community registry an
unsigned plugin is ordinary. On the curated one it is evidence of tampering,
because nothing reaches that index without being signed — so treating it as a
warning would let anyone who can rewrite the index, or sit in the middle of the
download, strip the signature and be waved through with a yellow badge.

Two further guards, both tested:

- A registry entry in the operator's config **cannot set `curated`** or claim the
  official id. Otherwise a config file could award itself the official badge.
- An operator-added publisher key **cannot shadow the official key**, and the
  official key cannot be removed. Otherwise "signed by the maintainer" would mean
  "signed by whoever edited your config". If you do not want the curated registry,
  disable the registry — do not remove the key, which would stop verification
  without stopping installs.

---

## 6. What curation does not mean

Say this on the shopfront, plainly. Review raises the floor; it does not make a
guarantee, and a store that implies otherwise is selling a warranty it cannot
honour:

- Review means a person read the code and nothing objected. It does not prove the
  author is who they say, that the plugin does what it claims, or that a later
  version is as careful as the one that was read.
- ELI still asks the user for each capability at install, and still enforces them
  at runtime through the audit hook. **Curation is a layer on top of consent, not
  a replacement for it** — an approved plugin that asks for `process_exec` is
  still asking for unlimited access, and the user still gets to say no.
- Payment is between the buyer and the seller. Review is not escrow.
