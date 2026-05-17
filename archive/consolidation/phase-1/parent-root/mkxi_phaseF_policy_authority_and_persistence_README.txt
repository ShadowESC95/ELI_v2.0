MKXI Phase F — policy authority + persistence normalization

What this phase does
1. Adds eli/runtime/identity_runtime_policy.py
   - canonical helper for detecting identity/runtime questions
   - canonical helper for greeting-only phatic fastpath

2. Adds eli/runtime/persistence_writer.py
   - canonical helper for governed conversation-turn writes
   - canonical helper for governed memory writes

3. Patches eli/kernel/engine.py
   - removes direct hardcoded "who are you" returns from test-mode branches
   - makes the phatic fastpath greeting-only
   - escalates identity/runtime/memory questions to the full pipeline
   - delegates turn persistence to runtime helper

4. Patches eli/execution/router_enhanced.py
   - keeps identity questions routed to CHAT
   - renames override label to identity.chat_classified

How to run
  cd "${ELI_PROJECT_ROOT:-/path/to/ELI_MKXI}" || exit 1
  source .venv/bin/activate
  cp /mnt/data/mkxi_phaseF_policy_authority_and_persistence.sh .
  chmod +x mkxi_phaseF_policy_authority_and_persistence.sh

Analysis first:
  bash ./mkxi_phaseF_policy_authority_and_persistence.sh "${ELI_PROJECT_ROOT:-$PWD}" --analyze

Apply:
  bash ./mkxi_phaseF_policy_authority_and_persistence.sh "${ELI_PROJECT_ROOT:-$PWD}" --apply

After apply, inspect:
  sed -n '1,220p' ops/reports/*.phaseF_policy_authority_and_persistence/import_probe.txt
  sed -n '1,220p' ops/reports/*.phaseF_policy_authority_and_persistence/compileall.txt
  sed -n '1,220p' ops/reports/*.phaseF_policy_authority_and_persistence/engine_phatic_surface.txt

What this phase does NOT do
- It does not fully remove engine-owned memory extraction logic.
- It does not yet move all persistence policy out of engine.py.
- It does not yet make orchestrator the sole semantic authority.

Recommended next phase after this one
- Phase G: move engine-owned memory extraction / persistence intent into orchestrator result packets
- Phase H: make world_model the canonical owner for identity/runtime/memory summary state
