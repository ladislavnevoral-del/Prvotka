"""
Spouštěcí skript pro Render.com
Při prvním spuštění (nebo pokud chybí DB) spustí sync, pak backend.
"""
import os, asyncio, subprocess, sys

DB_FILE = "prvotkar.db"

async def main():
    # Spusť sync pokud DB chybí nebo je starší než 7 dní
    run_sync = False
    if not os.path.exists(DB_FILE):
        print("📦 Databáze nenalezena – spouštím sync...")
        run_sync = True
    else:
        import time
        age_days = (time.time() - os.path.getmtime(DB_FILE)) / 86400
        if age_days > 7:
            print(f"📦 Databáze stará {age_days:.1f} dní – spouštím sync...")
            run_sync = True

    if run_sync:
        proc = await asyncio.create_subprocess_exec(sys.executable, "sync_ares.py")
        await proc.wait()
        print("✅ Sync dokončen")

    # Spusť backend
    port = os.environ.get("PORT", "8000")
    print(f"🚀 Spouštím backend na portu {port}")
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "main:app",
                               "--host", "0.0.0.0", "--port", port])

asyncio.run(main())
