from pathlib import Path


LABS_SOURCE = Path("eli/gui/labs_tab.py")


def _source() -> str:
    return LABS_SOURCE.read_text(encoding="utf-8")


def test_report_builder_exposes_quality_citation_depth_controls():
    source = _source()

    assert "_TEMPLATES" not in source
    assert "Generate Template" not in source
    assert "Template:" not in source
    assert "Report Builder: document generation profile" in source
    assert "_QUALITY_PROFILES" in source
    assert "_CITATION_POLICIES" in source
    assert "_DEPTH_PROFILES" in source
    assert "Document type:" in source
    assert "Generation Plan" in source
    assert "Plan Summary" in source
    assert "Raw Debug Prompt" in source
    assert "Quality bar:" in source
    assert "Citation policy:" in source
    assert "Run internal review pass" in source
    assert "Auto-save finished draft" in source
    assert "📄 Report Builder" in source


def test_report_builder_keeps_document_type_generation_profiles():
    source = _source()

    for doc_type in (
        '"Document"',
        '"Article"',
        '"Research Article"',
        '"Review Article"',
        '"Master\'s Thesis"',
        '"PhD Dissertation"',
        '"Peer-Review Paper"',
        '"Literature Review"',
        '"Research Proposal"',
        '"Lab Report"',
        '"Technical Report"',
        '"Simulation Report"',
    ):
        assert doc_type in source

    assert "document types define quality" in source
    assert "fill-in-the-blank bodies" in source


def test_report_prompts_enforce_evidence_and_acceptance_contracts():
    source = _source()

    assert "QUALITY BAR:" in source
    assert "EVIDENCE DISCIPLINE:" in source
    assert "FINAL ACCEPTANCE TEST BEFORE OUTPUT:" in source
    assert "[source needed]" in source
    assert "no fake file paths" in source
    assert "no fake citations" in source
    assert "Evidence Ledger / Source Coverage Matrix" in source


def test_report_pipeline_has_review_revision_and_autosave():
    source = _source()

    assert "def _build_revision_prompt" in source
    assert "critiquing draft against quality contract" in source
    assert "applying review feedback" in source
    assert "def _autosave_report" in source
    assert "artifacts" in source and "documents" in source
