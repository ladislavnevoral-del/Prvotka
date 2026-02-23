from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import sqlite3
import io
import os
import re as _re
import httpx
import uvicorn
import asyncio as _asyncio
import sys

# ======= Konfigurace =======

DB_FILE = os.environ.get("DB_FILE", "/data/prvotkar.db")
print("🗄️ Používám databázi:", DB_FILE)

app = FastAPI(title="Prvotkář 3.1 API")

@app.get("/api/version")
def version():
    return {"version": "3.1", "ok": True}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======= Frontend =======

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home():
    return FileResponse("index.html")

# ======= DB =======

def get_db():
    if not os.path.exists(DB_FILE):
        raise HTTPException(status_code=503, detail="Databáze nenalezena. Spusť Sync DB.")
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    return conn

def row_to_dict(row):
    return dict(row)

# ======= Upload DB (pro Render - nahraj prvotkar.db přes API) =======

@app.post("/api/upload-db")
async def upload_db(file: UploadFile = File(...)):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    content = await file.read()
    with open(DB_FILE, "wb") as f:
        f.write(content)
    return {"ok": True, "msg": f"Databáze uložena ({len(content):,} bytes)", "size": len(content)}

# ======= Stats =======

@app.get("/api/stats")
async def get_stats():
    if not os.path.exists(DB_FILE):
        return {"svj": 0, "bd": 0, "celkem": 0, "posledni_sync": None}
    conn = sqlite3.connect(DB_FILE)
    try:
        svj     = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='svj'").fetchone()[0]
        bd      = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='bd'").fetchone()[0]
        updated = conn.execute("SELECT MAX(updated_at) FROM subjekty").fetchone()[0]
        return {"svj": svj, "bd": bd, "celkem": svj + bd, "posledni_sync": updated}
    finally:
        conn.close()

# ======= API =======

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
    pocet: int = 2000,
):
    conn = get_db()
    try:
        params  = [obec, obec + "-%", typ]
        filters = "(obec = ? OR obec LIKE ?) AND typ = ?"
        if cast_obce:
            filters += " AND cast_obce = ?"
            params.append(cast_obce)
        if ulice:
            filters += " AND ulice = ?"
            params.append(ulice)
        all_rows = conn.execute(
            f"SELECT * FROM subjekty WHERE {filters} ORDER BY nazev", params
        ).fetchall()
        celkem = len(all_rows)
        page   = all_rows[start:start + pocet]
        subjekty = []
        for r in page:
            d = row_to_dict(r)
            subjekty.append({
                "ico":           d["ico"],
                "obchodniJmeno": d["nazev"],
                "stavSubjektu":  d["stav"],
                "datumVzniku":   d["datum_vzniku"],
                "sidlo": {
                    "nazevObce":      d["obec"],
                    "nazevCastiObce": d["cast_obce"],
                    "nazevUlice":     d["ulice"],
                    "cisloDomovni":   d["cislo_popisne"],
                    "cisloOrientacni":d["cislo_orientacni"],
                    "psc":            d["psc"],
                    "nazevKraje":     d["kraj"],
                }
            })
        return {"celkem": celkem, "subjekty": subjekty}
    finally:
        conn.close()

@app.get("/api/casti")
async def get_casti(obec: str = Query(...), typ: Optional[str] = None):
    conn = get_db()
    try:
        q      = "SELECT DISTINCT cast_obce FROM subjekty WHERE (obec = ? OR obec LIKE ?) AND cast_obce IS NOT NULL AND cast_obce != obec"
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
    conn = get_db()
    try:
        q      = "SELECT DISTINCT ulice FROM subjekty WHERE (obec = ? OR obec LIKE ?) AND ulice IS NOT NULL"
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

# ======= Detail s osobami z ARES VR =======

def _parse_osoby_vr(vr_json: dict) -> list:
    """Parsuje aktivní členy výboru z ekonomicke-subjekty-vr response."""
    osoby = []
    seen  = set()
    for zaznam in vr_json.get("zaznamy", []):
        for org in zaznam.get("statutarniOrgany", []):
            for clen in org.get("clenoveOrganu", []):
                if clen.get("datumVymazu"):
                    continue
                clenstvi    = clen.get("clenstvi", {})
                funkce_info = clenstvi.get("funkce", {})
                if funkce_info.get("zanikFunkce"):
                    continue
                # Fyzická osoba přímo
                fo = clen.get("fyzickaOsoba")
                # Nebo zástupce právnické osoby
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
                    fo.get("prijmeni", ""),
                ])).strip()
                if fo.get("titulZaJmenem"):
                    jmeno += ", " + fo["titulZaJmenem"]
                narozeni = fo.get("datumNarozeni", "")
                key      = f"{jmeno}|{narozeni}"
                if not jmeno or key in seen:
                    continue
                seen.add(key)
                osoby.append({
                    "jmeno":         jmeno,
                    "datumNarozeni": narozeni,
                    "funkce":        funkce_info.get("nazev", "člen výboru"),
                })
    return osoby

