"""Jednotný systém detekce obchodních signálů RBD Radaru.

Nahrazuje dřívější dvojici scoring.py (body) + signals.py (priority).
Každé pravidlo má:
  - type / label / category  ... identifikace signálu
  - priority (0-100)         ... jak "horký" je signál pro obchodníka
  - points                   ... příspěvek do celkového skóre dokumentu
  - keywords                 ... alespoň jedno klíčové slovo musí být v textu
  - action_words             ... pokud jsou uvedena, musí se v kontextu objevit
                                 alespoň jedno (odfiltruje pouhé zmínky)

Vyhledávání je odolné vůči chybějící diakritice (častý artefakt OCR):
text i klíčová slova se porovnávají v normalizované podobě bez diakritiky.
"""

import re
import unicodedata


# ---------------------------------------------------------------------------
# Normalizace (odstranění diakritiky) se zachováním mapování indexů
# ---------------------------------------------------------------------------

def _strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalize_with_map(text: str):
    """Vrátí (normalizovaný text, mapa indexů norm -> orig)."""
    out = []
    index_map = []
    for i, ch in enumerate(text):
        base = _strip_diacritics(ch).lower()
        if not base:
            continue
        for c in base:
            out.append(c)
            index_map.append(i)
    return "".join(out), index_map


def _norm(s: str) -> str:
    return _strip_diacritics(s).lower()


# ---------------------------------------------------------------------------
# Pravidla
# ---------------------------------------------------------------------------

ACTION_COMMON = [
    "plán", "plánuje", "příprav", "návrh", "schválen", "schválil",
    "realizac", "projekt", "rekonstrukc", "oprav", "výběr", "nabídk",
]

SIGNAL_RULES = [
    # --- Realizační fáze (nejsilnější signály) -----------------------------
    {
        "type": "vyber_zhotovitele", "label": "Výběr zhotovitele",
        "category": "realizace", "priority": 98, "points": 35,
        "keywords": [r"výběr.{0,40}zhotovitel", r"zhotovitel.{0,40}vybr"],
        "regex": True, "action_words": [],
    },
    {
        "type": "smlouva_o_dilo", "label": "Smlouva o dílo",
        "category": "realizace", "priority": 97, "points": 30,
        "keywords": [r"smlouv[ay].{0,30}o dílo"],
        "regex": True, "action_words": [],
    },
    {
        "type": "vyberove_rizeni", "label": "Výběrové řízení",
        "category": "poptávka", "priority": 92, "points": 28,
        "keywords": ["výběrové řízení", "výběrového řízení"],
        "action_words": [],
    },
    # --- Stavební záměry ---------------------------------------------------
    {
        "type": "zatepleni", "label": "Zateplení domu",
        "category": "zateplení", "priority": 95, "points": 25,
        "keywords": ["zatepl", "kontaktní zatepl", "minerální izol", "fasád"],
        "action_words": ACTION_COMMON,
    },
    {
        "type": "revitalizace", "label": "Revitalizace domu",
        "category": "revitalizace", "priority": 95, "points": 25,
        "keywords": ["revitaliz", "komplexní rekonstrukce", "rekonstrukce domu"],
        "action_words": ACTION_COMMON,
    },
    {
        "type": "fve", "label": "Fotovoltaika",
        "category": "FVE", "priority": 93, "points": 18,
        "keywords": ["fotovolta", r"\bfve\b", "solární elektr"],
        "regex": True,
        "action_words": ACTION_COMMON + ["instalac"],
    },
    {
        "type": "strecha", "label": "Rekonstrukce střechy",
        "category": "střecha", "priority": 90, "points": 15,
        "keywords": ["střech"],
        "action_words": ACTION_COMMON + ["výměn", "havarijn"],
    },
    {
        "type": "balkony_lodzie", "label": "Balkony / lodžie",
        "category": "balkony", "priority": 90, "points": 18,
        "keywords": ["balkon", "lodži", "lodžie"],
        "action_words": ACTION_COMMON + ["výměn", "zasklen"],
    },
    {
        "type": "hydroizolace", "label": "Hydroizolace",
        "category": "hydroizolace", "priority": 85, "points": 20,
        "keywords": ["hydroizol", "izolace spodní stavby"],
        "action_words": ACTION_COMMON,
    },
    {
        # Akční slovo musí být blízko slova "výtah" — jinak by signál spouštěl
        # např. výčet nákladů (…, Výtah, Úklid) vedle "fondu oprav".
        "type": "vytah", "label": "Výtah (rekonstrukce / výměna)",
        "category": "výtah", "priority": 85, "points": 18,
        "keywords": ["výtah"],
        "action_words": ["rekonstrukc", "výměn", "modernizac", "nový",
                         "oprav", "revize", "plán", "schválen"],
        "proximity": 60,
    },
    {
        # Informační signál: dům má výtah (relevantní pro výtahářské firmy).
        "type": "vytah_info", "label": "Výtah v domě",
        "category": "info", "priority": 40, "points": 3,
        "keywords": ["výtah"],
        "action_words": [],
    },
    {
        "type": "okna", "label": "Výměna / rekonstrukce oken",
        "category": "okna", "priority": 80, "points": 15,
        "keywords": ["oken", "okna"],
        "action_words": ["výměn", "rekonstrukc", "nová", "nových", "plán",
                         "schválen", "oprav"],
    },
    {
        "type": "havarijni_stav", "label": "Havarijní stav",
        "category": "havárie", "priority": 88, "points": 22,
        "keywords": ["havarijn"],
        "action_words": [],
    },
    # --- Přípravná fáze ----------------------------------------------------
    {
        "type": "projektova_dokumentace", "label": "Projektová dokumentace",
        "category": "příprava", "priority": 80, "points": 15,
        "keywords": [r"projektov.{0,20}dokumentac"],
        "regex": True, "action_words": [],
    },
    {
        "type": "energeticky_audit", "label": "Energetický audit",
        "category": "příprava", "priority": 80, "points": 18,
        "keywords": [r"energetick.{0,30}audit"],
        "regex": True, "action_words": [],
    },
    {
        "type": "penb", "label": "PENB",
        "category": "příprava", "priority": 70, "points": 12,
        "keywords": [r"\bpenb\b"],
        "regex": True, "action_words": [],
    },
    # --- Financování -------------------------------------------------------
    {
        "type": "nzu", "label": "Dotace NZÚ",
        "category": "financování", "priority": 75, "points": 18,
        "keywords": [r"\bnzu\b", "nová zelená úsporám", "zelená úsporám"],
        "regex": True, "action_words": [],
    },
    {
        "type": "sfpi", "label": "SFPI",
        "category": "financování", "priority": 75, "points": 18,
        "keywords": [r"\bsfpi\b"],
        "regex": True, "action_words": [],
    },
    {
        "type": "dotace", "label": "Dotace",
        "category": "financování", "priority": 70, "points": 12,
        "keywords": ["dotac"],
        "action_words": [],
    },
    {
        "type": "uver", "label": "Úvěr",
        "category": "financování", "priority": 70, "points": 10,
        "keywords": ["úvěr"],
        "action_words": [],
    },
]

