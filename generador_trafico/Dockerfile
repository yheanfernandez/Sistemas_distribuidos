FROM python:3.10-slim

WORKDIR /app

# Copiamos dependencias e instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Mantenemos el contenedor vivo por ahora (ideal para desarrollo)
CMD ["python", "-u", "main.py"]

