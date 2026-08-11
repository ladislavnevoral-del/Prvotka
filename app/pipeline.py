"""Pipeline: listina (PDF) -> text -> analýza -> databáze.

Použití z příkazové řádky:

  # zpracovat jedno PDF pro dané IČO
  python -m app.pipeline --ico 03438546 --pdf cesta/k/zapisu.pdf

  # stáhnout a zpracovat nové listiny jednoho SVJ ze Sbírky listin
  python -m app.pipeline --ico 03438546 --sync

  # projít více SVJ z databáze (nejdřív ta s nejnovějším zápisem)
  python -m app.pipeline --sync-all --limit 20
"""

import argparse
import hashlib
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from .db import init_db, SessionLocal
from .models import Subject, Document, Signal
from .pdf_extract import extract_text_smart
from .document_analyzer import analyze_document
from .signal_engine import detect_signals, score_signals, lead_level

LISTINY_DIR = Path("data/listiny")

# Stav běžící synchronizace (čte ho /api/sync/status a dashboard).
SYNC_STATE = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "progress": "",
    "processed_subjects": 0,
    "new_documents": 0,
    "hot_found": 0,
    "error": None,
}


def _state_update(state, **kwargs):
    if state is not None:
        state.update(kwargs)

# ---------------------------------------------------------------------------
# Váha podle typu dokumentu
#
# Stanovy, prohlášení vlastníka apod. obsahují obecné právní formulace
# ("v případě havarijního stavu…", "úvěr lze sjednat…"), které nejsou
# skutečným obchodním záměrem. Jejich skóre proto dělíme. Skutečný signál
# nesou hlavně zápisy ze shromáždění.
# ---------------------------------------------------------------------------

_DOC_DISCOUNTS = [
    (re.compile(r"stanovy|prohlášen|prohlasen|podpisov|účetní závěrk"
                r"|ucetni zaverk|rozvaha|výroční zpráv|vyrocni zprav", re.I), 3),
    (re.compile(r"notářsk|notarsk", re.I), 2),
]


def doc_score_divisor(title: str | None, doc_type: str | None) -> int:
    """Vrátí dělitel skóre podle typu dokumentu (1 = bez slevy)."""
    haystack = f"{title or ''} {doc_type or ''}"
    for pattern, divisor in _DOC_DISCOUNTS:
        if pattern.search(haystack):
            return divisor
    return 1


# ---------------------------------------------------------------------------
# Zpracování jednoho dokumentu
# ---------------------------------------------------------------------------

def ingest_text(db: Session, subject: Subject, *, text: str, external_id: str,
                title: str, source_url: str | None = None,
                document_date: datetime | None = None,
                file_path: str | None = None,
                ocr_used: bool = False) -> dict:
    """Uloží dokument + signály. Duplicitní text (podle hashe) přeskočí."""
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = db.scalar(select(Document).where(Document.text_hash == text_hash))
    if existing:
        return {"document_id": existing.id, "duplicate": True,
                "score": existing.score or 0,
                "lead_level": lead_level(existing.score or 0), "signals": []}

    meta = analyze_document(text)
    signals = detect_signals(text)
    score = score_signals(signals)

    divisor = doc_score_divisor(title, meta["document_type"])
    if divisor > 1:
        score //= divisor

    doc = Document(
        subject_id=subject.id,
        external_id=external_id,
        title=title,
        source_url=source_url,
        document_date=document_date or meta["meeting_date"],
        file_path=file_path,
        text=text,
        text_hash=text_hash,
        processed=True,
        score=score,
        doc_type=meta["document_type"],
        meeting_date=meta["meeting_date"],
        ocr_used=ocr_used,
    )
    db.add(doc)
    db.flush()

    for s in signals:
        db.add(Signal(
            document_id=doc.id,
            keyword=s["keyword"],
            category=s["category"],
            points=s["points"],
            evidence=s["context"],
            type=s["type"],
            label=s["label"],
            priority=s["priority"],
            value=s["value"],
        ))
    db.commit()

    return {
        "document_id": doc.id,
        "duplicate": False,
        "score": score,
        "lead_level": lead_level(score),
        "doc_type": meta["document_type"],
        "meeting_date": meta["meeting_date_text"],
        "board_members": meta["board_members"],
        "ocr_used": ocr_used,
        "signals": signals,
    }


def ingest_pdf(db: Session, subject: Subject, pdf_path: str | Path, *,
               external_id: str | None = None, title: str | None = None,
               source_url: str | None = None,
               document_date: datetime | None = None) -> dict:
    """Extrahuje text z PDF (s OCR fallbackem) a uloží ho k subjektu."""
    pdf_path = Path(pdf_path)
    text, ocr_used = extract_text_smart(str(pdf_path))
    if not text.strip():
        return {"error": f"Z PDF {pdf_path.name} se nepodařilo získat text."}
    return ingest_text(
        db, subject,
        text=text,
        external_id=external_id or pdf_path.stem,
        title=title or pdf_path.name,
        source_url=source_url,
        document_date=document_date,
        file_path=str(pdf_path),
        ocr_used=ocr_used,
    )


