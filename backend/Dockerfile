FROM python:3.13-slim

# Tesseract + poppler for Member 3's OCR; libgomp for XGBoost / scikit-learn
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY ml_modules ./ml_modules
COPY tests ./tests

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
