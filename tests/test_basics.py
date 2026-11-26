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

    def tl(text, box, words):
        return {"text": text, "bbox": box, "words": [{"text": t, "bbox": b} for t, b in words]}

    tess = [tl("क ख", [10, 10, 100, 30], [("क", [10, 10, 40, 30]), ("ख", [60, 10, 100, 30])]),
            tl("ग घ", [10, 40, 100, 60], [("ग", [10, 40, 40, 60]), ("घ", [60, 40, 100, 60])]),
            tl("elsewhere", [10, 500, 100, 520], [("elsewhere", [10, 500, 100, 520])])]
    out = place_lines(["क ख ग घ"], [0, 0, 120, 70], tess)
    assert [(x["text"], x["bbox"], x["box"]) for x in out] == [("क ख", [10, 10, 100, 30], "tesseract"), ("ग घ", [10, 40, 100, 60], "tesseract")]
    assert [w["bbox"] for w in out[1]["words"]] == [[10, 40, 40, 60], [60, 40, 100, 60]]
    # A Tesseract line that runs across two blocks (page number + running title) is cut at the block edge.
    head = [tl("१९८ श्रीमालिनी", [10, 10, 500, 40], [("१९८", [10, 10, 60, 40]), ("श्रीमालिनी", [300, 10, 500, 40])])]
    assert place_lines(["१९८"], [0, 0, 100, 50], head)[0]["bbox"] == [10, 10, 60, 40]
    assert place_lines(["श्रीमालिनी"], [250, 0, 520, 50], head)[0]["bbox"] == [300, 10, 500, 40]
    # Line counts that can't be matched: the block is shared out evenly, and marked as estimated.
    est = place_lines(["a", "b"], [0, 0, 100, 40], [])
    assert [(x["bbox"], x["box"]) for x in est] == [([0, 0, 100, 20], "estimated"), ([0, 20, 100, 40], "estimated")]
    assert est[0]["words"][0]["box"] == "estimated"


