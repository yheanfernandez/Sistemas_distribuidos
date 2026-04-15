# Tarea 1 - Sistemas Distribuidos: Sistema de Consultas con Caché

Sistema distribuido que simula tráfico de consultas sobre datos de edificios (Google Open Buildings) en zonas de Santiago, con caché Redis y registro de métricas.

---

## Estructura del Proyecto

```
/tarea_1_distribuidos
│
├── /generador_trafico
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── /generador_respuestas
│   ├── dataset_edificios.csv   <-- (Aquí van los datos de Google Open Buildings)
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── /almacenamiento_metricas
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
└── docker-compose.yml
```

---

## Requisitos Previos: Instalar Docker (Debian)

**1. Descargar la llave y el repositorio**
```bash
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --yes --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

**2. Actualizar e instalar**
```bash
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
```

**3. Evitar usar `sudo` constantemente**
```bash
sudo usermod -aG docker $USER
```

---

## Puesta en Marcha

### 1. Crear las carpetas de trabajo
```bash
mkdir -p generador_trafico generador_respuestas almacenamiento_metricas
```

### 2. Crear los archivos en blanco
```bash
touch generador_trafico/main.py generador_trafico/requirements.txt generador_trafico/Dockerfile
touch generador_respuestas/main.py generador_respuestas/requirements.txt generador_respuestas/Dockerfile
touch almacenamiento_metricas/main.py almacenamiento_metricas/requirements.txt almacenamiento_metricas/Dockerfile
```

### 3. Crear el archivo maestro `docker-compose.yml`
```yaml
services:
  # 1. Sistema de Caché (Redis)
  cache:
    image: redis:alpine
    container_name: redis_cache
    ports:
      - "6379:6379"
    command: redis-server --maxmemory 50mb --maxmemory-policy allkeys-lru

  # 2. Almacenamiento de Métricas
  datos:
    build: ./almacenamiento_metricas
    container_name: modulo_datos
    ports:
      - "8000:8000"

  # 3. Generador de Respuestas (El Cerebro)
  respuestas:
    build: ./generador_respuestas
    container_name: modulo_respuestas
    ports:
      - "8001:8000"
    depends_on:
      - cache
      - datos
    environment:
      - REDIS_HOST=cache
      - DATOS_URL=http://datos:8000

  # 4. Generador de Tráfico (El Bot Simulador)
  trafico:
    build: ./generador_trafico
    container_name: modulo_trafico
    depends_on:
      - cache
      - datos
      - respuestas
    environment:
      - REDIS_HOST=cache
      - DATOS_URL=http://datos:8000
      - RESPUESTAS_URL=http://respuestas:8001
```

### 4. Dockerfile base (para los 3 módulos)

Antes de trabajar en cada `main.py`, usamos este Dockerfile general para validar que los contenedores levanten correctamente:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Copiamos dependencias e instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Mantenemos el contenedor vivo durante el desarrollo
CMD ["tail", "-f", "/dev/null"]
```

> **¿Por qué `tail -f /dev/null`?** Mantiene el contenedor encendido y en silencio durante la fase de desarrollo, permitiendo entrar, revisar archivos y probar comandos sin que Docker lo mate. Una vez validado, se reemplaza por el comando real de cada módulo.

### 5. Encender el sistema completo
```bash
docker compose up -d --build
```

- `--build`: construye las imágenes desde cero leyendo los Dockerfiles.
- `-d`: modo *detached*, levanta los servicios en segundo plano.

### 6. Verificar que todo esté corriendo
```bash
docker compose ps
```

Deberías ver los 4 servicios (`cache`, `datos`, `respuestas`, `trafico`) con estado `Up`.

---

## Módulos

### `generador_respuestas` — El Cerebro

Servidor FastAPI que carga el dataset de edificios al iniciar y expone 5 endpoints de consulta.

**requirements.txt**
```
fastapi
uvicorn
pandas
numpy
```

**Zonas definidas**

