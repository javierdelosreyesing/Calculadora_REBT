# 1. Usamos una base de Ubuntu moderna, estable y con mejor soporte de librerías
FROM ubuntu:22.04

# Avoid stuck build triggers (evita que se quede colgado pidiendo zona horaria)
ENV DEBIAN_FRONTEND=noninteractive

# 2. Actualizamos e instalamos Python y las dependencias de WeasyPrint correctas
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    weasyprint \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Preparamos la carpeta de la aplicación dentro del servidor
WORKDIR /app

# 4. Instalamos Flask (WeasyPrint ya se instaló arriba con sus dependencias de Linux)
RUN pip3 install --no-cache-dir Flask==3.0.2

# 5. Copiamos todos tus archivos al servidor
COPY . .

# 6. Arrancamos tu servidor Flask usando python3
CMD ["python3", "app.py"]