# Kombinační bonusy: (množina kategorií, bonusové body)
COMBO_BONUSES = [
    ({"zateplení", "příprava"}, 15),
    ({"zateplení", "poptávka"}, 15),
    ({"revitalizace", "financování"}, 10),
    ({"balkony", "zateplení"}, 10),
]

LEAD_LEVELS = [(80, "HOT"), (60, "HIGH"), (35, "WATCH"), (0, "LOW")]


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def find_context(text: str, keyword: str, radius: int = 220) -> str:
    """Vrátí okolí prvního výskytu (bez ohledu na diakritiku a velikost písmen)."""
    norm_text, index_map = _normalize_with_map(text)
    m = re.search(_norm(keyword), norm_text, re.IGNORECASE)
    if not m:
        return ""
    start_o = index_map[max(0, m.start() - radius)] if index_map else 0
    end_norm = min(len(index_map) - 1, m.end() + radius)
    end_o = index_map[end_norm] + 1 if index_map else len(text)
    return " ".join(text[start_o:end_o].split())


def _search(pattern: str, norm_text: str, is_regex: bool):
    pat = _norm(pattern) if not is_regex else _norm(pattern)
    if not is_regex:
        pat = re.escape(pat)
    return re.search(pat, norm_text, re.IGNORECASE)


def _context_from_match(text, index_map, m, radius=220):
    start_o = index_map[max(0, m.start() - radius)]
    end_norm = min(len(index_map) - 1, m.end() + radius)
    end_o = index_map[end_norm] + 1
    return " ".join(text[start_o:end_o].split())


# ---------------------------------------------------------------------------
# Hlavní analýza
# ---------------------------------------------------------------------------

