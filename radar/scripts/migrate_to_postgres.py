"""Jednorázová migrace dat z lokální SQLite do Postgres (Render).

Použití (z kořene projektu, s aktivním .venv):

  python scripts/migrate_to_postgres.py \
      "postgresql://user:heslo@host/rbd_radar"

URL najdete na Renderu u databáze rbd-radar-db jako "External Database URL".
Skript je idempotentní — subjekty páruje podle IČO a dokumenty podle
text_hash, takže opakované spuštění nic nezdvojí.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base  # noqa: E402
from app.models import Subject, Document, Signal  # noqa: E402


def migrate(target_url: str,
            source_url: str = "sqlite:///./data/rbd_radar.db"):
    if target_url.startswith("postgres://"):
        target_url = target_url.replace("postgres://", "postgresql://", 1)

    src_engine = create_engine(source_url)
    dst_engine = create_engine(target_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=dst_engine)

    Src = sessionmaker(bind=src_engine)()
    Dst = sessionmaker(bind=dst_engine)()

    stats = {"subjects": 0, "documents": 0, "signals": 0, "skipped_docs": 0}

    try:
        ico_to_dst_id = {}
        for s in Src.scalars(select(Subject)):
            existing = Dst.scalar(select(Subject).where(Subject.ico == s.ico))
            if existing is None:
                existing = Subject(**{
                    c.name: getattr(s, c.name)
                    for c in Subject.__table__.columns if c.name != "id"
                })
                Dst.add(existing)
                Dst.flush()
                stats["subjects"] += 1
            ico_to_dst_id[s.ico] = existing.id

        for d in Src.scalars(select(Document)):
            if d.text_hash and Dst.scalar(
                    select(Document).where(Document.text_hash == d.text_hash)):
                stats["skipped_docs"] += 1
                continue
            src_subject = Src.get(Subject, d.subject_id)
            if not src_subject or src_subject.ico not in ico_to_dst_id:
                continue
            new_doc = Document(**{
                c.name: getattr(d, c.name)
                for c in Document.__table__.columns
                if c.name not in ("id", "subject_id")
            })
            new_doc.subject_id = ico_to_dst_id[src_subject.ico]
            Dst.add(new_doc)
            Dst.flush()
            stats["documents"] += 1

            for sig in Src.scalars(
                    select(Signal).where(Signal.document_id == d.id)):
                Dst.add(Signal(**{
                    **{c.name: getattr(sig, c.name)
                       for c in Signal.__table__.columns
                       if c.name not in ("id", "document_id")},
                    "document_id": new_doc.id,
                }))
                stats["signals"] += 1

        Dst.commit()
    finally:
        Src.close()
        Dst.close()

    return stats


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    out = migrate(sys.argv[1])
    print(f"Přeneseno: {out['subjects']} SVJ, {out['documents']} dokumentů, "
          f"{out['signals']} signálů (přeskočeno duplicit: {out['skipped_docs']}).")
