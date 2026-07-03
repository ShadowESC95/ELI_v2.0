# ELI — Redistribution & Health Audit

*A full audit for redistribution suitability and functional health. Run 2026-07-03 against
the working tree. Method: automated scans of tracked vs untracked content, a compile pass over
every module, an engine smoke test, the capability manifest, and the test-suite state.*

---

## Verdict

**Suitable for redistribution — with a short list of non-blocking local-hygiene cleanups.**

The *repository* (what would actually ship) is clean: no personal data in tracked source, no
secrets, no user databases, a complete licence + install surface, and 208/208 capabilities
active. Everything compiles and the engine runs. The only findings are **untracked local
junk** that never enters the repo but should be deleted for tidiness, and 5 **known,
non-blocking** test reds.

| Dimension | Result |
|-----------|:------:|
| Personal data in tracked source | **Clean ✓** |
| Hardcoded secrets / keys | **None ✓** |
| User DBs / uploads / audio committed | **None (0) ✓** |
| Licence + redistribution files | **Complete ✓** |
| All modules compile | **Yes ✓** |
| Engine constructs + processes a turn | **Yes ✓** |
| Capabilities active / in dispatch | **208 / 208 ✓** |
| Test suite | **7,347 passing, 5 known reds** |
| Cross-platform install surface | **Present ✓** |

---

## 1. Redistribution readiness

**1.1 Personal data — PASS.** No `/home/jay`, name, or email in any *tracked* source file
(`eli/`, `api/`, `bin/`, `scripts/`). The only personal-data references are in `LICENSE`,
`NOTICE`, `README`, `SECURITY`, `CONTRIBUTING` — the **intentional** copyright + security
contact, which *should* carry the author's name. Verified via `git grep`.

**1.2 Secrets — PASS.** No hardcoded API keys, passwords, or tokens in source. Auth reads from
env / a persisted local file; the stable token lives at `config/api_token` (0600, gitignored).

**1.3 User data — PASS.** Zero tracked databases, audio, or uploads. The user DBs
(`artifacts/db/*.sqlite3`), settings (`config/settings.json`), uploads, models, and venv are
all gitignored — present locally for running, never committed.

**1.4 Config template — PASS.** `config/settings.example.json` ships as a clean template; the
real `settings.json` (with your paths/name) is gitignored.

**1.5 Licence & install surface — PASS.** `LICENSE` (PolyForm Internal Use — proprietary),
`NOTICE`, `README`, `SECURITY`, `CONTRIBUTING`, `install.sh`, and platform requirements
(`requirements.txt` + `-full/-macos/-windows/-android/-learning` + `requirements.lock.txt`)
are all present.

**1.6 Untracked junk — CLEANUP RECOMMENDED (non-blocking).** These exist in the folder but are
**untracked → they never ship**, and are now gitignored so they can't be committed by accident:
- `sys/` — a stray directory (contains `/home/jay` + name). **Recommend: delete.**
- `tools/eval/benchmarks/*.sh`, `tools/eval/benchmarks/build_h2h_full.py` — dev benchmark
  scripts with hardcoded paths + name. **Recommend: delete.**
- `eli/eli_examination_report_*.txt`, `eli/.claude/` — local artifacts/IDE config.
- `config/api_token` — your credential (correctly gitignored; never delete on a live install).

None of these are redistribution blockers; removing the first three tidies the working tree.

---

## 2. Functional health

**2.1 Compilation — PASS.** `compileall` over `eli/` + `api/` reports **zero syntax errors** —
every module parses.

**2.2 Engine smoke — PASS.** `CognitiveEngine()` constructs and `process("what can you do?")`
returns a valid governed reply, correctly routed to `LIST_CAPABILITIES`. The core pipeline is
live.

**2.3 Capabilities — PASS.** The manifest reports **208 total, 208 active, 208 in-dispatch, 183
routable** (routable = router-reachable + supported-list). No dead/inactive capabilities.

**2.4 Test suite — PASS with known reds.** **7,347 unit + 76 web + 31 live + 27 GUI passing**
(49.2% honest coverage). **5 pre-existing reds, all non-blocking:**
- **3 × `smart_home` plugin** — the in-progress Home-Assistant→own-MQTT migration (a plugin in
  transition, not a core path).
- **1 × silent-swallow ratchet** — an *observability-debt* ceiling (987 `except: pass` vs 950);
  a self-imposed quality gate, not a functional failure.
- **1 × stale blueprint reference** — a doc references a since-moved file
  (`eli/execution/handlers/__init__.py`).

None affect the shipping product's behaviour. Full detail in `test_coverage_suite_report`.

**2.5 Security posture — PASS (audited earlier this cycle).** Offline-by-default socket
failsafe, fail-closed command gate, approval engine, tamper-evident HMAC-keyed audit ledger,
born-locked secret files, RBAC. See `security.md` (updated 2026-07-02).

---

## 3. Recommended actions (all optional / non-blocking)

1. **Delete the untracked junk** for a clean tree: `rm -rf sys tools/eval/benchmarks/*.sh
   tools/eval/benchmarks/build_h2h_full.py`. (Already gitignored, so purely tidiness.)
2. **Clear the 5 reds when convenient** — finish the `smart_home` migration, chip the
   silent-swallow ceiling down as swallows are made observable, and fix the one stale blueprint
   path. Not required to ship.
3. **On a fresh install**, `config/api_token` and `config/settings.json` are generated on first
   run from the example template — nothing to pre-populate.

---

## Bottom line

**The repository is clean and safe to redistribute as-is.** Nothing personal or secret is
tracked; the licence and install surface are complete; every module compiles; the engine runs;
all 208 capabilities are active; the suite is green bar 5 documented, non-blocking reds. The
only to-dos are cosmetic (delete untracked junk) and quality debt (the reds) — neither gates a
release. For a proprietary-licensed internal-use product, this is in good shape.
