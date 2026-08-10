from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Subject
from app.pipeline import ingest_text


def _setup():
    """Izolovaná in-memory databáze — nesahá na data/rbd_radar.db."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    subject = Subject(ico="99999999", name="SVJ Test, Brno")
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return db, subject


def test_ingest_and_dedupe():
    db, subject = _setup()
    text = (
        "Zápis ze shromáždění konané dne 5.6.2026. Schválena příprava "
        "zateplení fasády a rekonstrukce balkonů. Financování úvěrem. "
        "Bylo schváleno navýšení příspěvku do fondu oprav 40 Kč/m2."
    )
    out = ingest_text(db, subject, text=text, external_id="T-1",
                      title="Zápis ze shromáždění")
    assert not out["duplicate"]
    assert out["score"] >= 60
    assert out["doc_type"] == "zápis ze shromáždění"
    assert out["meeting_date"] == "5.6.2026"
    assert any(s["type"] == "fond_oprav" and s["value"] == "40 Kč/m²"
               for s in out["signals"])

    # stejný text podruhé -> duplicita
    out2 = ingest_text(db, subject, text=text, external_id="T-2",
                       title="Zápis ze shromáždění (kopie)")
    assert out2["duplicate"]
    db.close()


def test_ingest_stanovy_discount():
    db, subject = _setup()
    text = (
        "Notářský zápis — stanovy společenství. V případě havarijního stavu "
        "je výbor oprávněn zajistit opravu. Společenství může sjednat úvěr. "
        "Výbor zajišťuje projektovou dokumentaci oprav domu."
    )
    out = ingest_text(db, subject, text=text, external_id="T-3",
                      title="notářský zápis stanovy, NZ 1/2024")
    # bez slevy by skóre bylo ~50+, se slevou pro stanovy musí být nízké
    assert out["score"] < 35
    db.close()