| ID | Sector | Área (km²) |
|---|---|---|
| Z1 | Providencia | 9.5 |
| Z2 | Las Condes | 20.0 |
| Z3 | Maipú | 35.0 |
| Z4 | Santiago Centro | 15.0 |
| Z5 | Pudahuel | 40.0 |

**Endpoints disponibles**

| Endpoint | Descripción |
|---|---|
| `GET /q1` | Conteo de edificios en una zona |
| `GET /q2` | Área promedio y total de edificios |
| `GET /q3` | Densidad de edificios por km² |
| `GET /q4` | Comparación de densidad entre dos zonas |
| `GET /q5` | Distribución de scores de confianza |

**main.py**
```python
from fastapi import FastAPI, HTTPException
import pandas as pd
import numpy as np
import os

app = FastAPI()

ZONAS_KM2 = {
    "Z1": 9.5,   # Providencia
    "Z2": 20.0,  # Las Condes
    "Z3": 35.0,  # Maipú
    "Z4": 15.0,  # Santiago Centro
    "Z5": 40.0   # Pudahuel
}

ZONAS_BBOX = {
    "Z1": {"lat_min": -33.445, "lat_max": -33.420, "lon_min": -70.640, "lon_max": -70.600},
    "Z2": {"lat_min": -33.420, "lat_max": -33.390, "lon_min": -70.600, "lon_max": -70.550},
    "Z3": {"lat_min": -33.530, "lat_max": -33.490, "lon_min": -70.790, "lon_max": -70.740},
    "Z4": {"lat_min": -33.470, "lat_max": -33.430, "lon_min": -70.670, "lon_max": -70.630},
    "Z5": {"lat_min": -33.460, "lat_max": -33.430, "lon_min": -70.810, "lon_max": -70.760}
}

db_memoria = {}

@app.on_event("startup")
def cargar_datos():
    ruta_csv = "dataset_edificios.csv.gz"
    if not os.path.exists(ruta_csv):
        print(f"¡ADVERTENCIA! No se encontró el archivo {ruta_csv}.")
        return
    print(f"Cargando dataset real desde {ruta_csv}...")
    df_completo = pd.read_csv(ruta_csv)
    for zona, bbox in ZONAS_BBOX.items():
        filtro = (
            (df_completo['latitude'] >= bbox['lat_min']) &
            (df_completo['latitude'] <= bbox['lat_max']) &
            (df_completo['longitude'] >= bbox['lon_min']) &
            (df_completo['longitude'] <= bbox['lon_max'])
        )
        db_memoria[zona] = df_completo[filtro]
        print(f"Zona {zona} cargada con {len(db_memoria[zona])} edificios.")
    print("¡Dataset real cargado exitosamente en memoria RAM!")

@app.get("/q1")
def q1_count(zone_id: str, confidence_min: float = 0.0):
    if zone_id not in db_memoria:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    df = db_memoria[zone_id]
    conteo = int((df['confidence'] >= confidence_min).sum())
    return {"consulta": "Q1", "zone_id": zone_id, "count": conteo}

@app.get("/q2")
def q2_area(zone_id: str, confidence_min: float = 0.0):
    if zone_id not in db_memoria:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    df = db_memoria[zone_id]
    edificios_validos = df[df['confidence'] >= confidence_min]
    if edificios_validos.empty:
        return {"avg_area": 0, "total_area": 0, "n": 0}
    return {
        "consulta": "Q2", "zone_id": zone_id,
        "avg_area": float(edificios_validos['area_in_meters'].mean()),
        "total_area": float(edificios_validos['area_in_meters'].sum()),
        "n": len(edificios_validos)
    }

@app.get("/q3")
def q3_density(zone_id: str, confidence_min: float = 0.0):
    resultado_q1 = q1_count(zone_id, confidence_min)
    area_km2 = ZONAS_KM2.get(zone_id, 1.0)
    densidad = resultado_q1["count"] / area_km2
    return {"consulta": "Q3", "zone_id": zone_id, "density": densidad}

@app.get("/q4")
def q4_compare(zone_a: str, zone_b: str, confidence_min: float = 0.0):
    da = q3_density(zone_a, confidence_min)["density"]
    db = q3_density(zone_b, confidence_min)["density"]
    winner = zone_a if da > db else zone_b
    return {"consulta": "Q4", "zone_a": da, "zone_b": db, "winner": winner}

@app.get("/q5")
def q5_confidence_dist(zone_id: str, bins: int = 5):
    if zone_id not in db_memoria:
        raise HTTPException(status_code=404, detail="Zona no encontrada")
    df = db_memoria[zone_id]
    scores = df['confidence'].values
    counts, edges = np.histogram(scores, bins=bins, range=(0.0, 1.0))
    distribucion = [{"bucket": i, "min": float(edges[i]), "max": float(edges[i+1]), "count": int(counts[i])} for i in range(bins)]
    return {"consulta": "Q5", "zone_id": zone_id, "distribution": distribucion}
```

