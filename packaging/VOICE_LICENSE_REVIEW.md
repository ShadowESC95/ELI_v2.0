# ELI Piper Voice License Review

This report is packaging guidance, not a replacement for formal legal review.
Voice licences follow the dataset each voice was trained on, as its upstream
`MODEL_CARD` on [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
states it (read 2026-11-20). From v2.5.36 ELI's code is Apache-2.0, so a release
bundle may be passed on commercially; every voice in it keeps its own licence.

## Voices kept out of every release

Listed by name in `RESTRICTED_VOICE_NAMES` (`eli/runtime/voice_assets.py`, mirrored
by `scripts/asset_release_policy.py`), so every quality variant is excluded from the
`local-assets-v2.1` pack, from `--with-github-assets` restore and therefore from the
release builds. A user may still download them for personal use.

### `en_GB-cori-high`

- ONNX: `tts_piper/piper/en_GB-cori-high.onnx`
- Classification: **exclude** (auto-restore)
- Commercial bundle default: **exclude**
- Reason: LibriVox upstream (the card says public domain); clearance pending — use `en_US-amy-medium` for the out-of-the-box voice instead.

### `en_US-lessac-high`

- ONNX: `tts_piper/piper/en_US-lessac-high.onnx`
- Config present: `True`
- Classification: **license_review_required**
- Commercial bundle default: **exclude**
- Reason: Upstream MODEL_CARD points to the Blizzard 2013 Lessac dataset license; **excluded from `--with-github-assets` restore**. Fetch manually from upstream if you accept those terms.

### `en_US-lessac-medium`

- Classification: **exclude** (same Lessac upstream family as `-high`)

### `en_US-ryan-high`, `en_US-ryan-medium`

- ONNX: `tts_piper/piper/en_US-ryan-high.onnx`, `tts_piper/piper/en_US-ryan-medium.onnx`
- Config present: `True`
- Classification: **noncommercial_risk**
- Commercial bundle default: **exclude**
- Reason: Upstream MODEL_CARD dataset license is CC BY-NC-SA 4.0.

## Voices that ship (the `local-assets-v2.1` pack, bundled in every release build)

| Voice | Dataset licence (upstream card) | Classification |
|---|---|---|
| `de_DE-thorsten-medium`, `cs_CZ-jirka-medium`, `pl_PL-gosia-medium` | CC0 | cleared |
| `es_ES-carlfm-x_low` | Public domain | cleared |
| `fr_FR-siwis-medium`, `nl_NL-mls-medium` | CC BY 4.0 | cleared (attribution) |
| `en_GB-northern_english_male-medium` | CC BY-SA 4.0 | cleared (attribution, share-alike) |
| `en_US-amy-medium` (default), `it_IT-riccardo-x_low` | "See URL" (mimic3-voices; M-AILABS) | **license_review_required** |
| `en_GB-alan-medium` | "See URL" — the mimic3-voices `apope_low` LICENSE reads "Copyright 2022 Mycroft AI, All Rights Reserved" | **license_review_required** |
| `zh_CN-huayan-x_low` | Unknown (the card states none) | **license_review_required** |
| `ru_RU-ruslan-medium` | CC BY-NC-SA 4.0 (RUSLAN corpus) | **noncommercial_risk** — shipped today |

## Packaging rule

- Do **not** include voices classified `exclude` or `noncommercial_risk` in a distribution bundle; under Apache-2.0 every public release bundle can be passed on commercially.
- Do **not** assume repository-level metadata resolves dataset/model-card licensing conflicts.
- Retain MODEL_CARD/license evidence for any voice approved for shipping.

## Immediate implication

- `en_US-ryan-high` / `en_US-ryan-medium` stay excluded from every redistribution bundle unless you obtain independent legal clearance.
- `en_US-lessac-high` / `en_US-lessac-medium` are excluded from ELI's public auto-restore; install manually only after reviewing Blizzard/Lessac upstream terms.
- `en_GB-cori-high` is excluded from auto-restore and the GitHub asset pack; **`en_US-amy-medium`** is the default out-of-the-box Piper voice.
- `ru_RU-ruslan-medium` is non-commercial by its dataset licence but is in the `local-assets-v2.1` pack and every release build; it is not in `RESTRICTED_VOICE_NAMES`. The voices marked `license_review_required`, including the default `en_US-amy-medium`, need their terms confirmed.
