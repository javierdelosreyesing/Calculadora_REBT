FROM python:3.11

WORKDIR /app

# Copiamos todo el contenido al contenedor
COPY . /app

# Actualizamos pip e instalamos las librerías necesarias
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

CMD ["python", "app.py"]
