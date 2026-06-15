# 1. Usamos la imagen completa en lugar de la 'slim'. Ya tiene gcc y herramientas instaladas.
FROM python:3.11

WORKDIR /app

# 2. Copiamos los archivos (Recuerda configurar el Root Directory en Render si están en subcarpeta)
COPY . /app

# 3. Instalamos weasyprint de forma que maneje sus dependencias mediante Python directamente
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

CMD ["python", "app.py"]
