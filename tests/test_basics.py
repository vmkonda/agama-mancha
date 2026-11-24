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
    assert parse_tsv("") == []


def test_parse_tsv_rejects_plain_text():
    import pytest

    # What Tesseract prints when the "tsv" config isn't found: plain text, not TSV.
    with pytest.raises(RuntimeError):
        parse_tsv("फलम् ।\n")


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


def test_model_checksums_match_git_blob_ids():
    from amocr.setup import _git_blob_id

    assert _git_blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # git's empty blob


def test_surya_html_to_lines():
    from amocr.engines.surya import html_to_lines

    h = "<p>क ख ग<sup>१</sup> ।<br/>घ ङ ॥ १ ॥</p>"
    assert html_to_lines(h) == ["क ख ग१ ।", "घ ङ ॥ १ ॥"]
    assert html_to_lines("<p>a &amp; b</p><p>c</p>") == ["a & b", "c"]


def test_surya_split_like():
    from amocr.engines.surya import split_like

    # Re-flowed paragraph split back along three printed lines of similar length.
    text = "अ आ इ ई उ ऊ ए ऐ ओ"
    assert split_like(text, ["अ आ इ", "ई उ ऊ", "ए ऐ ओ"]) == ["अ आ इ", "ई उ ऊ", "ए ऐ ओ"]
    # Breaks follow line lengths, not exact words, so a misread word in a target line is harmless.
    assert split_like(text, ["अ आ इ", "ईई उ ऊ", "ए ऐ ओ"])[0] == "अ आ इ"
    assert split_like("एक", ["x", "y"]) == ["एक", ""]
    assert split_like("एक दो", ["only one line"]) == ["एक दो"]


def test_surya_place_lines():
    from amocr.engines.surya import place_lines

    tess = [{"text": "क ख", "bbox": [10, 10, 100, 30]}, {"text": "ग घ", "bbox": [10, 40, 100, 60]},
            {"text": "elsewhere", "bbox": [10, 500, 100, 520]}]
    assert place_lines(["क ख ग घ"], [0, 0, 120, 70], tess) == [("क ख", [10, 10, 100, 30]), ("ग घ", [10, 40, 100, 60])]
    # Line counts that can't be matched fall back to the block box.
    assert place_lines(["a", "b", "c"], [0, 0, 120, 70], tess) == [("a", [0, 0, 120, 70]), ("b", [0, 0, 120, 70]), ("c", [0, 0, 120, 70])]
