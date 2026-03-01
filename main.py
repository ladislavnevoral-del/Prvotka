from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import sqlite3
import io
import os
import httpx
from typing import Optional
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import uvicorn

app = FastAPI(title="Prvotkář 3.1 API")

@app.get("/api/version")
def version():
    return {"version": "3.1", "ok": True}

@app.get("/")
async def root():
    return FileResponse("index.html")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

DB_FILE = "prvotkar.db"

def get_db():
    if not os.path.exists(DB_FILE):
        raise HTTPException(
            status_code=503,
            detail="Databáze nenalezena. Spusť nejdřív: python3 sync_ares.py"
        )
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(row):
    return dict(row)

# ===================== ENDPOINTS =====================

@app.get("/api/kraje")
async def get_kraje():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT DISTINCT kraj, kraj_kod FROM subjekty WHERE kraj IS NOT NULL ORDER BY kraj"
        ).fetchall()
        return [{"nazev": r["kraj"], "kod": r["kraj_kod"]} for r in rows]
    finally:
        conn.close()

@app.get("/api/svj")
async def get_svj(
    obec: str = Query(...),
    ulice: Optional[str] = None,
    cast_obce: Optional[str] = None,
    typ: Optional[str] = "svj",
    start: int = 0,
    pocet: int = 200,
):
    conn = get_db()
    try:
        # Hledej přesnou shodu i části (např. "Brno" najde i "Brno-Židenice")
        params = [obec, obec + "-%", typ]
        filters = "(obec = ? OR obec LIKE ?) AND typ = ?"
        if cast_obce:
            filters += " AND cast_obce = ?"
            params.append(cast_obce)
        if ulice:
            filters += " AND ulice = ?"
            params.append(ulice)
        all_rows = conn.execute(
            f"SELECT * FROM subjekty WHERE {filters} ORDER BY nazev",
            params
        ).fetchall()
        celkem = len(all_rows)
        page = all_rows[start:start + pocet]

        subjekty = []
        for r in page:
            d = row_to_dict(r)
            lat = d.get("lat") or None
            lng = d.get("lng") or None
            subjekty.append({
                "ico": d["ico"],
                "obchodniJmeno": d["nazev"],
                "stavSubjektu": d["stav"],
                "datumVzniku": d["datum_vzniku"],
                "lat": lat if lat and lat != 0.0 else None,
                "lng": lng if lng and lng != 0.0 else None,
                "sidlo": {
                    "nazevObce": d["obec"],
                    "nazevCastiObce": d["cast_obce"],
                    "nazevUlice": d["ulice"],
                    "cisloDomovni": d["cislo_popisne"],
                    "cisloOrientacni": d["cislo_orientacni"],
                    "psc": d["psc"],
                    "nazevKraje": d["kraj"],
                }
            })

        return {"celkem": celkem, "subjekty": subjekty}
    finally:
        conn.close()

@app.get("/api/obce")
async def get_obce(q: str = Query(..., min_length=2), typ: Optional[str] = None):
    """Autocomplete obcí z lokální DB"""
    conn = get_db()
    try:
        query = "SELECT DISTINCT obec, kraj FROM subjekty WHERE obec LIKE ? AND obec IS NOT NULL"
        params = [f"{q}%"]
        if typ:
            query += " AND typ = ?"
            params.append(typ)
        query += " ORDER BY obec LIMIT 20"
        rows = conn.execute(query, params).fetchall()
        return [{"obec": r["obec"], "kraj": r["kraj"]} for r in rows]
    finally:
        conn.close()

@app.get("/api/stats")
async def get_stats():
    """Statistiky databáze"""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM subjekty").fetchone()[0]
        svj = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='svj'").fetchone()[0]
        bd = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='bd'").fetchone()[0]
        updated = conn.execute("SELECT MAX(updated_at) FROM subjekty").fetchone()[0]
        obce = conn.execute("SELECT COUNT(DISTINCT obec) FROM subjekty").fetchone()[0]
        return {
            "celkem": total, "svj": svj, "bd": bd,
            "obce": obce, "posledni_sync": updated
        }
    finally:
        conn.close()