def detect_signals(text: str) -> list[dict]:
    """Vrátí seznam signálů seřazený podle priority (kompatibilní se starým API)."""
    if not text or not text.strip():
        return []

    norm_text, index_map = _normalize_with_map(text)
    signals = []

    for rule in SIGNAL_RULES:
        is_regex = rule.get("regex", False)
        found = None
        found_kw = None
        for kw in rule["keywords"]:
            m = _search(kw, norm_text, is_regex)
            if m:
                found, found_kw = m, kw
                break
        if not found:
            continue

        context = _context_from_match(text, index_map, found)

        if rule["action_words"]:
            proximity = rule.get("proximity")
            if proximity:
                # Akční slovo musí být do N znaků od klíčového slova.
                lo = max(0, found.start() - proximity)
                hi = min(len(norm_text), found.end() + proximity)
                haystack = norm_text[lo:hi]
            else:
                haystack = _norm(context)
            if not any(re.search(re.escape(_norm(w)), haystack)
                       for w in rule["action_words"]):
                continue

        signals.append({
            "type": rule["type"],
            "label": rule["label"],
            "category": rule["category"],
            "priority": rule["priority"],
            "points": rule["points"],
            "keyword": found_kw,
            "value": None,
            "context": context,
        })

    # --- Hodnotové signály -------------------------------------------------

    # Finanční situace SVJ (náklady převyšují zálohy apod.)
    m = re.search(
        r"naklady.{0,200}prevysuji|obnos.{0,80}vybran|nedostatek.{0,60}prostred",
        norm_text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        signals.append({
            "type": "financni_situace", "label": "Finanční situace SVJ",
            "category": "finance", "priority": 75, "points": 10,
            "keyword": "náklady převyšují", "value": None,
            "context": _context_from_match(text, index_map, m),
        })

    # Zvýšení záloh (x %)
    m = re.search(
        r"(?:navyseni|zvyseni|navysenim|zvysenim).{0,120}?(?:zaloh|prispevk).{0,120}?(\d{1,3})\s*%",
        norm_text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        signals.append({
            "type": "zvyseni_zaloh", "label": "Zvýšení záloh",
            "category": "finance", "priority": 70, "points": 12,
            "keyword": "zvýšení záloh", "value": m.group(1) + " %",
            "context": _context_from_match(text, index_map, m),
        })

    # Fond oprav / dlouhodobé zálohy (x Kč/m²)
    m = re.search(
        r"(?:fond[u]? oprav|dlouhodob\w{0,4} zaloh).{0,160}?(\d{1,4})\s*kc\s*/?\s*m",
        norm_text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        signals.append({
            "type": "fond_oprav", "label": "Fond oprav / dlouhodobé zálohy",
            "category": "finance", "priority": 60, "points": 8,
            "keyword": "fond oprav", "value": m.group(1) + " Kč/m²",
            "context": _context_from_match(text, index_map, m),
        })

    # Nově zvolený výbor (kontaktní příležitost)
    m = re.search(r"zvoleni clenove|volb\w{0,4}.{0,40}vybor", norm_text,
                  re.IGNORECASE | re.DOTALL)
    if m:
        signals.append({
            "type": "volba_vyboru", "label": "Volba výboru",
            "category": "kontakt", "priority": 50, "points": 5,
            "keyword": "volba výboru", "value": None,
            "context": _context_from_match(text, index_map, m),
        })

    # Potlačení překryvů: obecná "dotace" nic nepřidává, když je detekováno NZÚ;
    # informační "výtah v domě" je zbytečný, když je detekována rekonstrukce výtahu.
    types = {s["type"] for s in signals}
    if "nzu" in types:
        signals = [s for s in signals if s["type"] != "dotace"]
    if "vytah" in types:
        signals = [s for s in signals if s["type"] != "vytah_info"]

    return sorted(signals, key=lambda x: x["priority"], reverse=True)


def score_signals(signals: list[dict]) -> int:
    score = sum(s["points"] for s in signals)
    cats = {s["category"] for s in signals}
    for combo, bonus in COMBO_BONUSES:
        if combo <= cats:
            score += bonus
    return min(score, 100)


def lead_level(score: int) -> str:
    for threshold, label in LEAD_LEVELS:
        if score >= threshold:
            return label
    return "LOW"


def analyze(text: str):
    """Kompatibilní náhrada za scoring.analyze -> (score, hits)."""
    signals = detect_signals(text)
    hits = [{
        "keyword": s["keyword"],
        "category": s["category"],
        "points": s["points"],
        "evidence": s["context"],
        "type": s["type"],
        "label": s["label"],
        "priority": s["priority"],
        "value": s["value"],
    } for s in signals]
    return score_signals(signals), hits
