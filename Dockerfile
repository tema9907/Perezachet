FROM python:3.11-slim

WORKDIR /app

# Шрифты для PyMuPDF (Liberation ≈ Times New Roman метрически)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8765

CMD ["python", "-m", "uvicorn", "app:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--log-level", "info"]
