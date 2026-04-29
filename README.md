# Tarea 1 - Sistemas Distribuidos: Sistema de Consultas con Caché

Sistema distribuido que simula tráfico de consultas sobre datos de edificios (Google Open Buildings) en zonas de Santiago, con caché Redis y registro de métricas.

---

## Estructura del Proyecto

```
/Sistemas_distribuidos
│
├── /generador_trafico
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── /generador_respuestas
│   ├── dataset_edificios.csv.gz   <-- (Aquí van los datos de Google Open Buildings)
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── /almacenamiento_datos
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

### 1. Encender el sistema completo

```bash
docker compose up -d --build
```

- `--build`: construye las imágenes desde cero leyendo los Dockerfiles.
- `-d`: modo *detached*, levanta los servicios en segundo plano.

### 2. Verificar que todo esté corriendo

```bash
docker compose ps
```

Deberías ver los 4 servicios (`cache`, `datos`, `respuestas`, `trafico`) con estado `Up`.

### 3. Ver los resultados en tiempo real

```bash
docker logs -f modulo_trafico
```

El bot espera **90 segundos** al iniciar para que los demás servicios estén listos, luego ejecuta las dos ráfagas e imprime los resultados directamente en consola.

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

| ID | Sector | lat_min | lat_max | lon_min | lon_max | Área (km²) |
|----|--------|---------|---------|---------|---------|------------|
| Z1 | Providencia | -33.445 | -33.420 | -70.640 | -70.600 | 9.5 |
| Z2 | Las Condes | -33.420 | -33.390 | -70.600 | -70.550 | 20.0 |
| Z3 | Maipú | -33.530 | -33.490 | -70.790 | -70.740 | 35.0 |
| Z4 | Santiago Centro | -33.470 | -33.430 | -70.670 | -70.630 | 15.0 |
| Z5 | Pudahuel | -33.460 | -33.430 | -70.810 | -70.760 | 40.0 |

**Endpoints disponibles**

| Endpoint | Descripción |
|----------|-------------|
| `GET /q1` | Conteo de edificios en una zona con confianza mínima |
| `GET /q2` | Área promedio y total de edificios |
| `GET /q3` | Densidad de edificios por km² |
| `GET /q4` | Comparación de densidad entre dos zonas |
| `GET /q5` | Distribución de scores de confianza (histograma) |

**CMD final del Dockerfile**

```
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Reconstruir el módulo**

```bash
docker compose up -d --build respuestas
```

---

### `almacenamiento_datos` — El Cuaderno

Servidor FastAPI que recibe y almacena métricas de cada consulta (hits, misses, latencia). Calcula percentiles de latencia y throughput en tiempo real.

**requirements.txt**

```
fastapi
uvicorn
numpy
```

**Endpoints disponibles**

| Endpoint | Descripción |
|----------|-------------|
| `POST /registrar` | Registra un evento HIT o MISS con su latencia |
| `GET /estadisticas` | Devuelve el resumen completo del sistema |
| `DELETE /reset` | Reinicia todas las métricas a cero (usado entre ráfagas) |

**Respuesta de `/estadisticas`**

```json
{
  "total_consultas": 5000,
  "cache_hits": 4321,
  "cache_misses": 679,
  "hit_rate_porcentaje": 86.42,
  "miss_rate_porcentaje": 13.58,
  "latencia_p50_ms": 2.1,
  "latencia_p95_ms": 45.3,
  "throughput_req_por_segundo": 8.7
}
```

**CMD final del Dockerfile**

```
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Reconstruir el módulo**

```bash
docker compose up -d --build datos
```

---

### `generador_trafico` — El Bot

Simula dos ráfagas de **5000 consultas** cada una, usando caché Redis para interceptar respuestas repetidas antes de llegar al Cerebro. Entre las dos ráfagas se reinician automáticamente tanto las métricas como la caché (Cold Start).

**requirements.txt**

```
requests
redis
numpy
```

**Parámetros de confianza usados**

```python
CONFIDENCES = [0.0, 0.25, 0.5, 0.75]
```

Cada consulta elige aleatoriamente uno de estos valores, ampliando el espacio de claves de caché posibles.

**Distribuciones de tráfico**

| Distribución | Descripción |
|--------------|-------------|
| Uniforme | Zonas y consultas elegidas al azar de forma equiprobable |
| Zipf (s=1.5) | Pocas zonas concentran la mayoría del tráfico, simulando comportamiento real |

**Formato de las cache keys**

| Consulta | Cache Key |
|----------|-----------|
| Q1 | `count:{zona}:conf={conf}` |
| Q2 | `area:{zona}:conf={conf}` |
| Q3 | `density:{zona}:conf={conf}` |
| Q4 | `compare:density:{zona_a}:{zona_b}:conf={conf}` |
| Q5 | `confidence_dist:{zona}:bins=5` |

**Flujo de cada consulta**

1. El bot elige zona, tipo de consulta y nivel de confianza aleatoriamente.
2. Construye la cache key y busca la respuesta en Redis.
3. **HIT**: usa la respuesta guardada directamente.
4. **MISS**: consulta al Cerebro (`http://respuestas:8000`), guarda el resultado en Redis con TTL de 60 segundos.
5. Registra la métrica (tipo, zona, latencia) en `almacenamiento_datos`.

**Secuencia de ejecución**

```
Cold Start (flushall)
    └─> Espera 90 segundos (servicios listos)
        └─> Ráfaga UNIFORME (5000 consultas)
            └─> Imprime estadísticas
                └─> DELETE /reset (reinicia métricas)
                    └─> Cold Start (flushall)
                        └─> Ráfaga ZIPF (5000 consultas)
                            └─> Imprime estadísticas finales
```

**CMD final del Dockerfile**

```
CMD ["python", "-u", "main.py"]
```

**Reconstruir el módulo**

```bash
docker compose up -d --build trafico
```

---

## Caché Redis — Decisiones de Diseño

**Límite de memoria (`--maxmemory 50mb`):** evita que Redis consuma recursos ilimitados. Se puede cambiar a `200mb` o `500mb` para comparar el impacto en el hit rate.

**Política LRU (`--maxmemory-policy allkeys-lru`):** cuando la caché se llena, Redis descarta automáticamente el dato menos usado recientemente (*Least Recently Used*). Se puede cambiar a `allkeys-lfu` o `allkeys-random` para comparar políticas.

**TTL de 60 segundos:** las respuestas guardadas expiran tras 60 segundos para evitar datos obsoletos.

**Cold Start (`limpiar_cache`):** se ejecuta `flushall` sobre Redis antes de cada ráfaga para garantizar que cada prueba parte desde cero y los resultados son comparables.

**Configuración actual en `docker-compose.yml`:**

```yaml
command: redis-server --maxmemory 50mb --maxmemory-policy allkeys-lru
```
