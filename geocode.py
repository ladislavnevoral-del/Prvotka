"""
Prvotkář 3.1 – Geokódování adres přes Nominatim (OpenStreetMap)
Spouští se automaticky po sync_ares.py, nebo ručně: python3 geocode.py
Přidá/aktualizuje sloupce lat, lng v tabulce subjekty.
Pokračuje tam kde skončil (přeskočí záznamy kde lat IS NOT NULL).
"""
import sqlite3, time, sys, urllib.request, urllib.parse, json
from datetime import datetime

DB_FILE      = "prvotkar.db"
NOMINATIM    = "https://nominatim.openstreetmap.org/search"
USER_AGENT   = "Prvotkar/3.1 (prvotkar@example.com)"
DELAY        = 1.1   # Nominatim limit: max 1 req/s
BATCH_COMMIT = 100   # Commit každých N záznamů

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    # Přidej sloupce lat/lng pokud neexistují
    try:
        conn.execute("ALTER TABLE subjekty ADD COLUMN lat REAL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE subjekty ADD COLUMN lng REAL")
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

def geocode(ulice, cp, obec, psc):
    """Geokóduje adresu přes Nominatim. Vrátí (lat, lng) nebo (None, None)."""
    # Sestav adresu od nejpřesnější po nejobecnější
    if ulice and cp:
        q = f"{ulice} {cp}, {obec}, Česká republika"
    elif ulice:
        q = f"{ulice}, {obec}, Česká republika"
    elif psc:
        q = f"{psc} {obec}, Česká republika"
    else:
        q = f"{obec}, Česká republika"

    params = urllib.parse.urlencode({
        "q":              q,
        "format":         "json",
        "limit":          1,
        "countrycodes":   "cz",
        "addressdetails": 0,
    })
    url = f"{NOMINATIM}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None, None

def main():
    print("=" * 60)
    print("Prvotkář 3.1 – Geokódování adres")
    print(f"Spuštěno: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn  = get_db()
    t0    = time.time()

    # Počet záznamů ke geokódování
    total = conn.execute("SELECT COUNT(*) FROM subjekty WHERE lat IS NULL").fetchone()[0]
    done  = conn.execute("SELECT COUNT(*) FROM subjekty WHERE lat IS NOT NULL").fetchone()[0]
    print(f"\nKe geokódování: {total:,} záznamů")
    print(f"Již hotovo:     {done:,} záznamů")

    if total == 0:
        print("\n✅ Vše už je geokódováno!")
        conn.close()
        return

    print(f"\nOdhadovaná doba: {fmt_time(total * DELAY)}")
    print("Nominatim limit: 1 req/s\n")

    rows = conn.execute(
        """SELECT ico, ulice, cislo_popisne, obec, psc
           FROM subjekty
           WHERE lat IS NULL
           ORDER BY obec, ulice"""
    ).fetchall()

    ok_count  = 0
    err_count = 0
    batch     = []

    for i, row in enumerate(rows):
        ico  = row["ico"]
        lat, lng = geocode(
            row["ulice"],
            row["cislo_popisne"],
            row["obec"],
            row["psc"]
        )

        if lat:
            ok_count += 1
            batch.append((lat, lng, ico))
        else:
            err_count += 1
            # Ulož 0,0 jako sentinel aby se nepřeskakoval donekonečna
            batch.append((0.0, 0.0, ico))

        # Commit po dávkách
        if len(batch) >= BATCH_COMMIT:
            conn.executemany(
                "UPDATE subjekty SET lat=?, lng=? WHERE ico=?", batch
            )
            conn.commit()
            batch = []

        # Progress
        elapsed = time.time() - t0
        pct     = (i + 1) / total * 100
        if total > i + 1:
            eta = fmt_time(elapsed / (i + 1) * (total - i - 1))
        else:
            eta = "0s"

        print(
            f"  [{pct:5.1f}%] {i+1:,}/{total:,} | "
            f"OK: {ok_count:,} | Chyba: {err_count:,} | "
            f"~{eta} zbývá | {row['obec'] or '?'[:20]}",
            end="\r", flush=True
        )

        time.sleep(DELAY)

    # Ulož zbytek
    if batch:
        conn.executemany(
            "UPDATE subjekty SET lat=?, lng=? WHERE ico=?", batch
        )
        conn.commit()

    elapsed = time.time() - t0
    print(f"\n\n{'='*60}")
    print(f"GEOKÓDOVÁNÍ DOKONČENO za {fmt_time(elapsed)}")
    print(f"Úspěšně:  {ok_count:,}")
    print(f"Selhalo:  {err_count:,}")
    geo_total = conn.execute("SELECT COUNT(*) FROM subjekty WHERE lat IS NOT NULL AND lat != 0").fetchone()[0]
    print(f"V DB s GPS: {geo_total:,}")
    print("=" * 60)
    conn.close()

if __name__ == "__main__":
    main()
