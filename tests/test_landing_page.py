"""Static checks for the public CORVUS × CRONOS integration overview page.

This is the bilingual (ES/EN) verification page — now served as
`web/overview.html` (the root `web/index.html` is the trilingual landing
hub that links to it, the CRONOS page, the Wolf demo, and the live console).
"""

from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web" / "overview.html"


def test_landing_page_is_a_bilingual_standalone_static_site():
    page = PAGE.read_text(encoding="utf-8")

    assert '<html lang="en"' in page
    assert 'data-language="es"' in page
    assert 'data-language="en"' in page
    assert 'data-es=' in page
    assert 'data-en=' in page
    assert "fetch(" not in page
    assert "--ink: #6C5D72" in page


def test_landing_page_states_the_actual_architecture_boundaries():
    page = PAGE.read_text(encoding="utf-8")

    for claim in (
        "CORVUS × CRONOS",
        "L1_GRICE",
        "L6_PEIRCE",
        "GATE",
        "SHA-256",
        "50.000 caracteres",
        "Qwen es opcional",
    ):
        assert claim in page
