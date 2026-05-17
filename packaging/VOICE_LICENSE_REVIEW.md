# ELI Piper Voice License Review

This report is packaging guidance, not a replacement for formal legal review.

## Current packaged voice assets detected

### `en_GB-cori-high`

- ONNX: `tts_piper/piper/en_GB-cori-high.onnx`
- Config present: `True`
- Classification: **review_before_ship**
- Commercial bundle default: **manual_review**
- Reason: Upstream model card identifies a public-domain LibriVox dataset; still retain upstream model-card/license evidence before shipping.

### `en_US-lessac-high`

- ONNX: `tts_piper/piper/en_US-lessac-high.onnx`
- Config present: `True`
- Classification: **license_review_required**
- Commercial bundle default: **manual_review**
- Reason: Upstream MODEL_CARD points to the Blizzard 2013 Lessac dataset license; commercial redistribution requires explicit review.

### `en_US-ryan-high`

- ONNX: `tts_piper/piper/en_US-ryan-high.onnx`
- Config present: `True`
- Classification: **noncommercial_risk**
- Commercial bundle default: **exclude**
- Reason: Upstream MODEL_CARD dataset license is CC BY-NC-SA 4.0.

## Packaging rule

- Do **not** automatically include voices classified `exclude` in a commercial distribution bundle.
- Do **not** assume repository-level metadata resolves dataset/model-card licensing conflicts.
- Retain MODEL_CARD/license evidence for any voice approved for shipping.

## Immediate implication

- `en_US-ryan-high` should be excluded from a commercial redistribution bundle by default unless you obtain independent legal clearance.
- `en_US-lessac-high` requires review of the Blizzard/LESSAC dataset license referenced by its upstream model card.
- `en_GB-cori-high` appears materially lower risk from the available upstream card, but it should still be documented before shipping.
