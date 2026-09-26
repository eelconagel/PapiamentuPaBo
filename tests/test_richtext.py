from papiamentu.richtext import rich


def test_paragraphs_and_bullets():
    html = str(rich("Intro zin.\n\nKOPJE:\n• een\n• twee\n\nSlot."))
    assert "<p>Intro zin.</p>" in html
    assert '<h3 class="rich-h">Kopje</h3>' in html
    assert "<ul><li>een</li><li>twee</li></ul>" in html
    assert html.endswith("<p>Slot.</p>")


def test_numbered_items_keep_their_number():
    html = str(rich("1. COPULA: Legt verband.\nMi ta studiant.\n2. STATUS: Toestand."))
    assert '<span class="num">1</span>' in html and '<span class="num">2</span>' in html
    assert "<strong>Copula:</strong> Legt verband." in html


def test_heading_keeps_brackets_and_proper_names():
    html = str(rich("BELANGRIJK VERSCHIL MET NEDERLANDS:\nx\n\nDEEL 1 (tabata):\ny"))
    assert "Belangrijk verschil met Nederlands" in html
    assert "Deel 1 (tabata)" in html


def test_escapes_html():
    html = str(rich("<script>alert(1)</script>\n• <b>x</b>"))
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;" in html


def test_normal_sentence_with_colon_is_not_a_heading():
    assert "rich-h" not in str(rich("Ayera (gisteren): 'Mi a bai ayera.'"))
