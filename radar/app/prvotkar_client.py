"""Napojení na Prvotkář (https://prvotkar-backend.onrender.com).

Prvotkář má celorepublikovou databázi SVJ a bytových družstev s vyhledáváním
podle obce/ulice. RBD Radar ho umí použít jako zdroj subjektů — místo ručního
dohledávání OpenData datasetů po krajích stačí:

  python -m app.prvotkar_client --obec "Brno"
  python -m app.prvotkar_client --obec "Brno" --ulice "Rybářská"
  python -m app.prvotkar_client --ico 3438546

Naimportované subjekty pak zpracuje běžná pipeline:
  python -m app.pipeline --sync-all --limit 10 --city Brno
"""

import argparse
import os
from datetime import datetime

import requests
from sqlalchemy import select

from .db import init_db, SessionLocal
from .models import Subject

PRVOTKAR_URL = os.getenv("PRVOTKAR_URL", "https://prvotkar-backend.onrender.com")
PAGE_SIZE = 200


class PrvotkarClient:
    def __init__(self, base_url: str = PRVOTKAR_URL, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "RBD-Radar/0.3"})

    def _get(self, path: str, **params):
        r = self.session.get(f"{self.base_url}{path}", params=params,
                             timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def svj(self, obec: str | None = None, ulice: str | None = None,
            cast_obce: str | None = None, typ: str | None = None,
            okres: str | None = None,
            start: int = 0, pocet: int = PAGE_SIZE) -> dict:
        params = {"start": start, "pocet": pocet}
        if obec:
            params["obec"] = obec
        if okres:
            params["okres"] = okres
        if ulice:
            params["ulice"] = ulice
        if cast_obce:
            params["cast_obce"] = cast_obce
        if typ:
            params["typ"] = typ
        return self._get("/api/svj", **params)

    def by_ico(self, ico: str) -> dict:
        return self._get(f"/api/ico/{ico}")

    def iter_svj(self, obec: str | None = None, **kwargs):
        """Projde všechny stránky výsledků."""
        start = 0
        while True:
            data = self.svj(obec, start=start, **kwargs)
            subjekty = data.get("subjekty", [])
            if not subjekty:
                break
            yield from subjekty
            start += len(subjekty)
            if start >= data.get("celkem", 0):
                break


def _subject_from_prvotkar(item: dict) -> dict:
    """Převod záznamu Prvotkáře na pole Subjectu RBD Radaru."""
    sidlo = item.get("sidlo") or {}
    cislo_dom = sidlo.get("cisloDomovni")
    cislo_or = sidlo.get("cisloOrientacni")
    house_number = (f"{cislo_dom}/{cislo_or}" if cislo_dom and cislo_or
                    else (cislo_dom or cislo_or))
    city = sidlo.get("nazevObce")
    street = sidlo.get("nazevUlice") or sidlo.get("nazevCastiObce")
    zip_code = sidlo.get("psc")
    address_parts = [x for x in [street, house_number, city, zip_code] if x]

    vznik = None
    if item.get("datumVzniku"):
        try:
            vznik = datetime.strptime(item["datumVzniku"], "%Y-%m-%d")
        except ValueError:
            pass

    return {
        "ico": str(item["ico"]).lstrip("0"),
        "name": item.get("obchodniJmeno") or f"SVJ {item['ico']}",
        "city": city,
        "street": street,
        "house_number": str(house_number) if house_number else None,
        "zip_code": str(zip_code) if zip_code else None,
        "address": ", ".join(str(x) for x in address_parts) or None,
        "last_entry_date": vznik,
        "source_dataset": "prvotkar",
    }


def import_obec(obec: str | None = None, ulice: str | None = None,
                cast_obce: str | None = None, typ: str | None = None,
                limit: int | None = None, okres: str | None = None) -> dict:
    """Naimportuje subjekty z Prvotkáře do databáze RBD Radaru."""
    init_db()
    client = PrvotkarClient()
    db = SessionLocal()
    inserted = updated = 0
    icos: list[str] = []
    try:
        for n, item in enumerate(client.iter_svj(obec, ulice=ulice,
                                                 cast_obce=cast_obce, typ=typ,
                                                 okres=okres)):
            if limit and n >= limit:
                break
            fields = _subject_from_prvotkar(item)
            icos.append(fields["ico"])
            subject = db.scalar(
                select(Subject).where(Subject.ico == fields["ico"]))
            if subject is None:
                subject = Subject(
                    legal_form="Společenství vlastníků jednotek",
                    source_url="https://or.justice.cz/ias/ui/rejstrik",
                    **fields,
                )
                db.add(subject)
                inserted += 1
            else:
                # Adresní údaje z Prvotkáře jsou obvykle čerstvější.
                for key, value in fields.items():
                    if key in ("ico", "last_entry_date"):
                        continue
                    if value:
                        setattr(subject, key, value)
                updated += 1
            if (inserted + updated) % 100 == 0:
                db.commit()
                print(f"Zpracováno: {inserted + updated}")
        db.commit()
    finally:
        db.close()
    return {"inserted": inserted, "updated": updated, "icos": icos}


def import_ico(ico: str) -> dict:
    init_db()
    client = PrvotkarClient()
    item = client.by_ico(ico)
    if item.get("subjekty"):
        item = item["subjekty"][0]
    fields = _subject_from_prvotkar(item)
    db = SessionLocal()
    try:
        subject = db.scalar(select(Subject).where(Subject.ico == fields["ico"]))
        created = subject is None
        if created:
            subject = Subject(
                legal_form="Společenství vlastníků jednotek",
                source_url="https://or.justice.cz/ias/ui/rejstrik",
                **fields,
            )
            db.add(subject)
        else:
            for key, value in fields.items():
                if key != "ico" and value:
                    setattr(subject, key, value)
        db.commit()
        return {"ico": fields["ico"], "name": fields["name"], "created": created}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Import SVJ/BD z Prvotkáře do RBD Radaru")
    parser.add_argument("--obec", help="Název obce (např. Brno)")
    parser.add_argument("--ulice", help="Filtr ulice")
    parser.add_argument("--cast-obce", help="Filtr části obce")
    parser.add_argument("--typ", help="svj / bd")
    parser.add_argument("--limit", type=int, help="Max. počet subjektů")
    parser.add_argument("--ico", help="Import jednoho subjektu podle IČO")
    args = parser.parse_args()

    if args.ico:
        out = import_ico(args.ico)
        print(f"{'Založen' if out['created'] else 'Aktualizován'}: "
              f"{out['name']} (IČO {out['ico']})")
    elif args.obec:
        out = import_obec(args.obec, args.ulice, args.cast_obce, args.typ,
                          args.limit)
        print(f"HOTOVO — nové: {out['inserted']}, "
              f"aktualizované: {out['updated']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