@app.get("/api/hledat")
async def hledat(
    q: str = Query(..., min_length=2),
    typ: Optional[str] = None,
    limit: int = 50,
):
    """Fulltext hledání napříč celou ČR podle názvu SVJ/BD"""
    conn = get_db()
    try:
        sql    = "SELECT * FROM subjekty WHERE nazev LIKE ?"
        params = [f"%{q}%"]
        if typ:
            sql += " AND typ = ?"
            params.append(typ)
        sql += " ORDER BY nazev LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            lat = d.get("lat") or None
            lng = d.get("lng") or None
            result.append({
                "ico":           d["ico"],
                "obchodniJmeno": d["nazev"],
                "stavSubjektu":  d["stav"],
                "datumVzniku":   d["datum_vzniku"],
                "lat": lat if lat and lat != 0.0 else None,
                "lng": lng if lng and lng != 0.0 else None,
                "sidlo": {
                    "nazevObce":       d["obec"],
                    "nazevCastiObce":  d["cast_obce"],
                    "nazevUlice":      d["ulice"],
                    "cisloDomovni":    d["cislo_popisne"],
                    "cisloOrientacni": d["cislo_orientacni"],
                    "psc":             d["psc"],
                    "nazevKraje":      d["kraj"],
                }
            })
        return {"celkem": len(result), "subjekty": result}
    finally:
        conn.close()

@app.get("/api/okoli")
async def get_okoli(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: float = Query(1.0),   # km
    typ: Optional[str] = None,
):
    """Vrátí SVJ/BD v okolí GPS souřadnic (radius v km)"""
    conn = get_db()
    try:
        # Haversine aproximace přes bounding box (rychlé, bez funkce v SQLite)
        # 1 stupeň lat ≈ 111 km, 1 stupeň lng ≈ 71 km (pro CZ)
        dlat = radius / 111.0
        dlng = radius / 71.0
        sql    = """SELECT *, 
                    ((lat - ?) * (lat - ?) * 12321 + (lng - ?) * (lng - ?) * 5041) AS dist2
                    FROM subjekty
                    WHERE lat IS NOT NULL AND lat != 0
                      AND lat BETWEEN ? AND ?
                      AND lng BETWEEN ? AND ?"""
        params = [lat, lat, lng, lng,
                  lat - dlat, lat + dlat,
                  lng - dlng, lng + dlng]
        if typ:
            sql += " AND typ = ?"
            params.append(typ)
        sql += " ORDER BY dist2 LIMIT 200"
        rows = conn.execute(sql, params).fetchall()

        # Přesný filtr přes Haversine
        import math
        def haversine(lat1, lng1, lat2, lng2):
            R    = 6371
            dlat = math.radians(lat2 - lat1)
            dlng = math.radians(lng2 - lng1)
            a    = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
            return R * 2 * math.asin(math.sqrt(a))

        result = []
        for r in rows:
            d    = row_to_dict(r)
            rlat = d.get("lat")
            rlng = d.get("lng")
            if not rlat or not rlng:
                continue
            dist = haversine(lat, lng, rlat, rlng)
            if dist <= radius:
                result.append({
                    "ico":           d["ico"],
                    "obchodniJmeno": d["nazev"],
                    "stavSubjektu":  d["stav"],
                    "datumVzniku":   d["datum_vzniku"],
                    "lat":           rlat,
                    "lng":           rlng,
                    "vzdalenost":    round(dist * 1000),  # v metrech
                    "sidlo": {
                        "nazevObce":       d["obec"],
                        "nazevCastiObce":  d["cast_obce"],
                        "nazevUlice":      d["ulice"],
                        "cisloDomovni":    d["cislo_popisne"],
                        "cisloOrientacni": d["cislo_orientacni"],
                        "psc":             d["psc"],
                        "nazevKraje":      d["kraj"],
                    }
                })

        result.sort(key=lambda x: x["vzdalenost"])
        return {"celkem": len(result), "subjekty": result}
    finally:
        conn.close()