**CMD final del Dockerfile**
```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Reconstruir el módulo**
```bash
docker compose up -d --build respuestas
```

---

### `almacenamiento_metricas` — El Cuaderno

Servidor FastAPI que recibe y almacena métricas de cada consulta (hits, misses, latencia).

**requirements.txt**
```
fastapi
uvicorn
```

**Endpoints disponibles**

| Endpoint | Descripción |
|---|---|
| `POST /registrar` | Registra un evento HIT o MISS |
| `GET /estadisticas` | Devuelve el resumen y hit rate del sistema |

**main.py**
```python
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()

registro_metricas = {
    "total_consultas": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "historial": []
}

class Metrica(BaseModel):
    tipo: str
    consulta: str
    zona: str
    tiempo_procesamiento_ms: float

@app.post("/registrar")
def registrar_evento(metrica: Metrica):
    registro_metricas["total_consultas"] += 1
    if metrica.tipo.upper() == "HIT":
        registro_metricas["cache_hits"] += 1
    elif metrica.tipo.upper() == "MISS":
        registro_metricas["cache_misses"] += 1
    registro_metricas["historial"].append({
        "timestamp": datetime.now().isoformat(),
        "tipo": metrica.tipo,
        "consulta": metrica.consulta,
        "zona": metrica.zona,
        "tiempo_ms": metrica.tiempo_procesamiento_ms
    })
    return {"status": "registrado", "evento": metrica.tipo}

@app.get("/estadisticas")
def ver_estadisticas():
    total = registro_metricas["total_consultas"]
    hits = registro_metricas["cache_hits"]
    hit_rate = (hits / total * 100) if total > 0 else 0.0
    return {
        "total_consultas": total,
        "cache_hits": hits,
        "cache_misses": registro_metricas["cache_misses"],
        "hit_rate_porcentaje": round(hit_rate, 2)
    }
```

**CMD final del Dockerfile**
```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Reconstruir el módulo**
```bash
docker compose up -d --build datos
```

---

### `generador_trafico` — El Bot

Simula dos ráfagas de 100 consultas cada una, usando caché Redis para interceptar respuestas repetidas antes de llegar al Cerebro.

**requirements.txt**
```
requests
redis
numpy
```

**Distribuciones de tráfico**

| Distribución | Descripción |
|---|---|
| Uniforme | Las consultas se reparten aleatoriamente entre todas las zonas |
| Zipf | Pocas zonas concentran la mayoría del tráfico, simulando comportamiento real |

**Flujo de cada consulta**
1. El bot elige zona y tipo de consulta aleatoriamente.
2. Busca la respuesta en Redis (caché).
3. **HIT**: usa la respuesta guardada directamente.
4. **MISS**: consulta al Cerebro, guarda el resultado en Redis con TTL de 60 segundos.
5. Registra la métrica (tipo, zona, latencia) en el módulo de almacenamiento.

