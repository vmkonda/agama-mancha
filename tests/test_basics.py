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
    # Garbled target lines (as Tesseract's often are) must not move a break by a word.
    text = "वर्णन प्रसङ्ग में सर्व प्रथम ध्यान की बात कही गयी है । अपना शरीर ही"
    targets = ["वर्णन प्रसद्ध में सवं प्रथम ध्यान की", "बात कही गयी है। अपना शरीर ही"]
    assert split_like(text, targets) == ["वर्णन प्रसङ्ग में सर्व प्रथम ध्यान की", "बात कही गयी है । अपना शरीर ही"]
    assert split_like("एक दो", ["only one line"]) == ["एक दो"]


def test_surya_place_lines():
    from amocr.engines.surya import place_lines

    tess = [{"text": "क ख", "bbox": [10, 10, 100, 30]}, {"text": "ग घ", "bbox": [10, 40, 100, 60]},
            {"text": "elsewhere", "bbox": [10, 500, 100, 520]}]
    assert place_lines(["क ख ग घ"], [0, 0, 120, 70], tess) == [("क ख", [10, 10, 100, 30]), ("ग घ", [10, 40, 100, 60])]
    # Line counts that can't be matched fall back to the block box.
    assert place_lines(["a", "b", "c"], [0, 0, 120, 70], tess) == [("a", [0, 0, 120, 70]), ("b", [0, 0, 120, 70]), ("c", [0, 0, 120, 70])]


def _review_base():
    return [{"text": "शीर्षक", "bbox": [0, 0, 10, 10], "block": 1, "label": "PageHeader"},
            {"text": "क ख ।", "bbox": [0, 20, 10, 30], "block": 2, "label": "Text"},
            {"text": "ग घ ॥ १ ॥", "bbox": [0, 40, 10, 50], "block": 2, "label": "Text"},
            {"text": "टीका", "bbox": [0, 60, 10, 70], "block": 3, "label": "Text"}]


def test_review_apply():
    from amocr.claude_review import apply_review, regions

    res = {"changes": [{"line": 2, "to": "क ग ।", "why": "misread"}, {"line": 4, "to": "टीका", "why": "unchanged"}],
           "insert": [{"after": 3, "text": "ङ च ॥ २ ॥", "why": "missed"}],
           "delete": [{"line": 1, "why": "smudge"}],
           "block_types": {"2": "verse", "3": "commentary"}}
    lines, changes, warnings = apply_review(res, _review_base())
    assert [ln["text"] for ln in lines] == ["क ग ।", "ग घ ॥ १ ॥", "ङ च ॥ २ ॥", "टीका"]
    assert lines[2]["bbox"] == [0, 40, 10, 50] and lines[2]["type"] == "verse"
    assert [c["to"] for c in changes] == ["", "क ग ।", "ङ च ॥ २ ॥"]  # an unchanged "change" isn't recorded
    assert any("deleted" in w for w in warnings)
    assert [(r["type"], len(r["lines"])) for r in regions(lines)] == [("verse", 3), ("commentary", 1)]
    # Nothing to correct is a valid answer.
    lines, changes, _ = apply_review({"changes": []}, _review_base())
    assert len(lines) == 4 and changes == [] and lines[0]["type"] == "header"


def test_review_apply_rejects_bad_edits():
    import pytest

    from amocr.claude_review import apply_review

    for bad in ({"changes": [{"line": 9, "to": "x"}]}, {"changes": [{"line": 2, "to": ""}]},
                {"changes": [{"line": 2, "to": "a"}, {"line": 2, "to": "b"}]}, {"insert": [{"after": 7, "text": "x"}]},
                {"block_types": {"2": "poem"}}):
        with pytest.raises(ValueError):
            apply_review(bad, _review_base())


def test_review_sheets(tmp_path):
    from PIL import Image

    from amocr.claude_review import MAX_PIXELS, MAX_W, build_sheets

    page = tmp_path / "page.png"
    Image.new("L", (1830, 2900), 255).save(page)
    lines = [{"bbox": [100, 100 + 60 * i, 1700, 145 + 60 * i]} for i in range(30)]
    sheets = build_sheets(page, lines, tmp_path)
    assert len(sheets) >= 2
    for s in sheets:
        im = Image.open(s)
        assert im.width <= MAX_W and im.width * im.height <= MAX_PIXELS


def test_screen_check_packet(tmp_path):
    import json
    from types import SimpleNamespace

    import pytest
    from PIL import Image

    from amocr.claude_review import prep_check, screen_text

    work = SimpleNamespace(id="B-x")
    lines = [{"text": f"पंक्ति {i}", "bbox": [10, 10 + 50 * i, 900, 50 + 50 * i], "block": 1, "label": "Text",
              "tess": "भिन्न" if i == 4 else None} for i in range(1, 7)]
    (tmp_path / "lines.json").write_text(json.dumps({"base": "surya-2.5-x", "lines": lines}, ensure_ascii=False))
    assert "  3  पंक्ति 3" in screen_text(9, lines) and "T:" not in screen_text(9, lines)
    page = tmp_path / "page.png"
    Image.new("L", (1000, 400), 255).save(page)
    (tmp_path / "flags.json").write_text(json.dumps({"work": "B-x", "page": 9, "flags": [{"line": 2, "why": "non-word"}]}))
    by_claude, by_tess = prep_check(work, 9, page, tmp_path)
    assert (by_claude, by_tess) == ([2], [4])
    check = (tmp_path / "check.txt").read_text()
    assert "  2  पंक्ति 2" in check and "flagged: non-word" in check and "T: भिन्न" in check and "  3  " not in check
    assert list(tmp_path.glob("check*.png"))
    (tmp_path / "flags.json").write_text(json.dumps({"work": "B-x", "page": 9, "flags": [{"line": 7}]}))
    with pytest.raises(ValueError):
        prep_check(work, 9, page, tmp_path)
