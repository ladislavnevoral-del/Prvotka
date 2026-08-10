from app.signal_engine import analyze, detect_signals, score_signals, lead_level
from app.document_analyzer import analyze_document


REAL_OCR_SAMPLE = (
    "Zápis zjednání shromáždění Společenství vlastníků Rybářská 28, Brno, "
    "konané dne 10.10.2024 v 18:30. "
    "NÁVRH NA NAVÝŠENÍ PŘÍSPĚVKŮ DO FONDU OPRAV 28Kč/m“ 12 0 0 "
    "Bylo schváleno navýšení příspěvku do fondu oprav na účet dlouhodobých "
    "záloh - 28Kč/m* Náklady SV Rybářská 28 (Administrativa, Vodné, Stočné, "
    "Elektřina, Výtah, Úklid, Pojištění) převyšují obnos vybraný na zálohách. "
    "Přítomní byli obeznámeni s plánovaným navýšením záloh v průměru o 30%. "
    "Zvolení členové: Jan Strádal, Edita Friedlová, Zdeněk Kuna"
)


def test_revitalization_lead():
    score, hits = analyze(
        "Shromáždění schválilo revitalizaci domu, zateplení fasády, "
        "rekonstrukci balkonů a projektovou dokumentaci."
    )
    assert score >= 60
    assert any(h["type"] == "revitalizace" for h in hits)
    assert any(h["type"] == "zatepleni" for h in hits)


def test_weak_repair():
    score, hits = analyze("Byla provedena běžná oprava světla ve sklepě.")
    assert score < 35


def test_real_ocr_values():
    signals = detect_signals(REAL_OCR_SAMPLE)
    by_type = {s["type"]: s for s in signals}
    assert by_type["fond_oprav"]["value"] == "28 Kč/m²"
    assert by_type["zvyseni_zaloh"]["value"] == "30 %"
    assert "financni_situace" in by_type
    assert "volba_vyboru" in by_type
    # kontext u fondu oprav nesmí být prázdný (původní bug)
    assert by_type["fond_oprav"]["context"]


def test_ocr_without_diacritics():
    """OCR často ztratí diakritiku — detekce musí přežít."""
    text = (
        "Zapis ze shromazdeni. Bylo schvaleno zatepleni fasady a "
        "rekonstrukce balkonu. Financovani uverem a dotaci NZU."
    )
    signals = detect_signals(text)
    types = {s["type"] for s in signals}
    assert "zatepleni" in types
    assert "balkony_lodzie" in types
    assert "nzu" in types or "dotace" in types


def test_mere_mention_is_filtered():
    """Pouhá zmínka bez akčního slova nesmí být signál."""
    signals = detect_signals(
        "Vlastník jednotky č. 5 si stěžoval na hluk z balkonu souseda "
        "v pozdních večerních hodinách."
    )
    assert not any(s["type"] == "balkony_lodzie" for s in signals)


def test_scoring_combo_and_cap():
    strong = (
        "Schválena revitalizace, zateplení fasády, výběr zhotovitele, "
        "smlouva o dílo, projektová dokumentace, energetický audit, "
        "úvěr, dotace NZÚ, rekonstrukce střechy a výměna oken."
    )
    score, _ = analyze(strong)
    assert score == 100
    assert lead_level(score) == "HOT"


def test_lead_levels():
    assert lead_level(85) == "HOT"
    assert lead_level(65) == "HIGH"
    assert lead_level(40) == "WATCH"
    assert lead_level(10) == "LOW"


def test_document_analyzer_metadata():
    meta = analyze_document(REAL_OCR_SAMPLE)
    assert meta["document_type"] == "zápis ze shromáždění"
    assert meta["meeting_date_text"] == "10.10.2024"
    assert "Jan Strádal" in meta["board_members"]
    assert len(meta["board_members"]) == 3


def test_empty_text():
    assert detect_signals("") == []
    assert score_signals([]) == 0
