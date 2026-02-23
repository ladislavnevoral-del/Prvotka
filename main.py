from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import io
import os
import shutil
import httpx
DB_FILE = "/data/prvotkar.db"

# Pokud DB na persistentním disku neexistuje, zkopíruj ji z repozitáře
if not os.path.exists(DB_FILE):
    if os.path.exists("prvotkar.db"):
        print("📦 Kopíruji prvotkar.db na persistentní disk /data ...")
        os.makedirs("/data", exist_ok=True)
        shutil.copy("prvotkar.db", DB_FILE)
    else:
        print("⚠️ Lokální prvotkar.db nenalezena, DB se vytvoří až při syncu")
from typing import Optional
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import uvicorn
import asyncio as _asyncio
import sys

app = FastAPI(title="Prvotkář 3.0 API")

# ======= Frontend =======
# Pokud nemáš složku static/, klidně tenhle řádek smaž
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def home():
    return FileResponse("index.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======= DB =======
DB_FILE = "/data/prvotkar.db"
print("🗄️ Používám databázi:", DB_FILE)

def get_db():
    if not os.path.exists(DB_FILE):
        raise HTTPException(
            status_code=503,
            detail="Databáze nenalezena. Spusť Sync DB."
        )
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def row_to_dict(row):
    return dict(row)

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
    pocet: int = 200,
):
    conn = get_db()
    try:
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
            subjekty.append({
                "ico": d["ico"],
                "obchodniJmeno": d["nazev"],
                "stavSubjektu": d["stav"],
                "datumVzniku": d["datum_vzniku"],
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

@app.get("/api/casti")
async def get_casti(obec: str = Query(...), typ: Optional[str] = None):
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
    return {
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

# ======= Export Excel =======

@app.get("/api/export/excel")
async def export_excel(
    obec: str = Query(...),
    ulice: Optional[str] = None,
    cast_obce: Optional[str] = None,
    typ: Optional[str] = "svj",
):
    result = await get_svj(obec=obec, ulice=ulice, cast_obce=cast_obce, typ=typ, start=0, pocet=9999)
    data = result["subjekty"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Seznam"
    ws.append(["IČO", "Název", "Ulice", "ČP/CO", "Obec", "PSČ", "Kraj", "Rok vzniku"])

    for s in data:
        sidlo = s.get("sidlo") or {}
        cp = str(sidlo.get("cisloDomovni") or "")
        co = sidlo.get("cisloOrientacni") or ""
        cislo = cp + ("/" + str(co) if co else "")
        rok = (s.get("datumVzniku") or "")[:4]
        ws.append([
            s.get("ico"), s.get("obchodniJmeno"),
            sidlo.get("nazevUlice"), cislo,
            sidlo.get("nazevObce"), sidlo.get("psc"),
            sidlo.get("nazevKraje"), rok
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    fn = f"export_{obec.replace(' ', '_')}.xlsx"
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"})

# ======= SYNC =======

_sync_running = False
_sync_status = {"running": False, "progress": "", "done": False, "error": "", "pct": 0, "eta": ""}

@app.get("/api/sync/status")
async def sync_status():
    if not os.path.exists(DB_FILE):
        return {**_sync_status, "svj": 0, "bd": 0, "posledni_sync": None}

    conn = sqlite3.connect(DB_FILE)
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
    try:
        proc = await _asyncio.create_subprocess_exec(
            sys.executable, "sync_ares.py",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
        )
        last = ""
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            last = line.decode("utf-8", errors="replace").strip()
            if last:
                _sync_status["progress"] = last
        await proc.wait()
        _sync_status = {"running": False, "progress": last, "done": True, "error": ""}
    except Exception as e:
        _sync_status = {"running": False, "progress": "", "done": False, "error": str(e)}
    finally:
        _sync_running = False

# ======= Run local =======

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)