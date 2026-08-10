from app.listiny import (
    parse_listiny_html, parse_subjekt_id, parse_download_url, Listina,
)

# Fixture odpovídá skutečnému markupu or.justice.cz (ověřeno 8/2026).
LISTINY_HTML = """
<html><body>
<table class="result-details"><tr><th>Spisová značka:</th><td>S 10868</td></tr></table>
<table class="list">
  <thead><tr>
    <th>Číslo listiny</th><th>Typ listiny</th><th>Vznik listiny</th>
    <th>Došlo na soud</th><th>Založeno do SL</th><th colspan="2">Stránek</th>
  </tr></thead>
  <tbody>
    <tr>
      <td><a href="./vypis-sl-detail?dokument=85685221&amp;subjektId=875537&amp;spis=949328"><span>S&nbsp;10868/SL16/KSBR</span></a></td>
      <td>ostatní zápis ze schůze shromáždění SVJ</td>
      <td>10.10.2024</td><td>26.2.2025</td><td>7.4.2025</td><td>2</td><td></td>
    </tr>
    <tr>
      <td><a href="./vypis-sl-detail?dokument=60285067&amp;subjektId=875537&amp;spis=949328"><span>S&nbsp;10868/SL15/KSBR</span></a></td>
      <td>účetní závěrka [2018]</td>
      <td>10.9.2019</td><td>5.12.2019</td><td>2.1.2020</td><td>3</td><td></td>
    </tr>
  </tbody>
</table>
</body></html>
"""

REJSTRIK_HTML = """
<html><body>
<a href="./vypis-sl-firma?subjektId=875537">Sbírka listin</a>
<a href="./rejstrik-firma.vysledky?subjektId=875537&amp;typ=UPLNY">Úplný výpis</a>
</body></html>
"""

DETAIL_HTML = """
<html><body>
<table><tr><th>Číslo listiny</th><td>S 10868/SL16/KSBR</td></tr></table>
<a href="/ias/content/download?id=12345678">zápis ze schůze shromáždění SVJ</a>
</body></html>
"""


def test_parse_subjekt_id():
    assert parse_subjekt_id(REJSTRIK_HTML) == "875537"


def test_parse_listiny():
    listiny = parse_listiny_html(LISTINY_HTML, "875537")
    assert len(listiny) == 2

    l = listiny[0]
    assert l.cislo == "S 10868/SL16/KSBR"
    assert l.typ == "ostatní zápis ze schůze shromáždění SVJ"
    assert l.dokument_id == "85685221"
    assert l.spis == "949328"
    assert l.vznik.year == 2024 and l.vznik.month == 10
    assert l.stran == 2
    assert l.is_interesting

    zaverka = listiny[1]
    assert not zaverka.is_interesting


def test_parse_download_url():
    url = parse_download_url(DETAIL_HTML)
    assert url == "https://or.justice.cz/ias/content/download?id=12345678"


def test_parse_download_url_missing():
    assert parse_download_url("<html><body>nic</body></html>") is None


def test_external_id_fallback():
    l = Listina(cislo="", typ="zápis", vznik=None, doslo=None, zalozeno=None,
                stran=None, dokument_id="42", subjekt_id="875537")
    assert l.external_id == "SL-42"