@app.get("/api/svj/{ico}/detail")
async def get_svj_detail(ico: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM subjekty WHERE ico = ?", [ico]).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Subjekt nenalezen")
    d = row_to_dict(row)

    base = {
        "ico":    d["ico"],
        "nazev":  d["nazev"],
        "sidlo": {
            "nazevObce":       d["obec"],
            "nazevCastiObce":  d["cast_obce"],
            "nazevUlice":      d["ulice"],
            "cisloDomovni":    d["cislo_popisne"],
            "cisloOrientacni": d["cislo_orientacni"],
            "psc":             d["psc"],
            "nazevKraje":      d["kraj"],
        },
        "datumVzniku":   d["datum_vzniku"],
        "stavSubjektu":  d["stav"],
        "osoby":         [],
        "spisovaZnacka": None,
        "subjektId":     None,
    }

    # Načti živá data z ARES VR (osoby + spisovaZnacka + subjektId)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Osoby + spisová značka z VR endpointu
            r = await client.get(
                f"https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/{ico}"
            )
            if r.status_code == 200:
                vr = r.json()
                base["osoby"] = _parse_osoby_vr(vr)
                for zaznam in vr.get("zaznamy", []):
                    for sz in zaznam.get("spisovaZnacka", []):
                        soud   = sz.get("soud", "")
                        oddil  = sz.get("oddil", "")
                        vlozka = sz.get("vlozka", "")
                        if oddil and vlozka:
                            base["spisovaZnacka"] = f"{oddil} {vlozka}/{soud}"
                            break

            # subjektId z Justice.cz pro přímé odkazy
            r2 = await client.get(
                f"https://or.justice.cz/ias/ui/rejstrik-$firma?ico={ico}&jenPlatne=PLATNE",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8
            )
            if r2.status_code == 200:
                ids = _re.findall(r"subjektId[=:](\d+)", r2.text)
                if ids:
                    base["subjektId"] = ids[0]
    except Exception:
        pass

    return base

# ======= Export Excel s osobami =======

