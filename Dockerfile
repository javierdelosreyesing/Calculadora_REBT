FROM python:3.11-slim

# 1. Forzar permisos de root y limpiar antes de actualizar
USER root

# 2. Instalar dependencias de WeasyPrint ignorando advertencias y limpiando caché
RUN apt-get clean && \
    apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    python3-cffi \
    python3-brotli \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

# 3. Asegurar que pip esté actualizado e instalar tus librerías
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

CMD ["python", "app.py"]