def test_surya_word_boxes():
    from amocr.engines.surya import word_boxes

    tw = [{"text": "स्वदेहं", "bbox": [0, 0, 100, 30]}, {"text": "चिन्तयेत्", "bbox": [120, 0, 260, 30]},
          {"text": "कष्णं", "bbox": [280, 0, 360, 30]}]  # Tesseract misread कृष्णं
    out = word_boxes("स्वदेहं चिन्तयेत्कृष्णं", [0, 0, 360, 30], tw)
    assert [w["text"] for w in out] == ["स्वदेहं", "चिन्तयेत्कृष्णं"]
    assert out[0]["bbox"] == [0, 0, 100, 30] and out[1]["bbox"] == [120, 0, 360, 30]  # one Surya word over two Tesseract words
    assert all(w["box"] == "tesseract" for w in out)
    assert word_boxes("एक दो", [0, 0, 100, 20], [])[1]["box"] == "estimated"


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
    (tmp_path / "lines.json").write_text(json.dumps({"base": "surya-2.5-x", "lines": lines}, ensure_ascii=False), encoding="utf-8")
    assert "  3  पंक्ति 3" in screen_text(9, lines) and "T:" not in screen_text(9, lines)
    page = tmp_path / "page.png"
    Image.new("L", (1000, 400), 255).save(page)
    (tmp_path / "flags.json").write_text(json.dumps({"work": "B-x", "page": 9, "flags": [{"line": 2, "why": "non-word"}]}), encoding="utf-8")
    by_claude, by_tess = prep_check(work, 9, page, tmp_path)
    assert (by_claude, by_tess) == ([2], [4])
    check = (tmp_path / "check.txt").read_text(encoding="utf-8")
    assert "  2  पंक्ति 2" in check and "flagged: non-word" in check and "T: भिन्न" in check and "  3  " not in check
    assert list(tmp_path.glob("check*.png"))
    (tmp_path / "flags.json").write_text(json.dumps({"work": "B-x", "page": 9, "flags": [{"line": 7}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        prep_check(work, 9, page, tmp_path)


def test_surya_classify():
    from amocr.engines.surya import classify

    verse = ["स्वदेहं चिन्तयेत्कृष्णं वृत्तं १षट्बिन्दुलाञ्छितम् ।", "चलं सचूचूशब्दं च वायवीं धारणां श्रितः ॥ ३४ ॥",
             "चलत्वं कफजव्याधिविच्छेदाद्वायुवद्भवेत् ।", "षण्मासमभ्यसेद्योगी२ तद्गतेनान्तरात्मना ॥ ३५ ॥", "पश्यते वायुतत्त्वेशानशुद्धानखिलानपि ।"]
    out = classify("Text", verse)
    assert [x["type"] for x in out] == ["verse"] * 5
    assert [x.get("verse") for x in out] == ["34", "34", "35", "35", None]  # last line continues on the next page
    prose = ["यहाँ से वायवी धारणा का वर्णन किया जा रहा है । वायवी धारणा भी", "योगियों की महत्त्वपूर्ण धारणा है ।",
             "होते थे । आजकल इसका प्रचार नहीं के बराबर है । शास्त्र", "तक इस धारणा की धृति से साधक ॥ ३५-३६ ॥"]
    assert classify("Text", prose)[0] == {"type": "commentary", "explains": "35-36"}
    assert classify("PageHeader", ["१९७"]) == [{"type": "header"}]
    assert classify("Footnote", ["१. क० पु० पाठः"]) == [{"type": "footnote"}]
    assert classify("Text", ["१. श्रीत० ८।३४४"]) == [{"type": "footnote"}]
    assert classify("Text", ["मा० वि०—३"]) == [{"type": "signature"}]
    # Hindi lines that happen to end in daṇḍas are still commentary.
    hindi = ["इस प्रक्रिया में सिद्ध हो जाने पर उपलब्धि हो जाती है ।", "साधक इसी क्रम में प्राप्त कर लेता है ।",
             "का ध्यान करने पर तेज की पराकाष्ठा को प्राप्त कर लेता है ॥ ४१-४२ ॥"]
    assert {x["type"] for x in classify("Text", hindi)} == {"commentary"}


def test_patterns_mining_and_matching():
    from amocr.patterns import _matches, fragment, word_pairs

    base = "जो रङ्ग भाता है, वह भी योगमागियों के लिये ।"
    fixed = "जो रङ्ग आता है, वह भी योगमार्गियों के लिये ।"
    assert word_pairs(base, fixed) == [("भाता", "आता"), ("योगमागियों", "योगमार्गियों")]
    assert fragment("अग्निमन्त्रेश्वरस्व", "अग्निमन्त्रेश्वरत्व") == ("रस्", "रत्")
    assert fragment("भाता", "आता") == ("भात", "आत")  # would also hit भात (rice): fragment rules start off
    word = {"kind": "word", "from": "भाता", "to": "आता"}
    assert [m[:2] for m in _matches(word, "भाता है। अभाता भाता।")] == [(0, 4), (15, 19)]  # whole words only, not अभाता
    frag = {"kind": "fragment", "from": "रस्व", "to": "रत्व"}
    assert [m[2] for m in _matches(frag, "मन्त्रेश्वरस्व की")] == ["रत्व"]
    rx = {"kind": "regex", "from": r"(\S+)स्व\b", "to": r"\1त्व"}
    assert list(_matches(rx, "महेश्वरस्व"))[0][2] == "महेश्वरत्व"


def test_chat_round_trip(tmp_path, monkeypatch):
    import json

    import pytest

    from amocr import chat
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-chat", title="t", languages=["san"], sha256="x")
    ocr = w.page_dir(7) / "ocr"
    ocr.mkdir(parents=True)
    rec = {"text": "शीर्षक\n\nजो रङ्ग भाता है ।\nदूसरी पंक्ति ।\n",
           "lines": [{"text": "शीर्षक", "bbox": [0, 0, 10, 10]}, {"text": "जो रङ्ग भाता है ।", "bbox": [0, 20, 10, 30]},
                     {"text": "दूसरी पंक्ति ।", "bbox": [0, 40, 10, 50]}]}
    (ocr / "surya-2.5-0.24.0.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    q = chat.post(w, "user", "line 2 looks wrong", page=7, n=2)
    assert [m["id"] for m in chat.pending(w)] == [q["id"]]
    assert chat.line_context(w, 7, 2)["text"] == "जो रङ्ग भाता है ।"  # n counts lines of text, not blank lines
    act = chat.check_action(w, {"type": "line", "page": "7", "n": "2", "to": "जो रङ्ग आता है ।"})
    assert act["from"] == "जो रङ्ग भाता है ।"
    with pytest.raises(ValueError):
        chat.check_action(w, {"type": "rule", "id": "nope"})
    r = chat.post(w, "claude", "It reads आता.", reply_to=q["id"], actions=[act])
    assert chat.pending(w) == []
    assert chat.apply(w, r["id"], 0) == {"page": 7, "n": 2}
    assert (w.gt_dir / "p0007.txt").read_text(encoding="utf-8").split("\n")[2] == "जो रङ्ग आता है ।"
    meta = json.loads((w.gt_dir / "p0007.meta.json").read_text(encoding="utf-8"))
    assert meta["verified"] is False and meta["chat_fixes_applied"] == 1
    assert f"{r['id']}:0" in chat.applied(w)
    with pytest.raises(ValueError):
        chat.apply(w, r["id"], 0)  # only once
    # A fix proposed against text that has since changed is refused.
    stale = chat.post(w, "claude", "x", reply_to=q["id"], actions=[{"type": "line", "page": 7, "n": 3, "from": "old", "to": "new"}])
    with pytest.raises(ValueError):
        chat.apply(w, stale["id"], 0)
    assert not chat.listening(w)
    chat.heartbeat(w)
    assert chat.listening(w)


def test_draft_starts_from_claude_then_surya(tmp_path, monkeypatch):
    import json

    from amocr import patterns as pat
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-d", title="t", languages=["san"], sha256="x")
    ocr = w.page_dir(3) / "ocr"
    ocr.mkdir(parents=True)

    def put(name, text):
        (ocr / f"{name}.json").write_text(json.dumps({"text": text, "lines": [{"text": text.strip(), "bbox": [0, 0, 9, 9]}]},
                                                     ensure_ascii=False), encoding="utf-8")

    put("tesseract-san+hin-psm3-5.5.4", "t\n")
    assert pat.draft(w, 3)["source"].startswith("tesseract")
    put("surya-2.5-0.24.0", "s\n")
    assert pat.draft(w, 3)["text"] == "s\n"
    put("claude-code-review-claude-opus-5-5", "c\n")
    assert pat.draft(w, 3)["text"] == "c\n"  # what Proofread starts from
    assert pat.base_result(w, 3)[0].startswith("surya")  # mining still compares against the engine


def test_chat_check_range(tmp_path, monkeypatch):
    import json

    import pytest
    from PIL import Image

    from amocr import chat
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-rng", title="t", languages=["san"], sha256="x")
    ocr = w.page_dir(2) / "ocr"
    ocr.mkdir(parents=True)
    Image.new("L", (400, 300), 255).save(w.page_dir(2) / "image.png")
    lines = [{"text": f"पंक्ति {i}", "bbox": [10, 10 + 40 * i, 300, 40 + 40 * i]} for i in range(5)]
    (ocr / "surya-2.5-0.24.0.json").write_text(json.dumps({"text": "\n".join(x["text"] for x in lines) + "\n", "lines": lines},
                                                          ensure_ascii=False), encoding="utf-8")
    m = chat.post(w, "user", "Check lines 2–4", page=2, n=2, n2=4, kind="check")
    assert m["kind"] == "check" and m["n2"] == 4
    ctx = chat.range_context(w, 2, 2, 4)
    assert [x["n"] for x in ctx["lines"]] == [2, 3, 4] and ctx["image"].endswith("p0002-l02-04.png")
    assert Image.open(ctx["image"]).size == (310, 130)  # the three lines' boxes, plus a margin
    assert "n2" not in chat.post(w, "user", "one line", page=2, n=3, n2=3)
    with pytest.raises(ValueError):
        chat.post(w, "user", "backwards", page=2, n=4, n2=2)


def test_suspects_signals():
    from collections import Counter

    from amocr.suspects import CharModel, lookalikes, syllables

    assert syllables("स्वदेहं चिन्तयेत्कृष्णं वृत्तं १षट्बिन्दुलाञ्छितम् ।") == 16
    assert syllables("चलं सचूचूशब्दं च वायवीं धारणां श्रितः ॥ ३४ ॥") == 16
    rules = [["ो", "ी", "shape"], ["^भा", "आ", "shape"], ["+र्", "", "reph"]]
    got = {v for v, _ in lookalikes("देवो", rules)}
    assert "देवी" in got
    assert ("आता", "shape") in lookalikes("भाता", rules)
    assert "अमरार्चित" in {v for v, _ in lookalikes("अमराचित", rules)}
    assert lookalikes("देवो", []) == []  # nothing is built in: a book without a profile gets no look-alikes
    lm = CharModel(Counter({"मालिनी": 50, "देवी": 40, "उसी": 30, "विजय": 20}))
    assert lm.score("मालिनीविजय") > lm.score("मालिनोविजय")


def test_context_fixes_only_in_context(tmp_path, monkeypatch):
    import json
    import re

    from amocr import suspects as sus
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-ctx", title="t", languages=["hin"], sha256="x", extra={"profile": {"lookalikes": [["ो", "ी", "shape"]]}})
    text = ("उस की तरह है । " * 30 + "राम को दिया । " * 30 + "उस को तरह है । " * 2 + "\n")
    ocr = w.page_dir(1) / "ocr"
    ocr.mkdir(parents=True)
    (ocr / "surya-2.5-0.24.0.json").write_text(json.dumps({"text": text, "lines": [{"text": text.strip(), "bbox": [0, 0, 9, 9]}]},
                                                          ensure_ascii=False), encoding="utf-8")
    fixes = sus.context_fixes(w)
    assert [(f["from"], f["next"], f["to"]) for f in fixes] == [("को", "तरह", "की")]
    rx = re.compile(sus.context_regex(fixes[0]))
    assert rx.search("उस को तरह है") and not rx.search("राम को दिया")  # को stays को where it belongs


def test_material_setting(tmp_path, monkeypatch):
    import pytest

    from amocr import book, config

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    config.path().write_text('operator = "x"\nproton_root = "/shared-with-me/L"\nmirror = "/shared-with-me/M"\n', encoding="utf-8")
    assert config.load().material == "/shared-with-me/M"  # the old name still works
    config.save(config.Config(proton_root="/shared-with-me/L"))
    with pytest.raises(SystemExit, match="material folder not set"):
        book._mirror("/shared-with-me/L/T/B.pdf", config.load())  # never write into the library by default


def test_library_merge():
    from amocr.library import merge

    a = {"path": "T/a.pdf", "name": "a.pdf", "folder": "T", "size": 10, "modified": "", "sha1": "x", "added_by": None}
    b = {"path": "T/b.pdf", "name": "b.pdf", "folder": "T", "size": 20, "modified": "", "sha1": "y", "added_by": None}
    e1, c1 = merge([], [a, b], "t1")
    assert c1["added"] == ["T/a.pdf", "T/b.pdf"] and all(e["state"] == "new" for e in e1)
    moved = a | {"path": "S/a.pdf", "folder": "S"}
    e2, c2 = merge(e1, [moved], "t2")
    assert c2["moved"] == ["T/a.pdf -> S/a.pdf"] and c2["gone"] == ["T/b.pdf"]
    assert next(e for e in e2 if e["path"] == "S/a.pdf")["moved_from"] == ["T/a.pdf"]
    e3, c3 = merge(e2, [moved | {"sha1": "z"}], "t3")
    assert c3["changed"] == ["S/a.pdf"] and any(e["state"] == "gone" for e in e3)  # gone entries are kept


def test_library_page_marks_books_on_this_machine(tmp_path, monkeypatch):
    import json

    from amocr import library, server
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    entries, _ = library.merge([], [
        {"path": "T/a.pdf", "name": "a.pdf", "folder": "T", "size": 1, "modified": "", "sha1": "x", "added_by": None},
        {"path": "T/b.pdf", "name": "b.pdf", "folder": "T", "size": 2, "modified": "", "sha1": "y", "added_by": None},
    ], "t1")
    library.save({"root": "/shared-with-me/L/", "refreshed_at": "2026-11-25T00:00:00+00:00", "count": 2, "entries": entries})
    w = Work(id="B-1", title="A", languages=["san"], sha256="0", remote="/shared-with-me/L/T/a.pdf")
    out = server._library({"B-1": w})
    assert out["count"] == 2 and not out["refresh"]["running"]
    assert {e["path"]: e.get("book") for e in out["entries"]} == {"T/a.pdf": "B-1", "T/b.pdf": None}
    json.dumps(out)  # the page gets it as JSON


def test_library_names_with_slashes_and_unreadable_folders():
    from amocr.library import _seg, merge, split_path
    from amocr.proton import ProtonError

    assert _seg("Durga/ Shakta") == "Durga\\/ Shakta"
    assert split_path("Texts/Durga\\/ Shakta/b.pdf") == ["Texts", "Durga/ Shakta", "b.pdf"]

    a = {"path": "T/X/a.pdf", "name": "a.pdf", "folder": "T", "size": 1, "modified": "", "sha1": "x", "added_by": None}
    e1, _ = merge([], [a], "t1")
    e2, c2 = merge(e1, [], "t2", unread=["T/X"])  # T/X couldn't be listed this time
    assert c2["gone"] == [] and e2[0]["path"] == "T/X/a.pdf" and e2[0]["state"] != "gone"
    assert issubclass(ProtonError, Exception)


def test_inventory_facts(tmp_path):
    import pymupdf

    from amocr import inventory

    pdf = tmp_path / "t.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page().insert_text((72, 72), "The study of the Tantra and the history of its schools is old. " * 3)
    doc.save(pdf)
    f = inventory.summarize(pdf)
    assert f["verdict"] == "text" and f["kinds"] == {"latin": 3} and f["pages"] == 3

    blank = tmp_path / "b.pdf"
    d2 = pymupdf.open()
    d2.new_page()
    d2.save(blank)
    assert inventory.summarize(blank)["verdict"] == "ocr"

    stub = tmp_path / "s.pdf"
    stub.write_bytes(b"bplist00\x00\x01")
    assert inventory.summarize(stub)["why"].startswith("a macOS placeholder")
    html = tmp_path / "h.pdf"
    html.write_text("<!DOCTYPE html><html><body>blocked</body></html>")
    assert inventory.summarize(html)["verdict"] == "notpdf"
    assert inventory.page_kind("dk;Z djrs gS vkSj ;g ,d iqLrd gS " * 5) == "suspect"  # legacy-font Hindi


def test_inventory_judges_text_layers():
    from amocr import inventory as inv

    real = inv.screen(["स्वदेहं चिन्तयेत्कृष्णं ध्यायेद्देवीं परां शिवाम् । " * 20])
    junk = inv.screen(["भथतानलर्िखाीं स " * 30])
    assert real["deva_broken"] == 0 and not inv.garbled(real)
    assert inv.garbled(junk)
    assert not inv.garbled(inv.screen(["bhagavān śivaḥ kṛṣṇaṁ ēkaṁ vadati " * 40]))  # IAST and ISO 15919
    assert inv.garbled(inv.screen(["bhagavËn ÝivaÆ kÎÌÆa vadati µ " * 40]))  # legacy-font leftovers

    same = inv.compare("śivaḥ paramaḥ sūkṣmaḥ " * 10, "sūkṣmaḥ śivaḥ paramaḥ " * 10)
    assert same["precision"] == 1.0 and inv.grade(same) == "good"  # order doesn't matter
    lost = inv.compare("sivah paramah suksmah " * 10, "śivaḥ paramaḥ sūkṣmaḥ " * 10)
    assert inv.grade(lost) == "poor"  # diacritics lost

    base = {"verdict": "text", "layer": "ocr"}
    assert inv.effective(base) == "layer-unchecked"
    assert inv.effective(base | {"quality": {"grade": "poor"}}) == "layer-poor"
    assert inv.effective(base | {"quality": {"grade": "good"}}) == "text"
    assert inv.effective({"verdict": "text", "layer": "digital", "screen": junk}) == "garbled"


def test_assemble_units(tmp_path, monkeypatch):
    """Two streams: verses close at their number, commentary at the number it explains, across pages;
    footnotes per page; the chapter from the running header; a colophon ends the chapter."""
    import json

    from amocr import assemble
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-test000001", title="t", languages=["san", "hin"], sha256="0" * 64)
    w.workdir.mkdir(parents=True)
    (w.workdir / "inventory.jsonl").write_text('{"page": 1}\n' * 4)
    pages = {   # invented lines in the edition's shape (no book text in the repo)
        1: ["विषयक्रमः", "भूमिका और अनुक्रमणिका यहाँ है ।"],
        2: ["अथ त्रयोदशोऽधिकारः", "१९७",
            "रामः वनं गच्छति सीता अपि गच्छति ।", "लक्ष्मणः अनुगच्छति भरतः तिष्ठति ॥ ३४ ॥",
            "नदी वहति पर्वतः तिष्ठति सदा ।", "वृक्षः फलति२ पक्षी उड्डयते नभः ॥ ३५ ॥",
            "यहाँ से वन यात्रा का वर्णन किया जा रहा है । यह कथा-", "मानी जाती है ॥ ३४ ॥",
            "इस श्लोक में नदी और पर्वत की तुलना की गयी है और यह बताया",
            "१. क० पु० वहतीति पाठः ;"],
        3: ["१९८", "श्रीपरीक्षातन्त्रम्",
            "चन्द्रः प्रकाशते रात्रौ सूर्यः दिवा ॥ ३६ ॥",
            "है । पाठक इसे सरलता से समझ जाता है ॥ ३५-३६३ ॥",
            "इति श्रीपरीक्षातन्त्रे त्रयोदशोऽधिकारः ॥ १३ ॥",
            "परीक्षा नामक तेरहवाँ अधिकार परिपूर्ण ॥ १३ ॥"],
        4: ["अनुक्रमणिका", "रामः वनं ३०२"],
    }
    w.gt_dir.mkdir()
    for p, lines in pages.items():
        (w.gt_dir / f"p{p:04d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (w.gt_dir / "p0003.meta.json").write_text(json.dumps({"verified": True}))

    r = assemble.assemble(w, commentary_layer="hindi-mishra")
    units = {u["id"]: u for u in map(json.loads, open(f"{r['path']}/units.jsonl", encoding="utf-8"))}
    assert r["new"] and r["chapters"] == {"13": 2} and r["front_pages"] == [1] and r["skipped_after_colophon"] == [4]
    assert list(units) == [
        "B-test000001/13/34/mula", "B-test000001/13/35/mula", "B-test000001/13/34/hindi-mishra",
        "B-test000001/13/p2/footnote-1", "B-test000001/13/36/mula", "B-test000001/13/35-36/hindi-mishra",
        "B-test000001/13/colophon/mula", "B-test000001/13/colophon/hindi-mishra"]
    v = units["B-test000001/13/34/mula"]
    assert v["iast"].startswith("rāmaḥ vanaṃ gacchati") and v["lines"] == [{"page": 2, "n": 3}, {"page": 2, "n": 4}]
    c = units["B-test000001/13/34/hindi-mishra"]
    assert "कथामानी" in c["text"] and c["explains"] == ["B-test000001/13/34/mula"]    # hyphen rejoined
    c = units["B-test000001/13/35-36/hindi-mishra"]   # runs on across the page; footnote marker 3 dropped
    assert c["pages"] == [2, 3] and c["explains"][-1] == "B-test000001/13/36/mula" and c["status"] == "draft"
    assert units["B-test000001/13/36/mula"]["status"] == "proofread"     # saved as verified before the ladder
    assert r["numbering"]["13"] == {"last": 36, "missing": list(range(1, 34)), "twice": []}  # sample starts at 34
    assert assemble.assemble(w)["new"] is False        # unchanged text: no new build
    assert assemble.chapter_of("अथ एकविशतितमोऽधिकारः") == 21 and assemble.chapter_of("सप्तमोऽधिकारः") == 7
    assert assemble.chapter_of("प्रथमोऽधिकारःपृष्ठाङ्काः१.") is None      # a contents line isn't a heading


def test_merge_duplicate_books(tmp_path, monkeypatch):
    """Same PDF under two ids: copy what's missing, never overwrite, block on differing ground truth,
    trash the duplicate, and keep its id as an alias."""
    import json

    import pytest

    from amocr import dedupe
    from amocr.catalog import Work, load_works, resolve

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    sha = "a" * 64
    keep = Work(id="B-aaaaaaaaaa", title="t", languages=["san"], sha256=sha)
    dup = Work(id="B-old0000001", title="t", languages=["san"], sha256=sha)
    for w in (keep, dup):
        w.save()

    def put(w, rel, text):
        f = w.workdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    put(keep, "pages/0001/ocr/surya.json", json.dumps({"text": "क", "work": keep.id}))
    put(dup, "pages/0001/ocr/surya.json", json.dumps({"text": "क", "work": dup.id}))   # same reading
    put(dup, "pages/0001/ocr/tess.json", json.dumps({"text": "ख"}))                     # missing in keep
    put(dup, "groundtruth/p0001.txt", "मेरा पाठ\n")                                      # a person's work
    put(keep, "groundtruth/p0001.txt", "दूसरा पाठ\n")
    assert [[w.id for w in g] for g in dedupe.duplicates()] == [["B-aaaaaaaaaa", "B-old0000001"]]

    r = dedupe.merge(dup, keep)                                   # ground truth differs: nothing happens
    assert r["conflicts"] == ["groundtruth/p0001.txt"] and not r["done"] and dup.workdir.exists()

    (dup.workdir / "groundtruth/p0001.txt").unlink()
    r = dedupe.merge(dup, keep)
    assert r["done"] and r["copy"] == ["pages/0001/ocr/tess.json"] and r["same"] == 1
    assert (keep.workdir / "pages/0001/ocr/tess.json").exists() and not dup.workdir.exists()
    assert (tmp_path / r["trash"]).exists() if not r["trash"].startswith("/") else True
    works = load_works()
    assert "B-old0000001" not in works and resolve(works, "B-old0000001") == "B-aaaaaaaaaa"
    assert (keep.workdir / "groundtruth/p0001.txt").read_text(encoding="utf-8") == "दूसरा पाठ\n"
    with pytest.raises(SystemExit):
        dedupe.merge(Work(id="B-x", title="t", languages=["san"], sha256="b" * 64), keep)   # different PDFs


def test_page_structure_for_proofreading(tmp_path, monkeypatch):
    """The proofreader sees each line's type and number, and warnings for a number the assembler can't use."""
    from amocr import assemble
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-test000002", title="t", languages=["san", "hin"], sha256="0" * 64)
    text = "\n".join(["अथ त्रयोदशोऽधिकारः", "१९७",
                      "रामः वनं गच्छति सीता अपि गच्छति ।", "लक्ष्मणः अनुगच्छति भरतः तिष्ठति ॥ ३४ ॥",
                      "नदी वहति पर्वतः तिष्ठति सदा ।", "वृक्षः फलति पक्षी उड्डयते नभः ॥ ३५ ।",
                      "चन्द्रः प्रकाशते रात्रौ सूर्यः दिवा ।", "तारा दृश्यते आकाशे सदा ॥ ३६ ॥",
                      "यहाँ से वन यात्रा का वर्णन किया जा रहा है ॥ ३४ ॥", "१. क० पु० वहतीति पाठः ;"])
    r = assemble.page_structure(w, 5, text)
    assert r["chapter"] == 13 and r["printed_page"] == "197" and r["verses"] == ["34", "36"]
    assert [t["type"] for t in r["lines"]][:4] == ["header", "header", "verse", "verse"]
    assert r["lines"][3]["verse"] == "34" and r["lines"][8]["explains"] == "34" and r["lines"][9]["note"] == "1"
    assert r["warnings"][0] == {"line": 6, "text": "verse number not between ॥ … ॥: «॥ ३५ ।»"}
    assert any(w_["line"] == 8 and "after verse 34" in w_["text"] for w_ in r["warnings"])


def test_viewer_has_no_book_specific_code():
    """Proofread is one standard view (CLAUDE.md): no branch, style or text tied to a particular book."""
    import re
    from importlib.resources import files

    for name in ("viewer.html", "theme.css", "library.html", "librarian.html"):
        src = files("amocr").joinpath(name).read_text(encoding="utf-8")
        assert not re.search(r"\b(B-[0-9a-f]{10}|SL-\d{4})\b", src), f"{name} mentions a specific book"


def test_reference_cross_check(tmp_path, monkeypatch):
    """A reference e-text flags verse lines that differ in reading, not in spelling (spaces, nasals)."""
    from amocr import assemble, reference
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-test000003", title="t", languages=["san", "hin"], sha256="0" * 64)
    w.workdir.mkdir(parents=True)
    src = tmp_path / "ref.txt"     # invented verses in GRETIL's plain-text shape
    src.write_text("13.1ab: rāmo vanaṃ gacchati sītā api gacchati 13.1cd: nadī vahati parvataḥ tiṣṭhati sadā\n", encoding="utf-8")
    m = reference.add(w, src, "TEST")
    assert m["segments"] == 2 and m["chapters"] == [13]
    text = "अथ त्रयोदशोऽधिकारः\nरामो वनं गच्छति सीता अपि गच्छति ।\nनदो वहति पर्वतः तिष्ठति सदा ॥ १ ॥"
    st = assemble.page_structure(w, 5, text)
    assert st["reference"] == "TEST" and st["lines"][1]["ref"] == "13.1ab" and st["lines"][2]["ref"] == "13.1cd"
    ref_w = [x for x in st["warnings"] if x.get("kind") == "reference"]
    assert len(ref_w) == 1 and ref_w[0]["line"] == 3
    assert ref_w[0]["diffs"] == [{"ours": "नदो", "ref": "नदी"}]          # the words, in Devanagari
    assert reference.deva("muhūrtād akhedataḥ") == "मुहूर्ताद् अखेदतः"
    assert reference.strip_markers("योगी२ तद्गते १षट्बिन्दु क० पु०") == "योगी तद्गते षट्बिन्दु क० पु०"
    assert reference.norm("vanaṃ gacchati") == reference.norm("vanam gacchati") == reference.norm("vanaṅgacchati")


def test_status_ladder():
    """Draft → proofread → validated by a second person; problem needs a note; old pages read sensibly."""
    import pytest

    from amocr import ladder

    assert ladder.of(None) == "none" and ladder.of({"verified": True}) == "proofread" and ladder.of({"verified": False}) == "draft"
    m = ladder.change(None, "draft", "anna", now="t1")
    assert m["status"] == "draft" and m["verified"] is False
    with pytest.raises(ValueError, match="only a proofread page"):
        ladder.change(m, "validated", "bala")
    m = ladder.change(m, "proofread", "anna", now="t2")
    assert m["proofread_by"] == "anna" and m["verified"] is True
    with pytest.raises(ValueError, match="second person"):
        ladder.change(m, "validated", "anna")
    assert ladder.can_validate(m, "anna")[0] is False and ladder.can_validate(m, "bala") == (True, "")
    v = ladder.change(m, "validated", "bala", now="t3")
    assert v["status"] == "validated" and v["validated_by"] == "bala" and v["proofread_by"] == "anna"
    assert [h["status"] for h in v["history"]] == ["draft", "proofread", "validated"]
    back = ladder.change(v, "proofread", "chandra", now="t4")         # text changed: validate again
    assert "validated_by" not in back and back["proofread_by"] == "chandra"
    with pytest.raises(ValueError, match="note"):
        ladder.change(None, "problem", "anna")
    assert ladder.change(None, "problem", "anna", note="verse 36 torn")["status"] == "problem"
    old = {"reviewer": "anna", "verified": True}                       # saved before the ladder
    with pytest.raises(ValueError, match="second person"):
        ladder.change(old, "validated", "anna")
    assert ladder.change(old, "validated", "bala")["proofread_by"] == "anna"


def test_page_grid(tmp_path, monkeypatch):
    """Every page with its status; groups from the latest build; warnings only on the text's own pages."""
    import json

    from amocr import grid
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-test000004", title="t", languages=["san", "hin"], sha256="0" * 64)
    w.workdir.mkdir(parents=True)
    (w.workdir / "inventory.jsonl").write_text('{"page": 1}\n' * 6)
    w.gt_dir.mkdir()
    for p, meta in ((2, {"status": "proofread", "proofread_by": "anna"}), (3, {"verified": False}), (6, {"status": "blank"})):
        (w.gt_dir / f"p{p:04d}.txt").write_text("अथ त्रयोदशोऽधिकारः\n" if p == 2 else "x\n", encoding="utf-8")
        (w.gt_dir / f"p{p:04d}.meta.json").write_text(json.dumps(meta))
    b = w.workdir / "units" / "v001"
    b.mkdir(parents=True)
    (b / "units.jsonl").write_text("")
    (b / "build.json").write_text(json.dumps({"chapters": {"13": 2}, "skipped_after_colophon": [5, 6]}))
    g = grid.pages(w)
    assert [r["status"] for r in g["pages"]] == ["none", "proofread", "draft", "none", "none", "blank"]
    assert g["groups"] == [{"name": "Before chapter 1", "from": 1, "to": 1}, {"name": "Chapter 13", "from": 2, "to": 4},
                           {"name": "After the text", "from": 5, "to": 6}]
    assert g["done"] == 1 and g["counts"]["proofread"] == 1 and g["pages"][1]["proofread_by"] == "anna"
    ws = grid.warnings(w)
    assert set(ws) == {2, 3, 4} and ws[4] == {"structure": 0, "reference": 0}    # chapter pages only


def test_save_history(tmp_path, monkeypatch):
    """Every save is kept; a page's text from before history is kept first; the base reading is found."""
    import json

    from amocr import history, ladder
    from amocr.catalog import Work

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = Work(id="B-test000005", title="t", languages=["san"], sha256="0" * 64)
    ocr = w.page_dir(3) / "ocr"
    ocr.mkdir(parents=True)
    (ocr / "surya-2.5-0.24.0.json").write_text(json.dumps({"text": "रामो वनं\n"}), encoding="utf-8")
    w.gt_dir.mkdir(parents=True)
    (w.gt_dir / "p0003.txt").write_text("रामः वनं\n", encoding="utf-8")                  # saved before history
    (w.gt_dir / "p0003.meta.json").write_text(json.dumps({"reviewer": "anna", "verified": False, "saved": "t0"}))
    meta = ladder.change(json.loads((w.gt_dir / "p0003.meta.json").read_text()), "proofread", "anna", now="t1")
    assert history.record(w, 3, "रामः वनं गच्छति\n", meta, "save") == 1
    vs = history.load(w, 3)
    assert [(v["v"], v["how"], v["text"]) for v in vs] == [(0, "before history", "रामः वनं\n"), (1, "save", "रामः वनं गच्छति\n")]
    assert vs[1]["status"] == "proofread" and vs[1]["by"] == "anna"
    assert history.base_text(w, 3) == ("surya-2.5-0.24.0", "रामो वनं\n")


def test_chat_fix_quotes_are_not_text():
    """A --fix written as '231:7:"…"' must not put the quotes into the proposed line."""
    from amocr.chat import _unquote

    assert _unquote('"योजनानां शतं गत्वा ।"') == "योजनानां शतं गत्वा ।"
    assert _unquote("“योजनानां ।”") == "योजनानां ।"
    assert _unquote("'मातृचक्र' का अर्थ") == "'मातृचक्र' का अर्थ"     # quotes inside a printed line stay


def test_etext_parse_patterns():
    """GRETIL's ways of marking structure: ids, pāda references, verse numbers, vṛtti, sūtra refs, prose."""
    import pytest

    pytest.importorskip("lancedb")
    from librarian.etext import parse
    from librarian.index import fold

    xml = """<TEI><text><body>
    <lg xml:id="AbhT_1.1"><l>vimalakalāśrayābhinava /</l><l>sṛṣṭimahā jananī //</l></lg>
    <p>2.1ab: athaiṣām eva tattvānāṃ 2.1cd: prapañcaḥ kathyate leśāt</p>
    <lg><l>jāgradādi vibhede 'pi</l><l>nivartate nijān naiva || 3 ||</l></lg>
    <p>Ipv: kevalam asya svasaṃvedanasiddhasya</p>
    <l>jñānaṃ bandhaḥ // SivS_1.2 //</l>
    <p>* [&lt;śivasūtravārtika:&gt; / * ajñānam iti tatrādyaṃ || SivSV_1.2:1 ||</p>
    <p>iha jñānaṃ mokṣakāraṇaṃ bandhanimittasya ajñānasya</p>
    </body></text></TEI>"""
    rows = parse(xml)
    got = [(r["chapter"], r["verse"], r["layer"]) for r in rows]
    assert got == [("1", "1", "mula"), ("2", "1", "mula"), ("2", "3", "mula"), ("2", "3", "vrtti"),
                   ("1", "2", "mula"), ("1", "2:1", "varttika"), ("1", "p1", "mula")]
    assert rows[1]["iast"] == "athaiṣām eva tattvānāṃ / prapañcaḥ kathyate leśāt"
    assert rows[5]["explains"] == "2" and rows[4]["iast"] == "jñānaṃ bandhaḥ"
    assert fold("Spanda-kārikā") == fold("spanda kArikA".replace("A", "a")) == "spanda karika"
    assert fold("स्पन्दः") == "spandah"


def test_study_chat(tmp_path, monkeypatch):
    """Questions carry the passage in focus; answers must cite units that exist in the library."""
    import pytest

    pytest.importorskip("lancedb")
    from librarian import etext, store, study

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    src = tmp_path / "sa_test.xml"
    src.write_text('<TEI><text><body><lg xml:id="T_1.1"><l>caitanyam ātmā</l></lg></body></text></TEI>', encoding="utf-8")
    m = etext.ingest(src)
    store.reload()
    uid = f"{m['id']}/1/1/mula"
    q = study.post("user", "What does this sūtra mean?", unit=uid, by="anna")
    assert study.pending() == [q] and q["unit"] == uid
    with pytest.raises(ValueError, match="no such unit"):
        study.post("claude", "…", reply_to=q["id"], cites=["ET-9999/1/1/mula"])
    a = study.post("claude", "Consciousness is the self.", reply_to=q["id"], cites=[uid])
    assert study.pending() == [] and a["cites"] == [uid]
    store.reload()


def test_gretil_catalogue_and_upload_checks():
    """GRETIL's catalogue page → titles and TEI paths; only GRETIL TEI paths download; uploads must be TEI."""
    import pytest

    pytest.importorskip("lancedb")
    from librarian import gretil, importer

    page = """<ul><li>Vasugupta: Spandakarika, with commentary by Ksemaraja <span>(..)</span>
      <a href="gretil/corpustei/sa_vasugupta-spandakArikA-comm.xml">TEI</a></li>
      <li><a href="gretil/corpustei/sa_vijJAnabhairava.xml">TEI-conformant XML</a></li>
      <li>No TEI here <a href="gretil/1_sanskr/x.htm">html</a></li></ul>"""
    items = gretil.parse(page)
    assert items == [{"title": "Vasugupta: Spandakarika, with commentary by Ksemaraja", "path": "gretil/corpustei/sa_vasugupta-spandakArikA-comm.xml"},
                     {"title": "Vijñānabhairava", "path": "gretil/corpustei/sa_vijJAnabhairava.xml"}]
    with pytest.raises(ValueError, match="only GRETIL TEI"):
        gretil.download("https://example.org/evil.xml")
    with pytest.raises(ValueError, match="TEI XML"):
        importer.from_upload("notes.txt", "just some text")


def test_hosted_members_only(tmp_path, monkeypatch):
    """Hosted mode: an invite sets the password; sign in with name and password (a session cookie);
    wrong passwords refused and locked out after five; pages without a session go to the login page;
    sign out ends the session; a listener token works as Bearer; only hashes are stored."""
    import json
    import socket
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    import pytest

    from amocr import members, server

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    with pytest.raises(SystemExit, match="without --hosted"):
        server.serve(port=1, open_browser=False, host="0.0.0.0", hosted=False)
    with pytest.raises(SystemExit, match="needs members"):
        server.serve(port=1, open_browser=False, host="0.0.0.0", hosted=True)
    code = members.add("Anna", "proofreader")
    members.add("Bala", "reader")

    server.Handler.hosted, server.Handler.works = True, {}
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    def req(path, body=None, cookie=None, token=None):
        h = {"Content-Type": "application/json"}
        if cookie:
            h["Cookie"] = cookie
        if token:
            h["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            resp = opener.open(r, timeout=10)
            return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()
    try:
        code_, hdr, _ = req("/library")
        assert code_ == 303 and hdr["Location"] == "/login?next=%2Flibrary"
        assert req("/api/works")[0] == 401 and req("/login")[0] == 200 and req("/theme.css")[0] == 200
        assert req("/api/auth/invite", {"code": code, "password": "short"})[0] == 400          # too short
        st, hdr, _ = req("/api/auth/invite", {"code": code, "password": "a long passphrase"})
        assert st == 200 and "am_session=" in hdr["Set-Cookie"] and "HttpOnly" in hdr["Set-Cookie"]
        assert req("/api/auth/invite", {"code": code, "password": "another passphrase"})[0] == 400   # used up
        assert req("/api/auth/login", {"name": "Anna", "password": "wrong password!"})[0] == 401
        st, hdr, _ = req("/api/auth/login", {"name": "Anna", "password": "a long passphrase"})
        cookie = hdr["Set-Cookie"].split(";")[0]
        assert st == 200 and req("/api/works", cookie=cookie)[0] == 200
        assert json.loads(req("/api/me", cookie=cookie)[2]) == {"hosted": True, "name": "Anna", "role": "proofreader"}
        tok = json.loads(req("/api/auth/token", {}, cookie=cookie)[2])["token"]
        assert req("/api/works", token=tok)[0] == 200 and req("/api/works", token="am_wrong")[0] == 401
        assert req("/api/auth/logout", {}, cookie=cookie)[0] == 200 and req("/api/works", cookie=cookie)[0] == 401
        for _ in range(5):
            req("/api/auth/login", {"name": "Bala", "password": "not the password"})
        assert req("/api/auth/login", {"name": "Bala", "password": "not the password"})[0] == 429      # locked out
    finally:
        httpd.shutdown()
        server.Handler.hosted = False
    stored = (tmp_path / "hosted" / "members.json").read_text() + (tmp_path / "hosted" / "sessions.json").read_text()
    assert "a long passphrase" not in stored and tok not in stored and code not in stored and cookie.split("=")[1] not in stored

    pytest.importorskip("lancedb")
    from librarian import study
    study.post("user", "Anna's question", by="Anna")
    study.post("user", "Bala's question", by="Bala")
    assert [m["text"] for m in study.thread("Anna")] == ["Anna's question"]
    assert [m["text"] for m in study.pending("Bala")] == ["Bala's question"] and len(study.thread(None)) == 2

def test_windows_scripts_parse():
    """The Windows serve/redeploy scripts are at least valid PowerShell (checked on the Windows CI runner)."""
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    here = Path(__file__).parent.parent / "scripts" / "windows"
    for c in sorted(here.glob("*.cmd")):                # each wrapper runs its own script, with a one-off bypass
        body = c.read_text(encoding="utf-8")
        assert f'"%~dp0{c.stem}.ps1"' in body and "-ExecutionPolicy Bypass" in body and (here / f"{c.stem}.ps1").exists()
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("no PowerShell here (the Windows CI runner has it)")
    for f in sorted((Path(__file__).parent.parent / "scripts" / "windows").glob("*.ps1")):
        cmd = ("$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e) | Out-Null; "
               "if ($e) { $e | ForEach-Object { $_.ToString() }; exit 1 }" % str(f).replace("'", "''"))
        r = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True)
        assert r.returncode == 0, f"{f.name}: {r.stdout}{r.stderr}"


def test_home_is_the_library():
    """/ opens the Library; old /#book/page links still reach the viewer, now at /proofread."""
    from amocr import server

    assert b"location.hash ? '/proofread' + location.hash : '/library'" in server.HOME
    from importlib.resources import files
    for name in ("library.html", "viewer.html", "librarian.html"):
        src = files("amocr").joinpath(name).read_text(encoding="utf-8")
        assert 'href="/"' not in src and 'href="/#' not in src and '<a href="/proofread' in src


def test_hosted_config_file(tmp_path, monkeypatch):
    """The private file supplies server and token only with --hosted; the env and flags win; own address caught."""
    import pytest

    pytest.importorskip("lancedb")
    from librarian import remote

    monkeypatch.delenv("AGAMA_SERVER", raising=False)
    monkeypatch.delenv("AGAMA_TOKEN", raising=False)
    cfg = tmp_path / "hosted.env"
    cfg.write_text('AGAMA_SERVER=http://10.0.0.5:8770/\nAGAMA_TOKEN="am_secret"\n# comment\nOTHER=x\n', encoding="utf-8")
    monkeypatch.setattr(remote, "CONFIG", cfg)
    assert remote.server() is None                                  # local by default
    assert remote.server(hosted=True) == "http://10.0.0.5:8770"
    assert remote._token() == "am_secret"
    assert remote.server("http://other:1", hosted=True) == "http://other:1"
    monkeypatch.setenv("AGAMA_SERVER", "http://env:2")
    assert remote.server(hosted=True) == "http://env:2"
    assert "own address" in remote.check("http://127.0.0.1:8770")


def _queue_book(tmp_path, pages=3):
    import json

    from amocr.catalog import Work
    from PIL import Image

    w = Work(id="B-test000006", title="t", languages=["san"], sha256="0" * 64)
    w.save()
    (w.workdir / "inventory.jsonl").write_text(
        "".join(json.dumps({"page": p, "text_layer": "text" if p == 2 else "none"}) + "\n" for p in range(1, pages + 1)))
    for p in range(1, pages + 1):
        w.page_dir(p).mkdir(parents=True, exist_ok=True)
        Image.new("L", (40, 20), 255).save(w.page_dir(p) / "image.png")
    return w


def test_ocr_queue(tmp_path, monkeypatch):
    """Queue the pages that need an engine; lease to one worker; save the reading; retries, then set aside."""
    import json

    import pytest

    from amocr import ocrqueue

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = _queue_book(tmp_path)
    assert ocrqueue.add(w, "tesseract") == 2                          # p2 has a usable text layer
    assert ocrqueue.add(w, "tesseract") == 0                          # already queued
    got = ocrqueue.lease("anna", ["tesseract"], n=5, host="mac")
    assert [j["page"] for j in got] == [1, 3] and ocrqueue.lease("bala", ["tesseract"]) == []
    with pytest.raises(ValueError, match="isn't leased to you"):
        ocrqueue.complete({w.id: w}, "bala", got[0]["job"], got[0]["key"], "tesseract-san+hin-psm3-5.5.4", {"text": "x"})
    with pytest.raises(ValueError, match="wants tesseract"):
        ocrqueue.complete({w.id: w}, "anna", got[0]["job"], got[0]["key"], "surya-2.5-0.24.0", {"text": "x"})
    ocrqueue.complete({w.id: w}, "anna", got[0]["job"], got[0]["key"], "tesseract-san+hin-psm3-5.5.4", {"text": "क\n", "lines": []})
    saved = json.loads((w.page_dir(1) / "ocr" / "tesseract-san+hin-psm3-5.5.4.json").read_text(encoding="utf-8"))
    assert saved["text"] == "क\n" and saved["operator"] == "anna" and saved["worker"] == "mac"
    for _ in range(3):                                                # fails three times: set aside
        j = got[1] if _ == 0 else ocrqueue.lease("anna", ["tesseract"])[0]
        ocrqueue.release("anna", j["job"], j["key"], "boom")
    st = ocrqueue.status()["books"][f"{w.id} · tesseract"]
    assert st == {"queued": 0, "leased": 0, "done": 1, "failed": 1}


def test_ocr_worker_end_to_end(tmp_path, monkeypatch):
    """A worker leases pages over HTTP from a hosted server, reads them with its engine, returns the readings."""
    import json
    import socket
    import threading
    from http.server import ThreadingHTTPServer

    import pytest

    pytest.importorskip("lancedb")
    from amocr import members, ocrqueue, server, worker
    from amocr.catalog import load_works
    from amocr.engines.base import Engine, OcrResult

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = _queue_book(tmp_path)
    members.add("Anna", "proofreader")
    tok = members.issue_token("Anna")
    ocrqueue.add(w, "tesseract")

    class Fake(Engine):
        name, label = "tesseract", "tesseract-fake"
        def version(self): return "1.0"
        def config(self): return {}
        def run(self, image):
            assert image.read_bytes()[:4] == b"\x89PNG"             # the page image came over HTTP
            return OcrResult(text="पठितम्\n", confidence=90.0, engine="tesseract", engine_version="1.0", config={})
    monkeypatch.setattr(worker, "available", lambda wanted=None: {"tesseract": Fake()})

    server.Handler.hosted, server.Handler.works = True, load_works()
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert worker.run(f"http://127.0.0.1:{port}", tok, once=True, log=lambda *a: None) == 2
    finally:
        httpd.shutdown()
        server.Handler.hosted = False
    for p in (1, 3):
        rec = json.loads((w.page_dir(p) / "ocr" / "tesseract-fake-1.0.json").read_text(encoding="utf-8"))
        assert rec["text"] == "पठितम्\n" and rec["operator"] == "Anna" and rec["via"] == "ocr-worker"
    assert ocrqueue.status()["books"][f"{w.id} · tesseract"]["done"] == 2


def test_hosted_proofreading_chat(tmp_path, monkeypatch):
    """Per-member proofreading chat: a member's question reaches only their listener (over HTTP, with the
    line image), the reply's fix is checked on the server, and restricted books are never handed out."""
    import json
    import socket
    import threading
    from http.server import ThreadingHTTPServer

    import pytest

    pytest.importorskip("lancedb")
    from amocr import chat, members, server
    from amocr.catalog import load_works
    from librarian import remote

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = _queue_book(tmp_path)
    (w.page_dir(1) / "ocr").mkdir(parents=True, exist_ok=True)
    (w.page_dir(1) / "ocr" / "surya-2.5-0.24.0.json").write_text(json.dumps(
        {"text": "रामो वनं\n", "lines": [{"text": "रामो वनं", "bbox": [2, 2, 30, 15]}]}), encoding="utf-8")
    members.add("Anna", "proofreader"); members.add("Bala", "proofreader")
    anna, bala = members.issue_token("Anna"), members.issue_token("Bala")
    chat.post(w, "user", "Is this रामः?", page=1, n=1, by="Anna")

    server.Handler.hosted, server.Handler.works = True, load_works()
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        assert remote.call(base, "/api/chat/next", bala, query={"timeout": 1})["message"] is None    # not Bala's
        r = remote.call(base, "/api/chat/next", anna, query={"timeout": 1})
        assert r["work"] == w.id and r["message"]["text"] == "Is this रामः?" and r["context"]["text"] == "रामो वनं"
        assert remote.fetch(base, r["context"]["image_url"], anna)[:4] == b"\x89PNG"
        with pytest.raises(SystemExit, match="no such question of yours"):
            remote.call(base, f"/api/{w.id}/chat/reply", bala, body={"msg": r["message"]["id"], "text": "x"})
        rep = remote.call(base, f"/api/{w.id}/chat/reply", anna,
                          body={"msg": r["message"]["id"], "text": "Printed रामः.", "fixes": [{"page": 1, "n": 1, "to": "रामः वनं"}]})
        assert rep["actions"][0]["to"] == "रामः वनं" and rep["actions"][0]["from"] == "रामो वनं"
        assert remote.call(base, "/api/chat/next", anna, query={"timeout": 1})["message"] is None      # answered
        w.restricted = True; w.save(); server.Handler.works = load_works()
        chat.post(w, "user", "and this?", page=1, n=1, by="Anna")
        assert remote.call(base, "/api/chat/next", anna, query={"timeout": 1})["message"] is None      # restricted
    finally:
        httpd.shutdown()
        server.Handler.hosted = False


def _helper_server(tmp_path, monkeypatch):
    """A hosted test server with one book whose page 1 has a line, two members and a question from Anna."""
    import json
    import socket
    import threading
    from http.server import ThreadingHTTPServer

    from amocr import chat, members, server
    from amocr.catalog import load_works

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = _queue_book(tmp_path)
    (w.page_dir(1) / "ocr").mkdir(parents=True, exist_ok=True)
    (w.page_dir(1) / "ocr" / "surya-2.5-0.24.0.json").write_text(json.dumps(
        {"text": "rama vanam\n", "lines": [{"text": "rama vanam", "bbox": [2, 2, 30, 15]}]}), encoding="utf-8")
    members.add("Anna", "proofreader"); members.add("Bala", "proofreader")
    q = chat.post(w, "user", "Is this right?", page=1, n=1, by="Anna")
    server.Handler.hosted, server.Handler.works = True, load_works()
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return w, q, httpd, f"http://127.0.0.1:{port}"


def test_claude_helper_tasks(tmp_path, monkeypatch):
    """The helper's server side: a separate helper token, the member's own question as a complete task
    (rules, the line, its image), the answer checked and posted with its fix, the download filled in."""
    import pytest

    from amocr import chat, members, server
    from librarian import remote

    w, q, httpd, base = _helper_server(tmp_path, monkeypatch)
    try:
        listener = members.issue_token("Anna")
        helper_tok = members.issue_token("Anna", "helper")
        assert members.check(listener) == ("Anna", "proofreader") == members.check(helper_tok)   # both work
        bala = members.issue_token("Bala", "helper")
        assert remote.call(base, "/api/helper/next", bala, query={"timeout": 1})["task"] is None   # not Bala's
        t = remote.call(base, "/api/helper/next", helper_tok, query={"timeout": 1})["task"]
        assert t["kind"] == "proofread" and t["id"] == q["id"] and "page 1 line 1: rama vanam" in t["prompt"]
        assert "{IMAGE1}" in t["prompt"] and remote.fetch(base, t["images"][0], helper_tok)[:4] == b"\x89PNG"
        assert "Transcribe what is printed" in t["prompt"] and t["schema"]["required"] == ["answer", "fixes"]
        assert chat.listening(w, "Anna") and not chat.listening(w, "Chitra")      # Chitra has no helper running
        with pytest.raises(SystemExit, match="no such question of yours"):
            remote.call(base, "/api/helper/answer", bala, body={"kind": "proofread", "work": w.id, "id": q["id"], "answer": "x"})
        r = remote.call(base, "/api/helper/answer", helper_tok, body={"kind": "proofread", "work": w.id, "id": q["id"],
                        "answer": "Printed rāma vanaṃ.", "fixes": [{"page": 1, "line": 1, "to": "rama vanam."}]})
        assert r["reply_to"] == q["id"] and r["actions"][0]["to"] == "rama vanam."
        assert remote.call(base, "/api/helper/next", helper_tok, query={"timeout": 1})["task"] is None   # answered
        from amocr import helper

        f = helper.download(base, helper_tok).decode()
        assert f.startswith("@echo off\r\n") and f'$Server = "{base}"' in f and f'$Token = "{helper_tok}"' in f
        assert "__TOKEN__" not in f and "\r\n" in f and "\n" not in f.replace("\r\n", "")
    finally:
        httpd.shutdown()
        server.Handler.hosted = False


def test_claude_helper_runs_on_windows(tmp_path, monkeypatch):
    """The downloaded helper file itself, in Windows PowerShell, against a test server, with a stand-in
    `claude` that answers the way Claude Code does (-p --output-format json --json-schema)."""
    import os
    import subprocess
    import sys
    import time

    import pytest

    if sys.platform != "win32":
        pytest.skip("the helper is a Windows file")
    from amocr import chat, helper, members, server

    w, q, httpd, base = _helper_server(tmp_path, monkeypatch)
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude.cmd").write_text(
        "@echo off\r\n"
        'if "%1"=="auth" (echo {"loggedIn": true}& exit /b 0)\r\n'
        'more > "%~dp0prompt.txt"\r\n'
        'echo {"type":"result","is_error":false,"result":"","structured_output":'
        '{"answer":"Printed with a danda.","fixes":[{"page":1,"line":1,"to":"rama vanam |"}]}}\r\n', encoding="ascii")
    f = tmp_path / "Agama Mancha Claude helper.cmd"
    f.write_bytes(helper.download(base, members.issue_token("Anna", "helper")))
    env = dict(os.environ, PATH=f"{fake};{os.environ['PATH']}")
    p = subprocess.Popen(["cmd", "/c", str(f)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        end = time.time() + 90
        while time.time() < end:
            got = [m for m in chat.load(w) if m.get("reply_to") == q["id"]]
            if got:
                break
            time.sleep(1)
        else:
            p.kill()
            pytest.fail("no answer from the helper:\n" + p.communicate(timeout=10)[0].decode(errors="replace"))
        assert got[0]["text"] == "Printed with a danda." and got[0]["actions"][0]["to"] == "rama vanam |"
        prompt = (fake / "prompt.txt").read_text(encoding="utf-8", errors="replace")
        assert "rama vanam" in prompt and "image1.png" in prompt and "{IMAGE1}" not in prompt
    finally:
        p.kill()
        httpd.shutdown()
        server.Handler.hosted = False


def test_fix_with_local_ai(tmp_path, monkeypatch):
    """An instruction goes to the local AI worker only (never to Claude); its edits come back as proposals
    limited to the selected lines, labelled local AI, and apply like Claude's."""
    import json
    import socket
    import threading
    from http.server import ThreadingHTTPServer

    from amocr import chat, fixer, helper, server
    from amocr.catalog import load_works

    monkeypatch.setenv("AMOCR_DATA", str(tmp_path))
    w = _queue_book(tmp_path)
    (w.page_dir(1) / "ocr").mkdir(parents=True, exist_ok=True)
    (w.page_dir(1) / "ocr" / "surya-2.5-0.24.0.json").write_text(json.dumps(
        {"text": "षण्माससभ्यसेद्योगी१\nद्वितीया\n", "lines": [{"text": "षण्माससभ्यसेद्योगी१", "bbox": [2, 2, 30, 9]},
                                                    {"text": "द्वितीया", "bbox": [2, 10, 30, 18]}]}), encoding="utf-8")
    q = chat.post(w, "user", "षण्माससभ्यसेद् should be षण्मासमभ्यसेद्, and the marker is २", page=1, n=1, kind="fix")
    works = load_works()
    assert chat.pending(w) == [] and helper.next_task(works, None, timeout=0) is None      # Claude never gets it
    t = fixer.next_task(works, timeout=0)
    assert t["id"] == q["id"] and t["lines"] == [{"n": 1, "text": "षण्माससभ्यसेद्योगी१"}]
    assert fixer.next_task(works, timeout=0) is None                                        # claimed by that worker
    assert fixer.active()

    def fake_edit(task, model, ollama=None):
        return {"edits": [{"line": 1, "to": "षण्मासमभ्यसेद्योगी२"}, {"line": 2, "to": "not selected"}], "note": ""}
    monkeypatch.setattr(fixer, "edit", fake_edit)
    fixer._CLAIMS.clear()
    server.Handler.hosted, server.Handler.works = False, works
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert fixer.run(f"http://127.0.0.1:{port}", "local", "test-model", once=True, log=lambda *_: None) == 1
    finally:
        httpd.shutdown()
    a = [m for m in chat.load(w) if m.get("reply_to") == q["id"]][0]
    assert a["role"] == "ai" and a["model"] == "test-model" and "outside the selected lines" in a["text"]
    assert [(x["n"], x["from"], x["to"]) for x in a["actions"]] == [(1, "षण्माससभ्यसेद्योगी१", "षण्मासमभ्यसेद्योगी२")]
    assert chat.pending(w, fixes=True) == []
    chat.apply(w, a["id"], 0)
    assert chat.line_context(w, 1, 1)["text"] == "षण्मासमभ्यसेद्योगी२"