@app.get("/api/export/excel")
async def export_excel(
    obec: str = Query(...),
    ulice: Optional[str] = None,
    cast_obce: Optional[str] = None,
    typ: Optional[str] = "svj",
):
    result = await get_svj(obec=obec, ulice=ulice, cast_obce=cast_obce, typ=typ, start=0, pocet=9999)
    data   = result["subjekty"]
    label  = "BD" if typ == "bd" else "SVJ"

    # Stáhni osoby pro prvních 150 záznamů (ARES throttling)
    MAX_OSOBY  = 150
    ico_list   = [s.get("ico") for s in data[:MAX_OSOBY] if s.get("ico")]
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

    # Spočítej max ostatních členů (kromě předsedy a místopředsedy)
    def get_ostatni(osoby):
        return [o for o in osoby
                if "předseda" not in (o.get("funkce") or "").lower()]

    max_ostatni = max(
        (len(get_ostatni(v)) for v in osoby_map.values()),
        default=0
    )

    # Styly
    hf  = PatternFill(start_color="1B4F72", end_color="1B4F72", fill_type="solid")
    hf2 = PatternFill(start_color="2E4057", end_color="2E4057", fill_type="solid")
    af  = PatternFill(start_color="EBF5FB", end_color="EBF5FB", fill_type="solid")
    b   = Border(
        left=Side(style="thin", color="BDC3C7"),
        right=Side(style="thin", color="BDC3C7"),
        top=Side(style="thin", color="BDC3C7"),
        bottom=Side(style="thin", color="BDC3C7"),
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Seznam"

    # Záhlaví - titulní řádky
    base_headers = [
        "IČO", f"Název {label}", "Ulice", "ČP/CO", "Obec", "PSČ", "Kraj", "Rok vzniku",
        "Předseda – jméno", "Předseda – narozen",
        "Místopředseda – jméno", "Místopředseda – narozen",
    ]
    total_cols = len(base_headers) + max_ostatni * 3

    ws.merge_cells(f"A1:{get_column_letter(total_cols)}1")
    ws["A1"].value     = f"Seznam {label} – {obec}" + (f" / {ulice}" if ulice else "")
    ws["A1"].font      = Font(bold=True, size=14, name="Calibri", color="1B4F72")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells(f"A2:{get_column_letter(total_cols)}2")
    ws["A2"].value     = f"Celkem: {len(data)} záznamů | Zdroj: ARES | Výbor: živá data ARES VR (prvních {MAX_OSOBY})"
    ws["A2"].font      = Font(italic=True, size=10, color="7F8C8D", name="Calibri")
    ws["A2"].alignment = Alignment(horizontal="center")

    # Záhlaví sloupců
    for col, hdr in enumerate(base_headers, 1):
        c           = ws.cell(row=4, column=col, value=hdr)
        c.fill      = hf if col <= 8 else hf2
        c.font      = Font(color="FFFFFF", bold=True, size=10, name="Calibri")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border    = b

    for i in range(max_ostatni):
        cb = len(base_headers) + 1 + i * 3
        for off, hdr in enumerate([f"Člen {i+1} – jméno", f"Člen {i+1} – funkce", f"Člen {i+1} – narozen"]):
            c           = ws.cell(row=4, column=cb + off, value=hdr)
            c.fill      = hf2
            c.font      = Font(color="FFFFFF", bold=True, size=10, name="Calibri")
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border    = b
    ws.row_dimensions[4].height = 30

    # Data
    for ri, s in enumerate(data, 5):
        sidlo  = s.get("sidlo") or {}
        cp     = str(sidlo.get("cisloDomovni") or "")
        co     = sidlo.get("cisloOrientacni") or ""
        cislo  = cp + ("/" + str(co) if co else "")
        rok    = (s.get("datumVzniku") or "")[:4]
        fill   = af if (ri - 5) % 2 == 1 else None

        base_vals = [
            s.get("ico"), s.get("obchodniJmeno"),
            sidlo.get("nazevUlice"), cislo,
            sidlo.get("nazevObce"), sidlo.get("psc"),
            sidlo.get("nazevKraje"), rok,
        ]
        for col, val in enumerate(base_vals, 1):
            c           = ws.cell(row=ri, column=col, value=val)
            c.font      = Font(size=10, name="Calibri")
            c.alignment = Alignment(vertical="center")
            c.border    = b
            if fill: c.fill = fill

        # Výbor
        ico    = s.get("ico", "")
        osoby  = osoby_map.get(ico, [])
        predseda   = next((o for o in osoby if "předseda" in (o.get("funkce") or "").lower() and "místopředs" not in (o.get("funkce") or "").lower()), {})
        mistoprds  = next((o for o in osoby if "místopředs" in (o.get("funkce") or "").lower()), {})
        ostatni    = [o for o in osoby if o is not predseda and o is not mistoprds]

        def put(row, col, val):
            c           = ws.cell(row=row, column=col, value=val)
            c.font      = Font(size=10, name="Calibri")
            c.alignment = Alignment(vertical="center")
            c.border    = b
            if fill: c.fill = fill

        put(ri, 9,  predseda.get("jmeno", ""))
        put(ri, 10, predseda.get("datumNarozeni", ""))
        put(ri, 11, mistoprds.get("jmeno", ""))
        put(ri, 12, mistoprds.get("datumNarozeni", ""))

        for i, osoba in enumerate(ostatni):
            cb = len(base_headers) + 1 + i * 3
            put(ri, cb,     osoba.get("jmeno", ""))
            put(ri, cb + 1, osoba.get("funkce", ""))
            put(ri, cb + 2, osoba.get("datumNarozeni", ""))

    # Šířky sloupců
    for i, w in enumerate([12, 45, 22, 10, 18, 8, 20, 8, 28, 13, 28, 13], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for i in range(max_ostatni):
        cb = len(base_headers) + 1 + i * 3
        ws.column_dimensions[get_column_letter(cb)].width     = 25
        ws.column_dimensions[get_column_letter(cb + 1)].width = 18
        ws.column_dimensions[get_column_letter(cb + 2)].width = 13

    ws.freeze_panes = "A5"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    fn = f"{label}_{obec.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{fn}\""}
    )

# ======= SYNC =======

_sync_running = False
_sync_status  = {"running": False, "progress": "", "done": False, "error": "", "pct": 0, "eta": ""}

@app.get("/api/sync/status")
async def sync_status():
    if not os.path.exists(DB_FILE):
        return {**_sync_status, "svj": 0, "bd": 0, "posledni_sync": None}
    conn = sqlite3.connect(DB_FILE)
    try:
        svj     = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='svj'").fetchone()[0]
        bd      = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='bd'").fetchone()[0]
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
    _sync_status  = {"running": True, "progress": "Spouštím sync…", "done": False, "error": "", "pct": 0, "eta": ""}
    _asyncio.create_task(_run_sync())
    return {"ok": True, "msg": "Sync spuštěn"}

async def _run_sync():
    global _sync_running, _sync_status
    try:
        proc = await _asyncio.create_subprocess_exec(
            sys.executable, "sync_ares.py",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
        )
        last = ""
        async for line in proc.stdout:
            txt = line.decode("utf-8", errors="replace").strip()
            if not txt:
                continue
            last = txt
            _sync_status["progress"] = txt
            # Parsuj % progress
            m = _re.search(r"\[(\s*\d+\.?\d*)%\]", txt)
            if m:
                _sync_status["pct"] = float(m.group(1).strip())
            # Parsuj ETA
            m2 = _re.search(r"~([\dhms ]+)zbyvá", txt)
            if m2:
                _sync_status["eta"] = m2.group(1).strip()
        await proc.wait()
        _sync_status.update({"running": False, "done": True, "progress": "Sync dokončen ✅", "pct": 100, "eta": ""})
    except Exception as e:
        _sync_status.update({"running": False, "done": False, "error": str(e)})
    finally:
        _sync_running = False

# ======= Run =======

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
