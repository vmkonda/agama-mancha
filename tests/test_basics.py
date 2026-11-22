from amocr.cli import parse_pages
from amocr.engines.tesseract import lines_to_text, parse_tsv
from amocr.metrics import cer, normalize
from amocr.pages import native_dpi
from amocr.textcheck import classify


def test_classify():
    assert classify("") == "none"
    assert classify("ब्रह्मादीनां प्रयच्छन्ति स्वबलेन समं फलम् । " * 3) == "devanagari"
    assert classify("brahmādīnāṃ prayacchanti svabalena samaṃ phalam " * 3) == "iast"
    # Kruti Dev style legacy-font junk: Latin letters, no diacritics
    assert classify("czãknhuka iz;PNfUr Locysu lea Qye~ " * 3) == "suspect"


def test_normalize_and_cer():
    assert normalize("फलम् || ३९ ||") == normalize("फलम् ॥ ३९ ॥")
    assert cer("फलम्", "फलम्") == 0.0
    assert cer("फलम", "फलम्") == 1 / 4
    assert cer("a b", "ab", ignore_space=True) == 0.0


def test_parse_pages():
    assert parse_pages("1,5,10-12", 20) == [1, 5, 10, 11, 12]
    assert parse_pages(None, 3) == [1, 2, 3]


def test_native_dpi_rotated():
    row = {"image_px": [2892, 1830], "rotation": 270, "width_pt": 439.0}
    assert native_dpi(row) == 300


def test_parse_tsv():
    hdr = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    rows = [
        "5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t90\tफलम्",
        "5\t1\t1\t1\t1\t2\t70\t10\t10\t20\t80\t।",
        "5\t1\t2\t1\t1\t1\t10\t50\t50\t20\t60\tइसी",
    ]
    lines = parse_tsv(hdr + "\n".join(rows) + "\n")
    assert [ln["text"] for ln in lines] == ["फलम् ।", "इसी"]
    assert lines[0]["conf"] == 85.0
    assert lines_to_text(lines) == "फलम् ।\n\nइसी\n"


def test_claude_validate():
    import pytest

    from amocr.catalog import Work
    from amocr.claude_session import to_text, validate

    w = Work(id="SL-0001", title="t", languages=["san"], sha256="x")
    res = {"work": "SL-0001", "page": 5, "mode": "direct",
           "regions": [{"type": "verse", "verse": "1", "lines": ["क ।", "ख ॥ १ ॥"]}]}
    assert validate(res, w, 5, None) == []
    assert to_text(res) == "क ।\nख ॥ १ ॥\n"
    assert any("dropped" in x for x in validate(res, w, 5, "a\nb\nc\nd\ne\n"))
    with pytest.raises(ValueError):
        validate(res | {"page": 6}, w, 5, None)
    with pytest.raises(ValueError):
        validate(res | {"regions": [{"type": "bogus", "lines": []}]}, w, 5, None)