# ---------------------------------------------------------------------------
# Synchronizace se Sbírkou listin
# ---------------------------------------------------------------------------

def sync_subject(db: Session, subject: Subject, client=None,
                 max_docs: int = 5, only_interesting: bool = True,
                 since: datetime | None = None) -> dict:
    """Stáhne a zpracuje nové listiny jednoho SVJ."""
    from .listiny import ListinyClient

    client = client or ListinyClient()
    result = {"ico": subject.ico, "name": subject.name,
              "downloaded": 0, "skipped": 0, "documents": []}

    if not subject.justice_subjekt_id:
        subject.justice_subjekt_id = client.find_subjekt_id(subject.ico)
        db.commit()

    listiny = client.list_listiny(subject.justice_subjekt_id)
    known_ids = {
        d.external_id
        for d in db.scalars(
            select(Document).where(Document.subject_id == subject.id)
        )
    }

    candidates = [
        l for l in listiny
        if (not only_interesting or l.is_interesting)
        and l.external_id not in known_ids
        and (since is None or ((l.zalozeno or l.vznik or datetime.min) >= since))
    ]
    # Nejnovější napřed.
    candidates.sort(key=lambda l: l.vznik or datetime.min, reverse=True)

    for listina in candidates[:max_docs]:
        target = LISTINY_DIR / subject.ico / f"{listina.dokument_id}.pdf"
        try:
            if not target.exists():
                print(f"  ↓ {listina.cislo} — {listina.typ}")
                client.download_pdf(listina, target)
                result["downloaded"] += 1
            outcome = ingest_pdf(
                db, subject, target,
                external_id=listina.external_id,
                title=listina.typ,
                source_url=listina.detail_url,
                document_date=listina.vznik,
            )
            outcome["listina"] = listina.cislo
            result["documents"].append(outcome)
        except Exception as exc:
            print(f"  ! {listina.cislo}: {exc}")
            result["documents"].append(
                {"listina": listina.cislo, "error": str(exc)}
            )

    result["skipped"] = len(listiny) - len(candidates)
    subject.listiny_checked_at = datetime.utcnow()
    db.commit()
    return result


