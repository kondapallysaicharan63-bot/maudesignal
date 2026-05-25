FROM python:3.12-slim

# GTK/Cairo for WeasyPrint PDF export
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY skills/ skills/

RUN pip install --no-cache-dir -e .

# DB stored in a named volume; mount at runtime.
ENV MAUDESIGNAL_DB_PATH=/data/maudesignal.db
VOLUME ["/data"]

EXPOSE 8501

CMD ["python3.12", "-m", "streamlit", "run", "src/maudesignal/dashboard/app.py", \
     "--server.port=8501", "--server.headless=true", "--server.enableCORS=false"]
