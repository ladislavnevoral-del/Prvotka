"""
Prvotkář 3.0 – Kompletní sync SVJ a BD z ARES
Strategie: RUIAN API -> všechny obce ČR -> ARES kodObce filtr
Pokryje všech ~79 873 SVJ a ~8 400 BD
"""
import sqlite3, json, time, sys, urllib.request, urllib.error
from datetime import datetime

DB_FILE      = "prvotkar.db"
ARES_URL     = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat"
RUIAN_BASE   = "https://ruian.fnx.io/api/v1/ruian/build"
RUIAN_KEY    = "cec9c90b443c5f6243ea6b2d878b4e5cbe0c8271c28cfb890de7a585595f6999"
PRAVNI_FORMY = {"svj": "145", "bd": "205"}  # 205 = Bytová a stavební bytová družstva (112 = s.r.o. – chyba!)

# ── DB ───────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS subjekty (
        ico TEXT PRIMARY KEY, typ TEXT, nazev TEXT,
        kraj TEXT, kraj_kod TEXT, obec TEXT, cast_obce TEXT,
        ulice TEXT, cislo_popisne TEXT, cislo_orientacni TEXT,
        psc TEXT, datum_vzniku TEXT, stav TEXT, updated_at TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_obec   ON subjekty(obec)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_typ    ON subjekty(typ)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cast   ON subjekty(cast_obce)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ulice  ON subjekty(ulice)")
    conn.commit()
    return conn

# ── HTTP ─────────────────────────────────────────────────────────────────────

def http_get(url, retries=3):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            if attempt < retries - 1:
                time.sleep(3)
    return None

def ares_post(payload, retries=3):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        ARES_URL, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("\n  Rate limit ARES, čekám 30s...")
                time.sleep(30)
            else:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(5)
    return None

# ── RUIAN: seznam všech obcí ─────────────────────────────────────────────────

def get_vsechny_obce():
    print("  Načítám seznam krajů z RUIAN...")
    regions_data = http_get(f"{RUIAN_BASE}/regions?apiKey={RUIAN_KEY}")
    if not regions_data:
        print("  ❌ RUIAN nedostupný, použiju záložní seznam")
        return _zaloha_obce()

    regions = regions_data.get("data", [])
    print(f"  Nalezeno {len(regions)} krajů")

    obce = {}  # municipalityId -> municipalityName
    for reg in regions:
        rid  = reg["regionId"]
        rnam = reg["regionName"]
        url  = f"{RUIAN_BASE}/municipalities?apiKey={RUIAN_KEY}&regionId={rid}"
        data = http_get(url)
        if data:
            muns = data.get("data", [])
            for m in muns:
                obce[m["municipalityId"]] = m["municipalityName"]
            print(f"    {rnam}: {len(muns)} obcí (celkem {len(obce)})")
        time.sleep(0.3)

    print(f"  ✅ Celkem {len(obce)} obcí ČR")
    return obce

def _zaloha_obce():
    """Minimální záloha pokud RUIAN selže."""
    return {
        554782: "Praha", 582786: "Brno", 554821: "Ostrava",
        554791: "Plzeň", 544973: "České Budějovice", 569810: "Liberec",
        569925: "Olomouc", 574490: "Hradec Králové", 555134: "Pardubice",
        585068: "Zlín", 555771: "Kladno", 567985: "Most",
        510266: "Opava", 598003: "Jihlava", 573868: "Teplice",
        598909: "Karlovy Vary", 560286: "Ústí nad Labem",
    }

# ── Pomocné funkce ────────────────────────────────────────────────────────────

def fmt_time(sec):
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: return f"{sec//60}m {sec%60}s"
    return f"{sec//3600}h {(sec%3600)//60}m"

def print_progress(i, total, n_zaz, t0, label):
    elapsed = time.time() - t0
    pct     = i / total * 100 if total else 0
    if i > 0:
        eta   = fmt_time(elapsed / i * (total - i))
        speed = int(i / elapsed * 60) if elapsed > 1 else 0
        line  = (f"  [{pct:5.1f}%] {i}/{total} obci | "
                 f"{n_zaz:,} zaznamu | ~{eta} zbyvá | "
                 f"{speed} obci/min | {label[:28]}")
    else:
        line  = f"  [  0.0%] 0/{total} obci | spoustim..."
    print(line, end="\r", flush=True)

# ── Uložení do DB ─────────────────────────────────────────────────────────────