@app.get("/api/svj/{ico}/detail")
async def get_svj_detail(ico: str):
    import httpx, json as jsonlib
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM subjekty WHERE ico = ?", [ico]).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Subjekt nenalezen")

    d = row_to_dict(row)
    base = {
        "ico": d["ico"],
        "nazev": d["nazev"],
        "sidlo": {
            "nazevObce": d["obec"],
            "nazevCastiObce": d["cast_obce"],
            "nazevUlice": d["ulice"],
            "cisloDomovni": d["cislo_popisne"],
            "cisloOrientacni": d["cislo_orientacni"],
            "psc": d["psc"],
            "nazevKraje": d["kraj"],
        },
        "datumVzniku": d["datum_vzniku"],
        "stavSubjektu": d["stav"],
        "osoby": [],
        "spisovaZnacka": None,
        "subjektId": None,
    }

    # Získej osoby + spisovaZnacka z VR endpointu
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/{ico}"
            )
            if r.status_code == 200:
                vr = r.json()
                import re as _re
                osoby = []
                seen = set()
                for zaznam in vr.get("zaznamy", []):
                    # Spisová značka
                    for sz in zaznam.get("spisovaZnacka", []):
                        soud = sz.get("soud","")
                        oddil = sz.get("oddil","")
                        vlozka = sz.get("vlozka","")
                        if oddil and vlozka:
                            base["spisovaZnacka"] = f"{oddil} {vlozka}/{soud}"
                    # Osoby
                    for org in zaznam.get("statutarniOrgany", []):
                        for clen in org.get("clenoveOrganu", []):
                            # Přeskoč vymazané členy (datumVymazu = zaniklý záznam)
                            if clen.get("datumVymazu"):
                                continue
                            clenstvi = clen.get("clenstvi", {})
                            funkce_info = clenstvi.get("funkce", {})
                            # Přeskoč zaniklé funkce
                            if funkce_info.get("zanikFunkce"):
                                continue
                            # Fyzická osoba přímo
                            fo = clen.get("fyzickaOsoba")
                            # Nebo zástupce právnické osoby (hledej aktivního zástupce)
                            if not fo:
                                po = clen.get("pravnickaOsoba", {})
                                for z in po.get("zastoupeni", []):
                                    if not z.get("datumVymazu"):
                                        fo = z.get("fyzickaOsoba")
                                        break
                            if not fo:
                                continue
                            jmeno = " ".join(filter(None, [
                                fo.get("titulPredJmenem",""),
                                fo.get("jmeno",""),
                                fo.get("prijmeni","")
                            ])).strip()
                            if fo.get("titulZaJmenem"):
                                jmeno += ", " + fo["titulZaJmenem"]
                            narozeni = fo.get("datumNarozeni","")
                            key = f"{jmeno}|{narozeni}"
                            if not jmeno or key in seen:
                                continue
                            seen.add(key)
                            osoby.append({
                                "jmeno": jmeno,
                                "prijmeni": fo.get("prijmeni",""),
                                "datumNarozeni": narozeni,
                                "funkce": funkce_info.get("nazev","člen výboru"),
                                "nazevRole": funkce_info.get("nazev","člen výboru"),
                            })
                base["osoby"] = osoby

            # Získej subjektId z Justice.cz
            r2 = await client.get(
                f"https://or.justice.cz/ias/ui/rejstrik-$firma?ico={ico}&jenPlatne=PLATNE",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8
            )
            if r2.status_code == 200:
                import re as _re
                ids = _re.findall(r'subjektId[=:](\d+)', r2.text)
                if ids:
                    base["subjektId"] = ids[0]
    except Exception:
        pass

    return base

