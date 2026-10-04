FROM python:3.11-slim-bookworm

LABEL maintainer="backtesting-engine"
LABEL description="Motor de Backtesting Cuantitativo - Backend"

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente
COPY . .

# Directorio para datos persistentes
RUN mkdir -p /app/data

VOLUME ["/app/data"]

# Por defecto, ejecutar init_db
CMD ["python", "init_db.py"]
