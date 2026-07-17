"""Static checks for the public CORVUS × CRONOS project page."""

from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "web" / "index.html"


def test_landing_page_is_a_bilingual_standalone_static_site():
    page = PAGE.read_text(encoding="utf-8")

    assert '<html lang="es"' in page
    assert 'data-language="es"' in page
    assert 'data-language="en"' in page
    assert 'data-es=' in page
    assert 'data-en=' in page
    assert "fetch(" not in page


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
