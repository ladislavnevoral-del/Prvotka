# Návod na nasazení Prvotkář 3.0 na web (Render.com + GitHub)

## Co potřebuješ
- Účet na github.com ✅
- Účet na render.com ✅

---

## KROK 1 — Vytvoř repozitář na GitHubu

1. Otevři https://github.com/new
2. **Repository name:** `prvotkar` 
3. Nastav na **Private** (doporučeno)
4. Klikni **Create repository**

---

## KROK 2 — Nahraj soubory na GitHub

Otevři Terminál a spusť tyto příkazy **jeden po druhém**:

```bash
cd ~/Prvotkar
git init
git add index.html main.py sync_ares.py requirements.txt start.py render.yaml .gitignore
git commit -m "Prvotkář 3.0 - první verze"
git branch -M main
```

Pak na GitHubu zkopíruj URL svého repozitáře (vypadá jako: https://github.com/TVOJE_JMENO/prvotkar.git)
a spusť:

```bash
git remote add origin https://github.com/TVOJE_JMENO/prvotkar.git
git push -u origin main
```

GitHub tě požádá o jméno a heslo (nebo token).

---

## KROK 3 — Nasaď na Render.com

1. Otevři https://dashboard.render.com
2. Klikni **New → Web Service**
3. Vyber **Connect a GitHub repository** → vyber `prvotkar`
4. Nastav:
   - **Name:** `prvotkar`
   - **Region:** `Frankfurt (EU Central)` 
   - **Branch:** `main`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python start.py`
5. **Instance Type:** vyber **Free**
6. Klikni **Create Web Service**

---

## KROK 4 — Počkej na první spuštění

Render automaticky:
1. Nainstaluje závislosti (~2 min)
2. Spustí `start.py` který stáhne databázi z ARES (~20 min)
3. Spustí backend

Průběh vidíš v záložce **Logs** na Render.com.

Po dokončení dostaneš URL ve tvaru: `https://prvotkar.onrender.com`

---

## Jak funguje aktualizace databáze

- Databáze se automaticky obnoví při každém restartu serveru pokud je starší 7 dní
- Na free plánu Render.com se server restartuje každých 24 hodin (po 15 minutách nečinnosti)
- Takže databáze bude vždy max. 7 dní stará

---

## Upozornění k free plánu Render.com

- Free plán "usne" po 15 minutách bez návštěvy
- První načtení po probuzení trvá ~30 sekund
- Pro veřejný nástroj doporučuji Starter plán ($7/měsíc) — server nikdy nespí

