"""Tests for glossary masking and enforcement."""

from pathlib import Path

from translategemma_cli.glossary import Glossary, GlossarySession, should_apply_glossary


def test_non_overlapping_mask(tmp_path: Path):
    csv_path = tmp_path / "glossary.csv"
    csv_path.write_text(
        "source,target,wrong\n"
        "正极活性材料,Cathode Active Material (CAM),\n"
        "正极,Cathode,\n"
        "理想汽车,Li Auto,Ideal Auto\n",
        encoding="utf-8",
    )
    g = Glossary(csv_path)

    text = "正极活性材料与理想汽车"
    masked, session = g.mask_for_translation(text)
    assert "正极活性材料" not in masked
    assert "理想汽车" not in masked
    assert "⟦G0⟧" in masked
    assert "⟦G1⟧" in masked
    assert session.placeholders["⟦G0⟧"] == "Cathode Active Material (CAM)"
    assert session.placeholders["⟦G1⟧"] == "Li Auto"

    out = g.finalize_output("⟦G0⟧ and Ideal Auto", session)
    assert out == "Cathode Active Material (CAM) and Li Auto"


def test_multiple_occurrences(tmp_path: Path):
    csv_path = tmp_path / "glossary.csv"
    csv_path.write_text("source,target\n理想汽车,Li Auto\n", encoding="utf-8")
    g = Glossary(csv_path)

    masked, session = g.mask_for_translation("理想汽车和理想汽车")
    assert masked.count("⟦G") == 2
    assert session.source_counts["理想汽车"] == 2

    out = g.finalize_output("⟦G0⟧ and ⟦G1⟧", session)
    assert out == "Li Auto and Li Auto"


def test_mask_does_not_add_instruction_hint(tmp_path: Path):
    csv_path = tmp_path / "glossary.csv"
    csv_path.write_text("source,target\n理想汽车,Li Auto\n", encoding="utf-8")
    g = Glossary(csv_path)

    masked, _ = g.mask_for_translation("理想汽车")
    assert masked == "⟦G0⟧"
    assert "Important:" not in masked


def test_strip_instruction_leak():
    leaked = (
        "Important: Do not change tokens like Li Auto during translation."
        "Copy them exactly; do not translate or remove them.Li Auto"
    )
    assert Glossary.strip_instruction_leak(leaked) == "Li Auto"


def test_should_apply_when_text_has_glossary_terms(tmp_path: Path):
    csv_path = tmp_path / "glossary.csv"
    csv_path.write_text("source,target\n理想汽车,Li Auto\n", encoding="utf-8")
    g = Glossary(csv_path)

    assert should_apply_glossary("理想汽车", None, default=False) is True
    assert should_apply_glossary("普通文本", None, default=False) is False
    assert should_apply_glossary("理想汽车", False, default=True) is False


def test_all_glossary_terms_masked_in_real_file():
    glossary_path = Path(__file__).resolve().parents[1] / "docs" / "glossary.csv"
    g = Glossary(glossary_path)
    sample = "理想汽车使用正极活性材料和锂离子电池"
    masked, session = g.mask_for_translation(sample)
    for source in session.sources:
        assert source not in masked
    assert len(session.placeholders) >= 3
