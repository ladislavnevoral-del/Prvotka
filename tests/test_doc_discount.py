from app.pipeline import doc_score_divisor


def test_stanovy_discounted():
    assert doc_score_divisor("notářský zápis stanovy, NZ 480/2014", None) == 3
    assert doc_score_divisor("stanovy společnosti", None) == 3
    assert doc_score_divisor("stanovy společnosti dodatek č.1", None) == 3
    assert doc_score_divisor(None, "stanovy") == 3
    assert doc_score_divisor("ostatní prohlášení o rozděl. práva k domu", None) == 3
    assert doc_score_divisor("účetní závěrka [2018]", None) == 3


def test_notarsky_zapis_mildly_discounted():
    assert doc_score_divisor("notářský zápis rozhod. shromáždění, NZ 152/2014",
                             None) == 2


def test_zapis_not_discounted():
    assert doc_score_divisor("ostatní zápis ze schůze shromáždění SVJ",
                             "zápis ze shromáždění") == 1
    assert doc_score_divisor("zápis z členské schůze", None) == 1
    assert doc_score_divisor("ostatní zápis ze schůze výboru", None) == 1
