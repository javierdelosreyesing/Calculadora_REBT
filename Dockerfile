FROM python:3.11-slim

# Instalamos las librerías de dibujo y PDF que exige WeasyPrint en Linux
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-cffi \
    python3-brotli \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libopenjp2-7 \
    libjpeg62-turbo \
    libgdk-pixbuf2.0-0 \
    shared-mime-info \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalamos tus requerimientos
RUN pip install --no-cache-dir Flask==3.0.2 weasyprint==61.2

COPY . .

CMD ["python", "app.py"]
