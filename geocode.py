"""
Prvotkář 3.2 – Geokódování adres přes Nominatim (OpenStreetMap)
Spouští se ručně: python3 geocode.py
P�idá/aktualizuje sloupce lat, lng v tabulce subjekty.
Pokračuje tam kde skončil. Záznamy bez obce označí jako -1.0 (trvalý skip).
"""
import sqlite3, time, json
from datetime import datetime

DB_FILE      = "prvotkar.db"
NOMINATIM    = "https://nominatim.openstreetmap.org/search"
USER_AGENT   = "Prvotkar/3.2 geocoder (info@ippolna.cz)"
DELAY        = 1.5
BATCH_COMMIT = 50

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    for col in ["lat", "lng"]:
        try:
            conn.execute(f"ALTER TABLE subjekty ADD COLUMN {col} REAL")
        except sqlite3.OperationalError:
            pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lat ON subjekty(lat)")
    conn.commit()
    return conn

def fmt_time(sec):
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: return f"{sec//60}m {sec%60}s"
    return f"{sec//3600}h {(sec%3600)//60}m"

def geocode(client, ulice, cp, obec, psc):
    if not obec:
        return None, None
    if ulice and cp:
        q = f"{ulice} {cp}, {obec}, Česká republika"
    elif ulice:
        q = f"{ulice}, {obec}, Česká republika"
    elif psc:
        q = f"{psc} {obec}, Česká republika"
    else:
        q = f"{obec}, Česká republika"
    try:
        r = client.get(NOMINATIM, params={
            "q": q, "format": "json", "limit": 1, "countrycodes": "cz",
        }, timeout=10)
        if r.status_code in (429, 403):
            print(f"\n  ⚠️  Rate limit ({r.status_code}), čekám 60s...")
            time.sleep(60)
            return None, None
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None

def main():
    try:
        import httpx
    except ImportError:
        print("❌ Chybí httpx. Spusť: pip3 install httpx")
        return

    print("=" * 60)
    print("Prvotkář 3.2 – Geokódování adres")
    print(f"Spuštěno: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn = get_db()
    t0   = time.time()

    # -1.0 = trvalý skip (bez obce), NULL nebo 0.0 = ke zpracování
    total = conn.execute(
        "SELECT COUNT(*) FROM subjekty WHERE (lat IS NULL OR lat = 0.0) AND obec IS NOT NULL AND obec != ''"
    ).fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM subjekty WHERE lat IS NOT NULL AND lat != 0.0 AND lat != -1.0"
    ).fetchone()[0]
    skip = conn.execute(
        "SELECT COUNT(*) FROM subjekty WHERE lat = -1.0"
    ).fetchone()[0]

    # Označ záznamy bez obce jako -1.0 (trvalý skip)
    conn.execute("UPDATE subjekty SET lat=-1.0, lng=-1.0 WHERE (lat IS NULL OR lat=0.0) AND (obec IS NULL OR obec='')")
    conn.commit()

    print(f"\nKe geokódování: {total:,} záznamů")
    print(f"Již hotovo:     {done:,} záznamů")
    print(f"Trvalý skip:    {skip:,} záznamů (bez obce)")

    if total == 0:
        print("\n✅ Vše geokódováno!")
        conn.close()
        return

    print(f"\nOdhadovaná doba: {fmt_time(total * DELAY)}")
    print(f"Delay: {DELAY}s mezi requesty\n")

    rows = conn.execute(
        """SELECT ico, ulice, cislo_popisne, obec, psc FROM subjekty
           WHERE (lat IS NULL OR lat = 0.0) AND obec IS NOT NULL AND obec != ''
           ORDER BY obec, ulice"""
    ).fetchall()

    ok_count  = 0
    err_count = 0
    batch     = []

    headers = {
        "User-Agent":      USER_AGENT,
        "Accept":          "application/json",
        "Accept-Language": "cs,en",
        "Referer":         "https://prvotka.onrender.com",
    }

    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for i, row in enumerate(rows):
            ico = row["ico"]
            lat, lng = geocode(client, row["ulice"], row["cislo_popisne"], row["obec"], row["psc"])

            if lat:
                ok_count += 1
                batch.append((lat, lng, ico))
            else:
                err_count += 1
                batch.append((None, None, ico))

            if len(batch) >= BATCH_COMMIT:
                conn.executemany("UPDATE subjekty SET lat=?, lng=? WHERE ico=?", batch)
                conn.commit()
                batch = []

            elapsed    = time.time() - t0
            pct        = (i + 1) / total * 100
            eta        = fmt_time(elapsed / (i + 1) * (total - i - 1)) if i > 0 else "?"
            obec_label = (row["obec"] or "?")[:25]
            print(f"  [{pct:5.1f}%] {i+1:,}/{total:,} | OK: {ok_count:,} | Chyba: {err_count:,} | ~{eta} zbývá | {obec_label}          ",
                  end="\r", flush=True)
            time.sleep(DELAY)

    if batch:
        conn.executemany("UPDATE subjekty SET lat=?, lng=? WHERE ico=?", batch)
        conn.commit()

    geo_total = conn.execute(
        "SELECT COUNT(*) FROM subjekty WHERE lat IS NOT NULL AND lat != 0.0 AND lat != -1.0"
    ).fetchone()[0]
    elapsed = time.time() - t0
    print(f"\n\n{'='*60}")
    print(f"GEOKÓDOVÁNÍ DOKONČENO za {fmt_time(elapsed)}")
    print(f"Úspěšně:    {ok_count:,} | Selhalo: {err_count:,} | V DB s GPS: {geo_total:,}")
    print("=" * 60)
    conn.close()

if __name__ == "__main__":
    main()
