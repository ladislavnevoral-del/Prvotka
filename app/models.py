from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    ico: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))
    legal_form: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    court: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(200), nullable=True)
    street: Mapped[str | None] = mapped_column(String(300), nullable=True)
    house_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_entry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_dataset: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ID subjektu ve webovém rejstříku or.justice.cz (pro Sbírku listin).
    justice_subjekt_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    listiny_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    documents = relationship("Document", back_populates="subject", cascade="all, delete-orphan")

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(500), index=True)
    title: Mapped[str] = mapped_column(String(1000))
    document_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Výstupy analýzy
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meeting_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    subject = relationship("Subject", back_populates="documents")
    signals = relationship("Signal", back_populates="document", cascade="all, delete-orphan")

class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    points: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text)

    # Rozšíření z jednotného signal_engine
    type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    document = relationship("Document", back_populates="signals")
