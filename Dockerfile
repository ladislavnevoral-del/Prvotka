FROM python:3.12-slim

# OCR závislosti (Tesseract s češtinou + Poppler pro převod PDF na obrázky)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-ces poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
RUN mkdir -p data/listiny data/cache data/logs

# DATABASE_URL dodá prostředí (Render: z připojené Postgres instance).
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
