"""Původní testy scoring.py — zachovány pro zpětnou kompatibilitu API."""

from app.scoring import analyze

def test_revitalization_lead():
    score, hits = analyze(
        "Shromáždění schválilo revitalizaci domu, zateplení fasády, "
        "rekonstrukci balkonů a projektovou dokumentaci."
    )
    assert score >= 60
    assert any(h["type"] == "revitalizace" for h in hits)

def test_weak_repair():
    score, hits = analyze("Byla provedena běžná oprava světla.")
    assert score < 35
