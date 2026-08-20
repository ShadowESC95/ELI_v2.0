# Hosting an ELI registry on GitHub Pages

A registry is one static file: `index.json` over HTTPS. GitHub Pages serves that for
free, which is why it is the recommended starting point — there is no server to run,
no database, and nothing for ELI's author to own.

## Setup

1. Create a public repo, e.g. `eli-registry`.
2. Put `index.json` at the root and plugin sources under `plugins/`.
3. Settings → Pages → deploy from `main` / root.
4. Your registry URL is `https://<user>.github.io/eli-registry/index.json`.
5. In ELI: **Settings ▸ 🛒 Marketplace ▸ Sources**, add that URL.

That is the whole marketplace. A website for browsing is optional and separate — it
can render the same `index.json`, but it must never install anything itself; it hands
out the registry URL and a listing id, and the desktop client does the verifying,
scanning and asking.

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

Never hand-write the hash.

```bash
python tools/marketplace/publish.py plugins/unit_converter.py \
    --source-url https://<user>.github.io/eli-registry/plugins/unit_converter.py
```

It validates the manifest, checks the code against the declared permissions, runs the
same scanners the user's machine will run, and prints the entry to paste into
`index.json`. It refuses to emit a listing that would be rejected on the other end.

**Regenerate the hash on every change to the source.** A listing whose hash no longer
matches fails for everyone, which reads to users as "this publisher ships broken
plugins".

## Signing (optional, recommended)

```bash
python tools/marketplace/publish.py --new-key ed25519.key      # once
python tools/marketplace/publish.py plugins/thing.py \
    --sign-key ed25519.key --publisher your-id \
    --source-url https://.../thing.py
```

Publish the printed public key in your README. An operator adds it once under trusted
publishers, and everything you sign afterwards verifies for them. Unsigned plugins are
not blocked — they are shown as unverified, which is the honest default for a
community marketplace.

## Review

Take listings as pull requests. That gives you a public record of who added what and
when, without hosting anything. CI can run `publish.py` over each changed plugin and
fail the PR on a bad manifest, a stale hash, or a scan finding.

## What ELI will never do

- treat your registry as trusted because it is popular — nothing here is curated, and
  ELI says so on every listing;
- install from a website;
- let a listing point the download at a private or loopback address.
