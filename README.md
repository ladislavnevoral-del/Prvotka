# Prvotkář 3.2 – IP Polná

SVJ & BD vyhledávač pro celou Českou republiku.

## Instalace na server

### Požadavky
- Python 3.10+
- pip

### Kroky

```bash
# 1. Nainstaluj závislosti
pip install -r requirements.txt

# 2. Stáhni databázi z ARES (~3-5 hodin)
python3 sync_ares.py

# 3. (Volitelně) Geokóduj adresy pro mapové zobrazení (~24 hodin)
python3 geocode.py

# 4. Spusť server
python3 main.py
# nebo přes uvicorn přímo:
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Porty a proměnné prostředí
- `PORT` – port serveru (výchozí: 8000)
- Server naslouchá na `0.0.0.0` – přístupný z lokální sítě

### Soubory
| Soubor | Popis |
|---|---|
| `main.py` | FastAPI backend, REST API |
| `sync_ares.py` | Stažení dat z ARES (spustit jednou) |
| `geocode.py` | Geokódování adres pro mapy |
| `index.html` | Frontend (SPA) |
| `prvotkar.db` | SQLite databáze (vznikne po syncu) |

### API endpointy
| Endpoint | Popis |
|---|---|
| `GET /api/ping` | Keep-alive / monitoring |
| `GET /api/version` | Verze aplikace |
| `GET /api/svj?obec=Brno&typ=svj` | Seznam SVJ/BD |
| `GET /api/ico/{ico}` | Vyhledání podle IČO |
| `GET /api/svj/{ico}/detail` | Detail + výbor z ARES VR |
| `GET /api/hledat?q=text` | Fulltext vyhledávání |
| `GET /api/export/excel?obec=Brno` | Export do .xlsx |
| `POST /api/sync/start` | Spustit sync ARES |
| `GET /api/sync/status` | Stav syncu + statistiky DB |

### Monitoring (doporučeno)
Zaregistruj `/api/ping` na UptimeRobot.com (zdarma) – zabrání uspání serveru na Render.com.

### Aktualizace dat
Data z ARES jsou platná cca 3-6 měsíců. Sync spusť znovu přes UI (tlačítko Sync DB) nebo ručně.
