import re
from datetime import datetime

def clean(value):
    return value.strip() if value else None

def first(pattern, text):
    m = re.search(pattern, text, flags=re.I | re.S)
    return clean(m.group(1)) if m else None

def parse_udaje(udaje: str):
    # OpenData ISVR používá ve sloupci 'udaje' textovou strukturu podobnou JSON.
    file_number = first(r"hlavicka=Spisová značka.*?hodnotaText=([^;}]*)", udaje)
    court = first(r"spisZn=\{soud=\{kod=[^;}]*(?:;|,)nazev=([^;}]+)", udaje)

    # Robustnější varianta: pokud se předchozí regex netrefí.
    if not court:
        court = first(r"soud=\{kod=[^;}]*(?:;|,)nazev=([^;}]+)", udaje)

    city = first(r"hlavicka=Sídlo.*?adresa=\{.*?obec=([^;}]*)", udaje)
    street = first(r"hlavicka=Sídlo.*?adresa=\{.*?ulice=([^;}]*)", udaje)
    cislo_po = first(r"hlavicka=Sídlo.*?adresa={.*?cisloPo=([^;}]*)", udaje)
    cislo_or = first(r"hlavicka=Sídlo.*?adresa={.*?cisloOr=([^;}]*)", udaje)
    house_number = f"{cislo_po}/{cislo_or}" if cislo_po and cislo_or else (cislo_po or cislo_or)
    zip_code = first(r"hlavicka=Sídlo.*?adresa=\{.*?psc=([^;}]*)", udaje)

    dates = re.findall(r"zapisDatum=(\d{4}-\d{2}-\d{2})", udaje)
    last_entry = None
    if dates:
        try:
            last_entry = datetime.strptime(max(dates), "%Y-%m-%d")
        except ValueError:
            pass

    address_parts = [x for x in [street, house_number, city, zip_code] if x]
    address = ", ".join(address_parts) if address_parts else None

    return {
        "file_number": file_number,
        "court": court,
        "city": city,
        "street": street,
        "house_number": house_number,
        "zip_code": zip_code,
        "address": address,
        "last_entry_date": last_entry,
    }