def _parse_osoby_vr(vr_json: dict) -> list:
    """Parsuje aktivní členy výboru z ekonomicke-subjekty-vr response."""
    osoby = []
    seen = set()
    for zaznam in vr_json.get("zaznamy", []):
        for org in zaznam.get("statutarniOrgany", []):
            for clen in org.get("clenoveOrganu", []):
                if clen.get("datumVymazu"):
                    continue
                clenstvi = clen.get("clenstvi", {})
                funkce_info = clenstvi.get("funkce", {})
                if funkce_info.get("zanikFunkce"):
                    continue
                fo = clen.get("fyzickaOsoba")
                if not fo:
                    po = clen.get("pravnickaOsoba", {})
                    for z in po.get("zastoupeni", []):
                        if not z.get("datumVymazu"):
                            fo = z.get("fyzickaOsoba")
                            break
                if not fo:
                    continue
                jmeno = " ".join(filter(None, [
                    fo.get("titulPredJmenem", ""),
                    fo.get("jmeno", ""),
                    fo.get("prijmeni", "")
                ])).strip()
                if fo.get("titulZaJmenem"):
                    jmeno += ", " + fo["titulZaJmenem"]
                narozeni = fo.get("datumNarozeni", "")
                key = f"{jmeno}|{narozeni}"
                if not jmeno or key in seen:
                    continue
                seen.add(key)
                osoby.append({
                    "jmeno": jmeno,
                    "narozeni": narozeni,
                    "funkce": funkce_info.get("nazev", "člen výboru"),
                })
    return osoby