def uloz_batch(conn, typ, subjekty):
    rows = []
    for s in subjekty:
        sidlo = s.get("sidlo", {})
        rows.append((
            s.get("ico", ""), typ,
            s.get("obchodniJmeno"),
            sidlo.get("nazevKraje"),
            str(sidlo.get("kodKraje", "") or ""),
            sidlo.get("nazevObce"),
            sidlo.get("nazevCastiObce"),
            sidlo.get("nazevUlice"),
            str(sidlo.get("cisloDomovni",    "") or ""),
            str(sidlo.get("cisloOrientacni", "") or ""),
            str(sidlo.get("psc",             "") or ""),
            (s.get("datumVzniku") or "")[:10] or None,
            s.get("stavSubjektu"),
            datetime.now().isoformat()
        ))
    if rows:
        conn.executemany("""
            INSERT OR REPLACE INTO subjekty
            (ico,typ,nazev,kraj,kraj_kod,obec,cast_obce,ulice,
             cislo_popisne,cislo_orientacni,psc,datum_vzniku,stav,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()

# ── Sync jedné obce ───────────────────────────────────────────────────────────

def sync_obec(conn, typ, kod_pf, kod_obce, nazev_obce):
    start  = 0
    celkem = 0
    while True:
        d = ares_post({
            "pravniForma": [kod_pf],
            "sidlo": {"kodObce": kod_obce},
            "start": start,
            "pocet": 1000
        })
        if not d:
            break
        if d.get("subKod") == "VYSTUP_PRILIS_MNOHO_VYSLEDKU":
            # Příliš mnoho – rozděl po písmenech názvu
            celkem += sync_obec_po_pismenech(conn, typ, kod_pf, kod_obce)
            return celkem
        subjekty = d.get("ekonomickeSubjekty", [])
        if not subjekty:
            break
        uloz_batch(conn, typ, subjekty)
        celkem += len(subjekty)
        if len(subjekty) < 1000:
            break
        start += 1000
        time.sleep(0.2)
    return celkem

def sync_obec_po_pismenech(conn, typ, kod_pf, kod_obce):
    """Fallback pro velká města (Praha, Brno…) – kombinuje kodObce + prefix."""
    celkem = 0
    znaky  = "ABCČDĎEÉĚFGHIÍJKLMNŇOÓPQRŘSŠTŤUÚŮVWXYÝZŽ0123456789"
    for z in znaky:
        start = 0
        while True:
            d = ares_post({
                "obchodniJmeno": z,
                "pravniForma":   [kod_pf],
                "sidlo":         {"kodObce": kod_obce},
                "start":         start,
                "pocet":         1000
            })
            if not d or d.get("subKod") == "VYSTUP_PRILIS_MNOHO_VYSLEDKU":
                break
            subjekty = d.get("ekonomickeSubjekty", [])
            if not subjekty:
                break
            uloz_batch(conn, typ, subjekty)
            celkem += len(subjekty)
            if len(subjekty) < 1000:
                break
            start += 1000
            time.sleep(0.15)
    return celkem

# ── Sync všech obcí ───────────────────────────────────────────────────────────

def sync_vsechny_obce(conn, typ, kod_pf, obce):
    print(f"\n{'='*60}")
    print(f"  Sync {typ.upper()} (pravniForma={kod_pf}) – {len(obce)} obcí")
    print(f"{'='*60}\n")

    obce_list = list(obce.items())
    n_obci    = len(obce_list)
    total     = 0
    t0        = time.time()

    for i, (kod_obce, nazev_obce) in enumerate(obce_list):
        print_progress(i, n_obci, total, t0, nazev_obce)
        total += sync_obec(conn, typ, kod_pf, kod_obce, nazev_obce)
        time.sleep(0.12)

    elapsed = time.time() - t0
    print(f"\n  [100.0%] {n_obci}/{n_obci} obci | "
          f"{total:,} zaznamu | hotovo za {fmt_time(elapsed)}          ")
    return total

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Prvotkář 3.1 – Kompletní ARES sync")
    print(f"Spuštěno: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn  = get_db()
    t_cel = time.time()

    # 1. Stáhni seznam všech obcí ČR z RUIAN
    print("\nFáze 1: Načítám seznam obcí ČR z RUIAN...")
    obce = get_vsechny_obce()
    print(f"Celkem obcí ke zpracování: {len(obce):,}\n")

    # 2. Sync SVJ
    n_svj = sync_vsechny_obce(conn, "svj", PRAVNI_FORMY["svj"], obce)
    svj_db = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='svj'").fetchone()[0]
    print(f"\n✅ SVJ: staženo {n_svj:,} | v DB celkem {svj_db:,}")

    # 3. Sync BD
    n_bd = sync_vsechny_obce(conn, "bd", PRAVNI_FORMY["bd"], obce)
    bd_db = conn.execute("SELECT COUNT(*) FROM subjekty WHERE typ='bd'").fetchone()[0]
    print(f"\n✅ BD:  staženo {n_bd:,} | v DB celkem {bd_db:,}")

    elapsed = int(time.time() - t_cel)
    print(f"\n{'='*60}")
    print(f"SYNC DOKONČEN za {fmt_time(elapsed)}")
    print(f"SVJ v DB:  {svj_db:,}")
    print(f"BD v DB:   {bd_db:,}")
    print(f"Celkem:    {svj_db+bd_db:,}")
    print("=" * 60)
    conn.close()

    # Fáze 4: Geokódování nových adres
    print("\n" + "=" * 60)
    print("Fáze 4: Spouštím geokódování nových adres...")
    print("(lze přerušit Ctrl+C, pokračuje při příštím spuštění)")
    print("=" * 60)
    try:
        import geocode as _geo
        _geo.main()
    except KeyboardInterrupt:
        print("\nGeokódování přerušeno – dokončíš při příštím syncu.")
    except Exception as e:
        print(f"\nChyba geokódování: {e}")

if __name__ == "__main__":
    main()
