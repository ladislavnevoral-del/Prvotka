"""Extrakce textu z PDF: nejdřív textová vrstva, u skenů OCR."""

from pypdf import PdfReader


def extract_pdf_text(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


def looks_like_scan(text: str, min_chars: int = 100) -> bool:
    return len(text.strip()) < min_chars


def extract_text_smart(path: str) -> tuple[str, bool]:
    """Vrátí (text, used_ocr). Skenované PDF automaticky projde OCR."""
    try:
        text = extract_pdf_text(path)
    except Exception:
        text = ""
    if looks_like_scan(text):
        from .ocr import ocr_pdf
        return ocr_pdf(path), True
    return text, False
