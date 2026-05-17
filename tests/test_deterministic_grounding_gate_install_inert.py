from __future__ import annotations


def test_public_deterministic_grounding_gate_install_does_not_mutate_process():
    from eli.runtime import deterministic_grounding_gate as gate

    def original_process(self, text="", *args, **kwargs):
        return {"ok": True, "content": "original"}

    class DummyEngine:
        process = original_process

    before = DummyEngine.process
    returned = gate.install(DummyEngine)

    assert returned is DummyEngine
    assert DummyEngine.process is before
    assert not hasattr(DummyEngine.process, "_eli_quick_only_bypass_v14")
    assert not getattr(DummyEngine, "_eli_quick_only_bypass_v14", False)
