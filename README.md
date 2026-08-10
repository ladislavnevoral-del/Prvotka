# RBD Radar v0.3

Nástroj pro vyhledávání obchodních příležitostí mezi SVJ: import subjektů
z OpenData Ministerstva spravedlnosti, stahování listin ze Sbírky listin,
OCR zápisů ze shromáždění a detekce obchodních signálů (zateplení,
revitalizace, fond oprav, zvyšování záloh…) se skórováním leadů.

## Co je nového ve v0.3
- **Jednotný systém signálů** (`app/signal_engine.py`) — sloučeny dřívější
  `scoring.py` (body) a `signals.py` (priority) do jedné sady pravidel;
  detekce je odolná vůči chybějící diakritice z OCR
- **Klient Sbírky listin** (`app/listiny.py`) — najde subjekt podle IČO,
  vypíše listiny, stáhne PDF; šetrný k rate-limitům or.justice.cz
- **Pipeline** (`app/pipeline.py`) — PDF → text (OCR jen u skenů) →
  analýza → uložení dokumentu a signálů do databáze
- **Dashboard** — `http://127.0.0.1:8000/` zobrazuje leady se skóre,
  signály (včetně hodnot jako „fond oprav 28 Kč/m²") a kontextem
- Nahrání PDF ručně přes `POST /api/documents/upload`
- Metadata dokumentu: typ, datum shromáždění, zvolený výbor, příznak OCR

## Instalace (macOS)

```bash
cd "/Users/ladislavnevoral/Downloads/RBD Radar/rbd_radar_v02"
source .venv/bin/activate          # nebo: python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install poppler tesseract tesseract-lang   # pokud ještě nejsou
```

## Spuštění serveru

```bash
python -m uvicorn app.main:app --reload
```

Dashboard: http://127.0.0.1:8000/ · Swagger: http://127.0.0.1:8000/docs

## Typický postup

```bash
# 1) Import SVJ z OpenData (jednorázově / při aktualizaci)
python -m app.import_justice --dataset svj-actual-brno-2026

# 2) Stažení a zpracování listin jednoho SVJ
python -m app.pipeline --ico 3438546 --sync

# 3) Hromadně — SVJ s nejnovějším zápisem v rejstříku napřed
python -m app.pipeline --sync-all --limit 20 --city Brno

# Ruční zpracování staženého PDF
python -m app.pipeline --ico 3438546 --pdf ~/Downloads/zapis.pdf
```

## API
- `GET  /api/leads?min_score=60` — leady seskupené podle SVJ
- `GET  /api/stats`, `GET /api/subjects?city=Brno&search=...`
- `POST /api/documents` — vložení textu dokumentu
- `POST /api/documents/upload` — nahrání PDF (form-data: `ico`, `file`)
- `POST /api/subjects/{ico}/sync-listiny` — stažení nových listin
- `POST /api/import/justice` — import datasetu OpenData

## Denní monitoring (launchd)

Automatické spouštění každý den v 7:30 (jednorázové nastavení):

```bash
chmod +x scripts/daily_sync.sh
cp scripts/com.rbdradar.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.rbdradar.daily.plist
```

Logy: `data/logs/sync-RRRR-MM-DD.log`. Vypnutí:
`launchctl unload ~/Library/LaunchAgents/com.rbdradar.daily.plist`.
Ruční test: `bash scripts/daily_sync.sh`.

## Napojení na Prvotkář

Prvotkář slouží jako celorepublikový zdroj subjektů:

```bash
# import všech SVJ v obci (stránkovaně, ~2000 pro Brno)
python -m app.prvotkar_client --obec "Brno" --limit 200

# konkrétní ulice nebo jednotlivé IČO
python -m app.prvotkar_client --obec "Brno" --ulice "Rybářská"
python -m app.prvotkar_client --ico 3438546
```

API pro opačný směr (Prvotkář čte z Radaru — CORS je povolen):
- `GET /api/leads/{ico}` — skóre a signály jednoho SVJ (pro detail/pin na mapě)
- `GET /api/leads?min_score=60` — seznam leadů
- `POST /api/import/prvotkar` — import obce přes API

## Skórování
Každý signál má **body** (příspěvek do skóre 0–100) a **prioritu**
(řazení pro obchodníka). Úrovně: HOT ≥ 80, HIGH ≥ 60, WATCH ≥ 35, LOW < 35.
Pravidla jsou v `app/signal_engine.py` — přidání nového signálu = nový
záznam v `SIGNAL_RULES`.

Stanovy, prohlášení a účetní závěrky mají skóre děleno třemi a notářské
zápisy dvěma (obsahují obecné právní formulace, ne skutečné záměry).
Po změně pravidel přepočítejte uložené dokumenty:

```bash
python -m app.pipeline --rescore
```

## Nasazení na Render (plně webová verze)

Projekt je připravený jako Render Blueprint (`render.yaml`): webová služba
(Docker s Tesseractem a Popplerem), Postgres databáze a denní cron
synchronizace. Postup:

1. Nahrajte projekt `rbd_radar_v02` do GitHub repozitáře.
2. Na dashboard.render.com zvolte **New → Blueprint** a vyberte repo —
   Render založí službu `rbd-radar`, databázi `rbd-radar-db` i cron
   `rbd-radar-sync` sám podle `render.yaml`.
3. Jednorázově přeneste lokální data (URL najdete u databáze na Renderu
   jako *External Database URL*):

   ```bash
   python scripts/migrate_to_postgres.py "postgresql://…External URL…"
   ```

4. Hotovo — dashboard poběží na `https://rbd-radar.onrender.com/`
   (přesnou adresu ukáže Render; pokud se liší, nastavte ji v Prvotkáři:
   `localStorage.setItem('radarUrl','https://…')`).

Zápisové endpointy (import, sync, upload) jsou na webu chráněné hlavičkou
`X-API-Key` — klíč vygeneruje Render (env `RADAR_API_KEY`, viz záložka
Environment). Čtecí endpointy (`/api/leads…`) zůstávají veřejné, aby je
mohl číst Prvotkář. Lokálně se bez nastaveného `RADAR_API_KEY` klíč
nevyžaduje, vše funguje jako dřív.

Orientační cena: web „starter" + nejmenší Postgres ≈ 14 USD/měsíc
(free web tier má jen 256 MB RAM, což pro OCR nemusí stačit — lze
vyzkoušet změnou `plan: starter` na `plan: free`).

## Poznámky
- or.justice.cz omezuje frekvenci požadavků; klient drží pauzy (3 s)
  a opakuje pokusy. Hromadnou synchronizaci spouštějte po menších dávkách.
- OCR se použije jen tehdy, když PDF nemá textovou vrstvu.
- Testy: `python -m pytest tests/`