**main.py**
```python
import time
import random
import requests
import redis
import numpy as np
import os
import json

REDIS_HOST = "cache"
DATOS_URL = "http://datos:8000"
RESPUESTAS_URL = "http://respuestas:8000"

cache = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

ZONAS = ["Z1", "Z2", "Z3", "Z4", "Z5"]
CONSULTAS = ["q1", "q2", "q3", "q4", "q5"]

def limpiar_cache():
    print("Limpiando la caché (Cold Start)...")
    try:
        r = redis.Redis(host=os.getenv("REDIS_HOST", "cache"), port=6379, db=0)
        r.flushall()
        print("¡Caché limpia y lista para la prueba!")
    except Exception as e:
        print(f"No se pudo limpiar la caché: {e}")

def elegir_zona_zipf():
    rango = np.random.zipf(1.5)
    while rango > len(ZONAS):
        rango = np.random.zipf(1.5)
    return ZONAS[rango - 1]

def simular_trafico(distribucion="uniforme", iteraciones=100):
    print(f"\n--- Iniciando ráfaga de {iteraciones} consultas ({distribucion.upper()}) ---")
    for i in range(iteraciones):
        inicio_ms = time.time() * 1000
        tipo_consulta = random.choice(CONSULTAS)
        zona = random.choice(ZONAS) if distribucion == "uniforme" else elegir_zona_zipf()
        if tipo_consulta == "q4":
            zona_b = random.choice(ZONAS)
            cache_key = f"{tipo_consulta}:{zona}:{zona_b}:conf=0.0"
            params = {"zone_a": zona, "zone_b": zona_b, "confidence_min": 0.0}
        else:
            cache_key = f"{tipo_consulta}:{zona}:conf=0.0"
            params = {"zone_id": zona, "bins": 5} if tipo_consulta == "q5" else {"zone_id": zona, "confidence_min": 0.0}
        respuesta_cache = cache.get(cache_key)
        if respuesta_cache:
            evento = "HIT"
            print(f"[{evento}] {cache_key}")
        else:
            evento = "MISS"
            print(f"[{evento}] {cache_key} -> Calculando en Cerebro...")
            try:
                respuesta_cerebro = requests.get(f"{RESPUESTAS_URL}/{tipo_consulta}", params=params)
                if respuesta_cerebro.status_code == 200:
                    cache.setex(cache_key, 60, json.dumps(respuesta_cerebro.json()))
            except Exception as e:
                print(f"Error conectando al cerebro: {e}")
        latencia = (time.time() * 1000) - inicio_ms
        metrica = {"tipo": evento, "consulta": tipo_consulta.upper(), "zona": zona, "tiempo_procesamiento_ms": latencia}
        try:
            requests.post(f"{DATOS_URL}/registrar", json=metrica)
        except Exception:
            pass
        time.sleep(0.1)

if __name__ == "__main__":
    limpiar_cache()
    print("Bot esperando 60 segundos a que la Caché y los Cerebros estén listos...")
    time.sleep(60)
    simular_trafico("uniforme", 100)
    simular_trafico("zipf", 100)
    print("\n¡Simulación terminada! Manteniendo contenedor vivo...")
    while True:
        time.sleep(1000)
```

**CMD final del Dockerfile**
```dockerfile
CMD ["python", "-u", "main.py"]
```

**Reconstruir el módulo**
```bash
docker compose up -d --build trafico
```

---

## Caché Redis — Decisiones de Diseño

**Límite de memoria (`--maxmemory 50mb`):** evita que Redis consuma recursos ilimitados. En sistemas distribuidos es crítico que ningún servicio "secuestre" la memoria del servidor.

**Política LRU (`--maxmemory-policy allkeys-lru`):** cuando la caché se llena, Redis descarta automáticamente el dato menos usado recientemente (*Least Recently Used*), manteniendo siempre los más populares y frescos.

**TTL de 60 segundos:** las respuestas guardadas expiran tras 60 segundos para evitar datos obsoletos.

**Cold Start (`limpiar_cache`):** al iniciar el bot se ejecuta `flushall` sobre Redis para garantizar que cada prueba parte desde cero y los resultados son comparables entre ráfagas.