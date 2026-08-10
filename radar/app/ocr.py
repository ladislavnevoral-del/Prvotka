"""OCR vrstva: PDF -> obrázky (Poppler) -> text (Tesseract, čeština).

Cesty k nástrojům se hledají automaticky (funguje na macOS s Homebrew,
na Linuxu i v Dockeru). Pracovní adresář je volitelný — bez něj se použije
dočasná složka, která se po zpracování uklidí.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

_EXTRA_PATHS = [
    "/opt/homebrew/bin",   # macOS Apple Silicon (Homebrew)
    "/usr/local/bin",      # macOS Intel / Linux
    "/usr/bin",
]


def _find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for prefix in _EXTRA_PATHS:
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(
        f"Nástroj '{name}' nebyl nalezen. Nainstaluj ho prosím "
        f"(macOS: brew install {'tesseract tesseract-lang' if name == 'tesseract' else 'poppler'}, "
        f"Linux: apt install {'tesseract-ocr tesseract-ocr-ces' if name == 'tesseract' else 'poppler-utils'})."
    )


def pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 300) -> list[Path]:
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    prefix = out / "page"
    subprocess.run(
        [_find_tool("pdftoppm"), "-jpeg", "-r", str(dpi), str(pdf), str(prefix)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sorted(out.glob("page-*.jpg"))


def ocr_image(image_path: str, lang: str = "ces") -> str:
    image_path = Path(image_path).resolve()
    result = subprocess.run(
        [_find_tool("tesseract"), str(image_path), "stdout", "-l", lang],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Tesseract skončil s kódem {result.returncode}: {stderr.strip()}"
        )
    return result.stdout.decode("utf-8", errors="replace")


def ocr_pdf(pdf_path: str, work_dir: str | None = None, lang: str = "ces",
            dpi: int = 300) -> str:
    """Zpracuje celé PDF. Bez work_dir použije dočasnou složku."""
    if work_dir is None:
        with tempfile.TemporaryDirectory(prefix="rbd_ocr_") as tmp:
            return _ocr_pdf_in(pdf_path, tmp, lang, dpi)
    return _ocr_pdf_in(pdf_path, work_dir, lang, dpi)


def _ocr_pdf_in(pdf_path: str, work_dir: str, lang: str, dpi: int) -> str:
    images = pdf_to_images(pdf_path, work_dir, dpi)
    texts = []
    for image in images:
        try:
            text = ocr_image(image, lang)
            if text.strip():
                texts.append(text)
        except RuntimeError as exc:
            print(f"OCR chyba: {image}: {exc}")
    return "\n\n".join(texts)
