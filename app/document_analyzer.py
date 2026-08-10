"""Extrakce metadat dokumentu (typ, datum shromáždění, výbor...).

Doplněk k signal_engine: signal_engine hledá obchodní signály,
document_analyzer strukturální údaje o dokumentu.
"""

import re
from datetime import datetime

from .signal_engine import _normalize_with_map, _norm


DATE_RE = r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})"


def _parse_cz_date(day: str, month: str, year: str):
    try:
        return datetime(int(year), int(month), int(day))
    except ValueError:
        return None


def analyze_document(text: str) -> dict:
    result = {
        "document_type": None,
        "meeting_date": None,       # datetime | None
        "meeting_date_text": None,  # "10.10.2024" | None
        "board_members": [],
    }
    if not text or not text.strip():
        return result

    norm_text, index_map = _normalize_with_map(text)

    # --- Typ dokumentu -----------------------------------------------------
    if re.search(r"zapis.{0,80}shromazdeni|shromazdeni.{0,80}zapis", norm_text, re.S):
        result["document_type"] = "zápis ze shromáždění"
    elif re.search(r"notarsky zapis", norm_text):
        result["document_type"] = "notářský zápis"
    elif re.search(r"stanovy", norm_text):
        result["document_type"] = "stanovy"
    elif re.search(r"ucetni zaverk|rozvaha|vykaz zisku", norm_text):
        result["document_type"] = "účetní závěrka"
    elif re.search(r"zapis", norm_text):
        result["document_type"] = "zápis"

    # --- Datum shromáždění -------------------------------------------------
    m = re.search(r"konan[eaéí]\w*\s+dne\s+" + DATE_RE, norm_text)
    if not m:
        m = re.search(r"shromazdeni.{0,120}?dne\s+" + DATE_RE, norm_text, re.S)
    if m:
        dt = _parse_cz_date(m.group(1), m.group(2), m.group(3))
        if dt:
            result["meeting_date"] = dt
            result["meeting_date_text"] = f"{int(m.group(1))}.{int(m.group(2))}.{int(m.group(3))}"

    # --- Členové výboru ----------------------------------------------------
    m = re.search(r"zvoleni clenove\s*:?\s*", norm_text)
    if m:
        # Vezmi zbytek řádku z původního textu.
        start_orig = index_map[min(m.end(), len(index_map) - 1)]
        line = text[start_orig:start_orig + 200].splitlines()[0]
        members = [
            x.strip(" .;-–")
            for x in re.split(r",|\s+a\s+", line)
            if x.strip(" .;-–")
        ]
        # Jen položky vypadající jako jména (2+ slova začínající velkým písmenem).
        result["board_members"] = [
            mbr for mbr in members
            if re.match(r"^[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][^\d]+\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]", mbr)
        ][:10]

    return result
