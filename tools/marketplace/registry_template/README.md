# Hosting an ELI registry on GitHub Pages

A registry is one static file: `index.json` over HTTPS. GitHub Pages serves that for
free, which is why it is the recommended starting point — there is no server to run,
no database, and nothing for ELI's author to own.

## Setup

1. Create a public repo from this template, e.g. `eli-registry`.
2. Put `index.json` at the root and each plugin under `plugins/<id>/`: one `.py` source
   and its `eli_plugin.json` manifest — the layout `tools/marketplace/review.py` and the
   `review-submission.yml` workflow expect.
3. Settings → Pages → deploy from `main` / root. Pages then serves the repo as it is:
   `index.json` and `plugins/`.
4. Your registry URL is `https://<user>.github.io/eli-registry/index.json`.
5. In ELI: **Settings ▸ 🛒 Marketplace ▸ Sources**, enter an id and that URL and press
   **Add source**. Browsing needs ELI's network switch on; offline, only the built-in
   plugins are listed.

That is the whole marketplace. A website for browsing is optional and separate — it
can render the same `index.json`, but it must never install anything itself; it hands
out the registry URL and a listing id, and the desktop client does the verifying,
scanning and asking. `tools/marketplace/build_site.py` builds such a page (one HTML
file, no install button). This template's `publish-site.yml` runs it on every push to
`main` and deploys the result with GitHub Actions, which needs the Pages source set to
GitHub Actions instead of step 3; that site holds `index.html`, `index.json` and a
`CNAME`, not the plugin sources, so the listings' `source` URLs must then point
somewhere else (release assets, say). It also refuses an index that holds an unsigned
listing, which suits a curated registry: for a community one with unsigned plugins,
drop that step.

## Why GitHub Pages satisfies the client's rules

ELI's `netguard.safe_fetch` refuses anything that is not plain http(s) to a public
address, re-checks every redirect hop, and caps the body. Pages gives you HTTPS with
a valid certificate on a public host and no redirect games, so it passes without
special-casing. It also means:

| Requirement | Why it matters |
|---|---|
| `https://` source URLs | a plain-http download **stops the one-click install** — it can be altered in transit |
| a correct `sha256` per listing | no checksum also stops one-click; a *stale* one is a hard refusal everywhere |
| honest `permissions` | undeclared capability use is a refusal, not a warning |

## Publishing

Never hand-write the hash. From an ELI checkout:

```bash
python tools/marketplace/publish.py plugins/unit_converter/plugin.py \
    --source-url https://<user>.github.io/eli-registry/plugins/unit_converter/plugin.py
```

It reads the manifest beside the plugin (`eli_plugin.json`, or `--manifest <file>`),
validates it, checks the code against the declared permissions, runs the same scanners
the user's machine will run, and prints the entry to paste into `index.json`. It
refuses to emit a listing that would be rejected on the other end, and one whose scan
is not clean unless you pass `--allow-findings`.

**Regenerate the hash on every change to the source.** A listing whose hash no longer
matches fails for everyone, which reads to users as "this publisher ships broken
plugins".

## Signing (optional, recommended)

```bash
python tools/marketplace/publish.py --new-key ed25519.key      # once
python tools/marketplace/publish.py plugins/thing/plugin.py \
    --sign-key ed25519.key --publisher your-id \
    --source-url https://.../thing/plugin.py
```

Publish the printed public key in your README. An operator adds it once to their
trusted publishers, and everything you sign afterwards verifies for them. There is no
Marketplace-tab control for that: it is
`eli.plugins.integrity.trust_publisher("your-id", "<public key>")`, which stores the key
in `plugin_publishers.json` in ELI's config folder. Unsigned plugins are not blocked —
they are shown as unverified, which is the honest default for a community marketplace.

## Review

Take listings as pull requests. That gives you a public record of who added what and
when, without hosting anything. The template's `review-submission.yml` runs
`tools/marketplace/review.py` on each `plugins/<id>/` a pull request changes, fails the
PR on a bad manifest, code that uses capabilities its manifest does not declare, or a
malicious scan verdict, and posts the report on the PR. Set the repo variable `ELI_REPO`
(and `ELI_REF`, default `main`) to the ELI repository it should take `review.py` from.
It does not compare the hashes in `index.json` with the files; `publish.py` regenerates
them.

## What ELI will never do

- treat your registry as trusted because it is popular — a community registry is not
  curated: the Marketplace tab says so, and each listing shows only what was checked
  (signed, checksum only, or unverified);
- install from a website;
- let a listing on a public registry point the download at a private or loopback
  address (a registry you add yourself on your own machine or network is the one
  exception, and ELI warns and records it when you add it).
