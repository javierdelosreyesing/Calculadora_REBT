FROM python:3.11-alpine

# 1. Instalar las dependencias de Weasyprint usando el gestor alpino (apk)
RUN apk add --no-cache \
    gcc \
    musl-dev \
    jpeg-dev \
    zlib-dev \
    libffi-dev \
    cairo-dev \
    pango-dev \
    gdk-pixbuf-dev \
    shared-mime-info \
    ttf-dejavu

WORKDIR /app

COPY . /app

# 2. Actualizar pip e instalar tus librerías
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

CMD ["python", "app.py"]
