FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-deu \
    tesseract-ocr-fra \
    tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY oracle/ oracle/

RUN pip install --no-cache-dir -e .

EXPOSE 8200

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

CMD ["uvicorn", "oracle.api.app:create_app", "--host", "0.0.0.0", "--port", "8200", "--factory"]
