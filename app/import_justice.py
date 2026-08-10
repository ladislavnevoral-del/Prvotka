import argparse
import csv
from pathlib import Path
from sqlalchemy import select

from .db import init_db, SessionLocal
from .models import Subject
from .justice_client import JusticeClient
from .justice_parser import parse_udaje

def import_dataset(dataset: str, limit: int | None = None):
    init_db()
    Path("data/cache").mkdir(parents=True, exist_ok=True)

    client = JusticeClient()
    url = client.csv_url(dataset)
    target = Path("data/cache") / f"{dataset}.csv"

    print(f"Dataset: {dataset}")
    print(f"CSV: {url}")
    print("Stahuji...")
    client.download(url, target)
    print(f"Staženo: {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")

    db = SessionLocal()
    inserted = updated = skipped = errors = 0

    try:
        with open(target, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row_no, row in enumerate(reader, start=1):
                if limit and row_no > limit:
                    break

                try:
                    ico = (row.get("ico") or "").strip()
                    name = (row.get("nazev") or "").strip()
                    udaje = row.get("udaje") or ""
                    if not ico or not name:
                        skipped += 1
                        continue

                    parsed = parse_udaje(udaje)
                    subject = db.scalar(select(Subject).where(Subject.ico == ico))

                    if subject is None:
                        subject = Subject(
                            ico=ico,
                            name=name,
                            legal_form="Společenství vlastníků jednotek",
                            source_url="https://or.justice.cz/ias/ui/rejstrik",
                            source_dataset=dataset,
                        )
                        db.add(subject)
                        inserted += 1
                    else:
                        updated += 1

                    subject.name = name
                    subject.address = parsed["address"]
                    subject.court = parsed["court"]
                    subject.file_number = parsed["file_number"]
                    subject.city = parsed["city"]
                    subject.street = parsed["street"]
                    subject.house_number = parsed["house_number"]
                    subject.zip_code = parsed["zip_code"]
                    subject.last_entry_date = parsed["last_entry_date"]
                    subject.source_dataset = dataset

                    if row_no % 500 == 0:
                        db.commit()
                        print(f"Zpracováno: {row_no:,} | nové: {inserted:,} | aktualizované: {updated:,}")

                except Exception as exc:
                    errors += 1
                    if errors <= 10:
                        print(f"CHYBA řádek {row_no}: {exc}")

            db.commit()
    finally:
        db.close()

    print()
    print("IMPORT HOTOV")
    print(f"Zpracováno: {row_no:,}")
    print(f"Nové:       {inserted:,}")
    print(f"Aktualizované: {updated:,}")
    print(f"Přeskočené: {skipped:,}")
    print(f"Chyby:      {errors:,}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="svj-actual-brno-2026")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    import_dataset(args.dataset, args.limit)