@app.get("/api/export/excel")
async def export_excel(
    obec: str = Query(...),
    ulice: Optional[str] = None,
    cast_obce: Optional[str] = None,
    typ: Optional[str] = "svj",
):
    result = await get_svj(obec=obec, ulice=ulice, cast_obce=cast_obce, typ=typ, start=0, pocet=9999)
    data = result["subjekty"]
    label = "BD" if typ == "bd" else "SVJ"

    # Stáhni osoby pro prvních 150 SVJ (ARES throttling)
    MAX_OSOBY = 150
    ico_list = [s.get("ico") for s in data[:MAX_OSOBY] if s.get("ico")]
    osoby_map: dict = {}
    async with httpx.AsyncClient(timeout=12) as client:
        sem = _asyncio.Semaphore(6)
        async def fetch_osoby(ico):
            async with sem:
                try:
                    await _asyncio.sleep(0.1)
                    r = await client.get(
                        f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/{ico}"
                    )
                    if r.status_code == 200:
                        osoby_map[ico] = _parse_osoby_vr(r.json())
                except Exception:
                    pass
        await _asyncio.gather(*[fetch_osoby(ico) for ico in ico_list])

    # Zjisti max počet členů (pro dynamické sloupce)
    # max_clenu nahrazen max_ostatni_clen níže

    wb = Workbook()
    ws = wb.active
    ws.title = "Seznam"

    hf = PatternFill(start_color="1B4F72", end_color="1B4F72", fill_type="solid")
    hf2 = PatternFill(start_color="2E4057", end_color="2E4057", fill_type="solid")
    af = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid")
    b = Border(
        left=Side(style="thin", color="BDC3C7"), right=Side(style="thin", color="BDC3C7"),
        top=Side(style="thin", color="BDC3C7"), bottom=Side(style="thin", color="BDC3C7")
    )

    # Spočítej max ostatních členů pro dynamické sloupce
    max_ostatni_clen = max((len([o for o in v if 'předseda' not in (o.get('funkce','') or '').lower()]) for v in osoby_map.values()), default=0)
    total_cols = 12 + max_ostatni_clen * 3
    ws.merge_cells(f"A1:{get_column_letter(total_cols)}1")
    ws["A1"].value = f"Seznam {label} – {obec}" + (f" / {ulice}" if ulice else "")
    ws["A1"].font = Font(bold=True, size=14, name="Calibri", color="1B4F72")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells(f"A2:{get_column_letter(total_cols)}2")
    ws["A2"].value = f"Celkem: {len(data)} záznamů | Zdroj: ARES (lokální DB) | Výbor: živá data z ARES VR"
    ws["A2"].font = Font(italic=True, size=10, color="7F8C8D", name="Calibri")
    ws["A2"].alignment = Alignment(horizontal="center")

    # Záhlaví - základní + výbor
    # Struktura: IČO | Název | Ulice | ČP | Obec | PSČ | Kraj | Rok | Předseda | Předseda nar. | Místopředs. | Místopředs. nar. | Člen 1 jméno | Člen 1 funkce | Člen 1 nar. | ...
    base_headers = ["IČO", f"Název {label}", "Ulice", "ČP/CO", "Obec", "PSČ", "Kraj", "Rok vzniku",
                    "Předseda – jméno", "Předseda – narozen",
                    "Místopředseda – jméno", "Místopředseda – narozen"]
    
    # Spočítej max ostatních členů (ne předseda, ne místopředseda)
    max_ostatni = 0
    for ico, osoby in osoby_map.items():
        ostatni = [o for o in osoby if 'předseda' not in (o.get('funkce') or '').lower()]
        max_ostatni = max(max_ostatni, len(ostatni))
    total_cols = len(base_headers) + max_ostatni * 3

    # Překresli merge buňky
    ws.merge_cells(f"A1:{get_column_letter(total_cols)}1")
    ws.merge_cells(f"A2:{get_column_letter(total_cols)}2")

    for col, header in enumerate(base_headers, 1):
        c = ws.cell(row=4, column=col, value=header)
        c.fill = hf if col <= 8 else hf2
        c.font = Font(color="FFFFFF", bold=True, size=10 if col > 8 else 11, name="Calibri")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = b

    for i in range(max_ostatni):
        col_base = len(base_headers) + 1 + i * 3
        for offset, header in enumerate([f"Člen {i+1} – jméno", f"Člen {i+1} – funkce", f"Člen {i+1} – narozen"]):
            c = ws.cell(row=4, column=col_base + offset, value=header)
            c.fill = hf2
            c.font = Font(color="FFFFFF", bold=True, size=10, name="Calibri")
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = b
    ws.row_dimensions[4].height = 30

    # Data
    for ri, s in enumerate(data, 5):
        sidlo = s.get("sidlo") or {}
        cp = str(sidlo.get("cisloDomovni") or "")
        co = sidlo.get("cisloOrientacni") or ""
        cislo = cp + ("/" + str(co) if co else "")
        rok = (s.get("datumVzniku") or "")[:4]
        fill = af if (ri - 5) % 2 == 1 else None

        base_vals = [
            s.get("ico"), s.get("obchodniJmeno"),
            sidlo.get("nazevUlice") or "", cislo,
            sidlo.get("nazevObce"), sidlo.get("psc"),
            sidlo.get("nazevKraje"), rok
        ]
        for col, val in enumerate(base_vals, 1):
            c = ws.cell(row=ri, column=col, value=val)
            if fill: c.fill = fill
            c.border = b
            c.font = Font(size=10, name="Calibri")
            c.alignment = Alignment(vertical="center")

        osoby = osoby_map.get(s.get("ico"), [])
        # Rozděl na předsedu, místopředsedu a ostatní
        predseda    = next((o for o in osoby if "předseda" in (o.get("funkce","")).lower() and "místopředs" not in (o.get("funkce","")).lower()), {})
        mistoprds   = next((o for o in osoby if "místopředs" in (o.get("funkce","")).lower()), {})
        ostatni     = [o for o in osoby if o is not predseda and o is not mistoprds if o not in ({}, None)]

        def put(row, col, val):
            c = ws.cell(row=row, column=col, value=val)
            c.border = b
            c.font = Font(size=10, name="Calibri")
            c.alignment = Alignment(vertical="center")
            if fill: c.fill = fill

        # Předseda (sloupce 9, 10)
        put(ri, 9,  predseda.get("jmeno", ""))
        put(ri, 10, predseda.get("datumNarozeni", "") or predseda.get("narozeni", ""))
        # Místopředseda (sloupce 11, 12)
        put(ri, 11, mistoprds.get("jmeno", ""))
        put(ri, 12, mistoprds.get("datumNarozeni", "") or mistoprds.get("narozeni", ""))
        # Ostatní členové dynamicky od sloupce 13
        for i, osoba in enumerate(ostatni):
            cb = 13 + i * 3
            put(ri, cb,   osoba.get("jmeno", ""))
            put(ri, cb+1, osoba.get("funkce", ""))
            put(ri, cb+2, osoba.get("datumNarozeni", "") or osoba.get("narozeni", ""))

    # Šířky sloupců
    for i, w in enumerate([12, 45, 25, 14, 20, 9, 22, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{get_column_letter(total_cols)}{4 + len(data)}"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    fn = f"{label}_{obec.replace(' ', '_')}.xlsx"
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

@app.get("/api/casti")
async def get_casti(obec: str = Query(...), typ: Optional[str] = None):
    """Vrátí unikátní části obce pro danou obec"""
    conn = get_db()
    try:
        q = "SELECT DISTINCT cast_obce FROM subjekty WHERE (obec = ? OR obec LIKE ?) AND cast_obce IS NOT NULL AND cast_obce != obec"
        params = [obec, obec + "-%"]
        if typ:
            q += " AND typ = ?"
            params.append(typ)
        q += " ORDER BY cast_obce"
        rows = conn.execute(q, params).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()

@app.get("/api/ulice")
async def get_ulice(obec: str = Query(...), cast_obce: Optional[str] = None, typ: Optional[str] = None):
    """Vrátí unikátní ulice pro danou obec/část"""
    conn = get_db()
    try:
        q = "SELECT DISTINCT ulice FROM subjekty WHERE (obec = ? OR obec LIKE ?) AND ulice IS NOT NULL"
        params = [obec, obec + "-%"]
        if cast_obce:
            q += " AND cast_obce = ?"
            params.append(cast_obce)
        if typ:
            q += " AND typ = ?"
            params.append(typ)
        q += " ORDER BY ulice"
        rows = conn.execute(q, params).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ===================== SYNC ENDPOINT =====================
import asyncio as _asyncio
import subprocess as _subprocess

_sync_running = False
_sync_status = {"running": False, "progress": "", "done": False, "error": ""}

@app.get("/api/sync/status")
async def sync_status():
    conn = get_db()
    try:
        svj = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='svj'").fetchone()[0]
        bd  = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='bd'").fetchone()[0]
        updated = conn.execute("SELECT MAX(updated_at) FROM subjekty").fetchone()[0]
    finally:
        conn.close()
    return {**_sync_status, "svj": svj, "bd": bd, "posledni_sync": updated}

@app.post("/api/sync/start")
async def sync_start():
    global _sync_running, _sync_status
    if _sync_running:
        return {"ok": False, "msg": "Sync už běží"}
    _sync_running = True
    _sync_status = {"running": True, "progress": "Spouštím sync…", "done": False, "error": "", "pct": 0, "eta": ""}
    _asyncio.create_task(_run_sync())
    return {"ok": True, "msg": "Sync spuštěn"}

async def _run_sync():
    global _sync_running, _sync_status
    import sys, os
    try:
        proc = await _asyncio.create_subprocess_exec(
            sys.executable, "sync_ares.py",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        import re as _re
        last = ""
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            last = line.decode("utf-8", errors="replace").strip()
            if last:
                _sync_status["progress"] = last
                m = _re.search(r"\[(\s*\d+\.?\d*)%\]", last)
                if m:
                    _sync_status["pct"] = float(m.group(1).strip())
                m2 = _re.search(r"~([\dhms ]+)zbyvá", last)
                if m2:
                    _sync_status["eta"] = m2.group(1).strip()
        await proc.wait()
        _sync_status.update({"running": False, "done": True, "progress": "Sync dokončen ✅", "pct": 100, "eta": ""})
    except Exception as e:
        _sync_status = {"running": False, "progress": "", "done": False, "error": str(e)}
    finally:
        _sync_running = False
