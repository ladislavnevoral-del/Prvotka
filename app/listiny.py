"""Klient pro Sbírku listin na or.justice.cz.

Web or.justice.cz nemá oficiální API a poměrně agresivně omezuje
frekvenci požadavků (při rychlém přístupu vrací timeouty). Klient proto:
  - drží mezi požadavky pauzu (výchozí 3 s),
  - opakuje neúspěšné požadavky s exponenciálním čekáním,
  - stahuje jen listiny, které v databázi ještě nejsou.

Tok:  IČO -> subjektId (stránka rejstříku)
      subjektId -> seznam listin (vypis-sl-firma)
      dokumentId -> odkaz na PDF (vypis-sl-detail, /ias/content/download?id=...)
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://or.justice.cz/ias/ui"
CONTENT_BASE = "https://or.justice.cz"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "RBD-Radar/0.3 (interni monitoring SVJ; kontakt: provozovatel)"
)

# Typy listin, které mají pro obchodní signály smysl.
INTERESTING_TYPES = re.compile(
    r"z[áa]pis|shrom[áa]žd|rozhodnut|not[áa]řsk|stanovy", re.IGNORECASE
)


@dataclass
class Listina:
    cislo: str                     # např. "S 10868/SL16/KSBR"
    typ: str                       # např. "zápis ze schůze shromáždění SVJ"
    vznik: datetime | None         # datum vzniku listiny
    doslo: datetime | None         # došlo na soud
    zalozeno: datetime | None      # založeno do SL
    stran: int | None
    dokument_id: str
    subjekt_id: str
    spis: str | None = None
    detail_url: str = field(default="")

    @property
    def external_id(self) -> str:
        return self.cislo or f"SL-{self.dokument_id}"

    @property
    def is_interesting(self) -> bool:
        return bool(INTERESTING_TYPES.search(self.typ or ""))


def _parse_cz_date(value: str) -> datetime | None:
    value = (value or "").strip()
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _qs(href: str, name: str) -> str | None:
    m = re.search(rf"[?&]{name}=(\d+)", href or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Parsování HTML (oddělené od klienta kvůli testovatelnosti bez sítě)
# ---------------------------------------------------------------------------

def parse_subjekt_id(html: str) -> str | None:
    """Najde subjektId v HTML stránky rejstříku (odkaz na Sbírku listin)."""
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        sid = _qs(a["href"], "subjektId")
        if sid and "vypis-sl" in a["href"]:
            return sid
    for a in soup.find_all("a", href=True):
        sid = _qs(a["href"], "subjektId")
        if sid:
            return sid
    return None


def parse_listiny_html(html: str, subjekt_id: str) -> list[Listina]:
    """Vyparsuje tabulku listin ze stránky vypis-sl-firma."""
    soup = BeautifulSoup(html, "html.parser")
    listiny: list[Listina] = []
    for table in soup.find_all("table"):
        heads = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        if not any("Číslo listiny" in h for h in heads):
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            a = tds[0].find("a", href=True)
            if not a:
                continue
            href = a["href"]
            dokument_id = _qs(href, "dokument")
            if not dokument_id:
                continue
            stran_txt = tds[5].get_text(strip=True)
            listiny.append(Listina(
                cislo=a.get_text(" ", strip=True).replace("\xa0", " "),
                typ=tds[1].get_text(" ", strip=True),
                vznik=_parse_cz_date(tds[2].get_text(strip=True)),
                doslo=_parse_cz_date(tds[3].get_text(strip=True)),
                zalozeno=_parse_cz_date(tds[4].get_text(strip=True)),
                stran=int(stran_txt) if stran_txt.isdigit() else None,
                dokument_id=dokument_id,
                subjekt_id=subjekt_id,
                spis=_qs(href, "spis"),
                detail_url=f"{BASE}/{href.lstrip('./')}",
            ))
    return listiny


def parse_download_url(html: str) -> str | None:
    """Najde odkaz na PDF v HTML detailu listiny."""
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "content/download" in href or re.search(r"\.pdf(\?|$)", href, re.I):
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                return CONTENT_BASE + href
            return f"{BASE}/{href.lstrip('./')}"
    return None


class ListinyClient:
    def __init__(self, delay: float = 3.0, timeout: int = 60,
                 max_retries: int = 4):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "cs,en;q=0.8",
        })
        self._last_request = 0.0

    # -- nízká úroveň -------------------------------------------------------

    def _get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(self.max_retries):
            wait = self.delay - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                self._last_request = time.time()
                r = self.session.get(url, timeout=self.timeout, **kwargs)
                if r.status_code in (429, 502, 503, 504):
                    raise requests.RequestException(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r
            except requests.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise
                backoff = self.delay * (2 ** (attempt + 1))
                print(f"  ! {exc} — čekám {backoff:.0f} s a zkouším znovu")
                time.sleep(backoff)
        raise RuntimeError("unreachable")

    # -- kroky --------------------------------------------------------------

    def find_subjekt_id(self, ico: str) -> str:
        """Najde subjektId (webové ID) podle IČO."""
        ico_clean = re.sub(r"\D", "", ico).lstrip("0") or ico
        r = self._get(f"{BASE}/rejstrik-$firma",
                      params={"ico": ico_clean, "jenPlatne": "PLATNE",
                              "polozek": "50"})
        sid = parse_subjekt_id(r.text)
        if not sid:
            raise LookupError(f"Subjekt s IČO {ico} nebyl v rejstříku nalezen.")
        return sid

    def list_listiny(self, subjekt_id: str) -> list[Listina]:
        """Vrátí seznam listin ze stránky Sbírky listin subjektu."""
        r = self._get(f"{BASE}/vypis-sl-firma", params={"subjektId": subjekt_id})
        return parse_listiny_html(r.text, subjekt_id)

    def get_download_url(self, listina: Listina) -> str:
        """Z detailu listiny vytáhne odkaz na PDF."""
        params = {"dokument": listina.dokument_id,
                  "subjektId": listina.subjekt_id}
        if listina.spis:
            params["spis"] = listina.spis
        r = self._get(f"{BASE}/vypis-sl-detail", params=params)
        url = parse_download_url(r.text)
        if not url:
            raise LookupError(
                f"Odkaz na PDF nebyl na detailu listiny {listina.cislo} nalezen."
            )
        return url

    def download_pdf(self, listina: Listina, target: str | Path) -> Path:
        """Stáhne PDF listiny do cílového souboru."""
        url = self.get_download_url(listina)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        r = self._get(url, stream=True)
        content_type = r.headers.get("Content-Type", "")
        first = next(r.iter_content(chunk_size=1024 * 256), b"")
        if not first.startswith(b"%PDF") and "pdf" not in content_type.lower():
            raise RuntimeError(
                f"Stažený obsah listiny {listina.cislo} nevypadá jako PDF "
                f"(Content-Type: {content_type})."
            )
        with open(target, "wb") as f:
            f.write(first)
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        return target