def sync_many(db: Session, limit: int = 10, city: str | None = None,
              max_docs: int = 3, since_days: int | None = None,
              state: dict | None = None,
              icos: list[str] | None = None) -> list[dict]:
    """Projde více SVJ — přednostně ta s nejnovějším zápisem v rejstříku.

    since_days: stahovat jen listiny založené/vzniklé za posledních N dní.
    icos: explicitní seznam IČO (např. celý okres z Prvotkáře).
    state: volitelný slovník, do kterého se průběžně hlásí postup.
    """
    from .listiny import ListinyClient

    # Rotační fronta: nejdřív domy, které ještě nikdy nebyly zkontrolované,
    # pak ty s nejstarší kontrolou. Opakované běhy tak postupně pokryjí
    # celou databázi, místo aby dokola procházely stejné subjekty.
    rotation = (Subject.listiny_checked_at.asc().nullsfirst(),
                desc(Subject.last_entry_date))
    if icos:
        normalized = {i.lstrip("0") for i in icos if i}
        q = (select(Subject).where(Subject.ico.in_(normalized))
             .order_by(*rotation).limit(max(limit, len(normalized))))
    elif city:
        q = (select(Subject).where(Subject.city.ilike(f"%{city}%"))
             .order_by(*rotation).limit(limit))
    else:
        q = select(Subject).order_by(*rotation).limit(limit)

    since = None
    if since_days:
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(days=since_days)

    client = ListinyClient()
    results = []
    subjects = db.scalars(q).all()
    for n, subject in enumerate(subjects, 1):
        print(f"» {subject.name} (IČO {subject.ico})")
        _state_update(state,
                      progress=f"{n}/{len(subjects)}: {subject.name}",
                      processed_subjects=n)
        try:
            res = sync_subject(db, subject, client, max_docs=max_docs,
                               since=since)
            results.append(res)
            if state is not None:
                new_docs = [d for d in res.get("documents", [])
                            if not d.get("duplicate") and not d.get("error")]
                state["new_documents"] += len(new_docs)
                state["hot_found"] += sum(
                    1 for d in new_docs if d.get("score", 0) >= 60)
        except Exception as exc:
            print(f"  ! přeskočeno: {exc}")
            results.append({"ico": subject.ico, "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# Přepočet uložených dokumentů (po změně pravidel)
# ---------------------------------------------------------------------------

def rescore_all(db: Session) -> dict:
    """Znovu analyzuje všechny uložené texty aktuálními pravidly."""
    changed = unchanged = 0
    docs = db.scalars(select(Document).where(Document.text.isnot(None))).all()
    for doc in docs:
        meta = analyze_document(doc.text)
        signals = detect_signals(doc.text)
        score = score_signals(signals)
        divisor = doc_score_divisor(doc.title, meta["document_type"])
        if divisor > 1:
            score //= divisor

        old_score = doc.score
        # nahradit signály
        for s in list(doc.signals):
            db.delete(s)
        for s in signals:
            db.add(Signal(
                document_id=doc.id,
                keyword=s["keyword"], category=s["category"],
                points=s["points"], evidence=s["context"],
                type=s["type"], label=s["label"],
                priority=s["priority"], value=s["value"],
            ))
        doc.score = score
        doc.doc_type = meta["document_type"]
        doc.meeting_date = meta["meeting_date"] or doc.meeting_date

        if old_score != score:
            changed += 1
            print(f"  {doc.title[:60]:60s} {old_score or 0:>3} -> {score:>3}"
                  + (f"  (/{divisor} – {meta['document_type'] or 'typ dle názvu'})"
                     if divisor > 1 else ""))
        else:
            unchanged += 1
    db.commit()
    return {"changed": changed, "unchanged": unchanged, "total": len(docs)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RBD Radar pipeline")
    parser.add_argument("--ico", help="IČO SVJ")
    parser.add_argument("--pdf", help="Cesta k PDF ke zpracování")
    parser.add_argument("--sync", action="store_true",
                        help="Stáhnout nové listiny ze Sbírky listin")
    parser.add_argument("--sync-all", action="store_true",
                        help="Synchronizovat více SVJ z databáze")
    parser.add_argument("--city", help="Filtr města pro --sync-all")
    parser.add_argument("--limit", type=int, default=10,
                        help="Počet SVJ pro --sync-all")
    parser.add_argument("--max-docs", type=int, default=5,
                        help="Max. počet listin na jedno SVJ")
    parser.add_argument("--since-days", type=int, default=None,
                        help="Stahovat jen listiny za posledních N dní")
    parser.add_argument("--rescore", action="store_true",
                        help="Přepočítat skóre všech uložených dokumentů "
                             "aktuálními pravidly")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.rescore:
            out = rescore_all(db)
            print(f"\nPřepočteno {out['total']} dokumentů, "
                  f"změněno {out['changed']}, beze změny {out['unchanged']}.")
        elif args.pdf:
            if not args.ico:
                parser.error("--pdf vyžaduje --ico")
            subject = db.scalar(select(Subject).where(Subject.ico == args.ico.lstrip("0")))
            if not subject:
                subject = db.scalar(select(Subject).where(Subject.ico == args.ico))
            if not subject:
                parser.error(f"SVJ s IČO {args.ico} není v databázi. "
                             f"Nejdřív spusť import: python -m app.import_justice")
            out = ingest_pdf(db, subject, args.pdf)
            _print_outcome(out)
        elif args.sync:
            if not args.ico:
                parser.error("--sync vyžaduje --ico")
            subject = db.scalar(select(Subject).where(Subject.ico == args.ico.lstrip("0")))
            if not subject:
                subject = db.scalar(select(Subject).where(Subject.ico == args.ico))
            if not subject:
                parser.error(f"SVJ s IČO {args.ico} není v databázi.")
            result = sync_subject(db, subject, max_docs=args.max_docs)
            print(f"\nStaženo: {result['downloaded']}, "
                  f"nezajímavé/známé: {result['skipped']}")
            for docres in result["documents"]:
                _print_outcome(docres)
        elif args.sync_all:
            results = sync_many(db, limit=args.limit, city=args.city,
                                max_docs=args.max_docs,
                                since_days=args.since_days)
            hot = [r for r in results for d in r.get("documents", [])
                   if d.get("score", 0) >= 60]
            print(f"\nHotovo. Subjektů: {len(results)}, "
                  f"nadějných dokumentů: {len(hot)}")
        else:
            parser.print_help()
    finally:
        db.close()


def _print_outcome(out: dict):
    if out.get("error"):
        print(f"  ! {out['error']}")
        return
    if out.get("duplicate"):
        print(f"  = dokument už v databázi je (id {out['document_id']})")
        return
    print(f"  ✓ dokument {out.get('listina', out['document_id'])}: "
          f"skóre {out['score']}/100 ({out['lead_level']})"
          + (" [OCR]" if out.get("ocr_used") else ""))
    for s in out.get("signals", []):
        val = f" = {s['value']}" if s.get("value") else ""
        print(f"      · {s['label']}{val}")


if __name__ == "__main__":
    main()
