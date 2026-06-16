# Tarea 2 — Sistemas Distribuidos 2026-1
## Procesamiento y Fallback con Apache Kafka

**Universidad Diego Portales — Ingeniería Civil Informática y Telecomunicaciones**  
**Alumnos:** Yhean Fernández · Rodrigo Jeria  
**Profesor:** Nicolás Hidalgo

---

## Descripción

Evolución de la plataforma distribuida de la Tarea 1, incorporando **Apache Kafka** como sistema de mensajería asíncrona para garantizar tolerancia a fallos y escalamiento horizontal. El sistema analiza consultas geoespaciales sobre el dataset Google Open Buildings (Región Metropolitana de Santiago), con mecanismos de caché Redis, reintentos automáticos y Dead Letter Queue.

---

## Estructura del Proyecto

```
/
├── generador_trafico/        # Kafka Producer — genera consultas Q1-Q5
│   ├── main.py               # Distribuciones: Zipf, Uniforme, Spike
│   ├── requirements.txt
│   └── Dockerfile
│
├── kafka_consumer/           # Consumidor Kafka — módulo central de la Tarea 2
│   ├── main.py               # Caché + reintentos + DLQ
│   ├── requirements.txt
│   └── Dockerfile
│
├── generador_respuestas/     # FastAPI — procesa consultas Q1-Q5 desde dataset
│   ├── main.py
│   ├── dataset_edificios.csv.gz   ← dataset aquí (ver sección Dataset)
│   ├── requirements.txt
│   └── Dockerfile
│
├── almacenamiento_datos/     # FastAPI — almacena y expone métricas del sistema
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
│
└── docker-compose.yml        # Orquestación completa del sistema
```

---

## Requisitos

- Docker >= 24.0
- Docker Compose >= 2.0
- Dataset `dataset_edificios.csv.gz` (Google Open Buildings — ver sección Dataset)

---

## Dataset

Descargar el dataset desde [Google Open Buildings](https://sites.research.google/gr/open-buildings/) correspondiente a la Región Metropolitana de Santiago y colocarlo en:

```
generador_respuestas/dataset_edificios.csv.gz
```

El sistema lo carga automáticamente en memoria al iniciar. Se soportan tanto `.csv` como `.csv.gz`.

---

## Instalación y Despliegue

### 1. Clonar el repositorio

```bash
git clone https://github.com/yheanfernandez/Sistemas_distribuidos.git
cd Sistemas_distribuidos
git checkout rodri
```

### 2. Colocar el dataset

```bash
cp /ruta/a/dataset_edificios.csv.gz generador_respuestas/
```

### 3. Levantar el sistema

```bash
docker compose up -d --build
```

### 4. Verificar que todo esté corriendo

```bash
docker compose ps
```

Salida esperada:
```
NAME                                     STATUS
zookeeper                                Up (healthy)
kafka                                    Up (healthy)
kafka_init                               Exited (0)     ← normal, solo crea topics
redis_cache                              Up
modulo_datos                             Up
modulo_respuestas                        Up (healthy)
sistemas_distribuidos-kafka_consumer-1   Up
modulo_trafico                           Up
```

### 5. Verificar topics Kafka

```bash
docker exec kafka kafka-topics --bootstrap-server localhost:9092 --list
```

Debe mostrar: `consultas`, `consultas-retry`, `consultas-dlq`

---

## Arquitectura

```
Generador de Tráfico
        │
        │ publica en
        ▼
   [consultas]  ←──────────────────────────────────┐
    Topic Kafka                                     │
        │                                           │
        │ consume                              reintentos
        ▼                                           │
  Kafka Consumer ──── Redis (caché) ──── HIT → Métricas
        │                  │
        │ MISS             │ no encontrado
        ▼                  │
  Generador de   ◄─────────┘
   Respuestas
        │
        ├── Éxito → guarda en caché → Métricas
        │
        └── Falla → [consultas-retry] → (max reintentos) → [consultas-dlq]
```

### Topics Kafka

| Topic | Particiones | Descripción |
|---|---|---|
| `consultas` | 3 | Topic principal — todas las consultas entrantes |
| `consultas-retry` | 3 | Consultas que fallaron temporalmente |
| `consultas-dlq` | 1 | Dead Letter Queue — consultas sin solución |

---

## Escenarios de Evaluación

### Escenario 1 — Sistema normal (Zipf)

```bash
# El sistema corre con distribución Zipf por defecto
curl -X DELETE http://localhost:8000/reset
sleep 60
curl http://localhost:8000/estadisticas | python3 -m json.tool
```

### Escenario 2 — Distribución Uniforme

Editar `docker-compose.yml`: cambiar `ESCENARIO=uniform`, luego:

```bash
docker compose up -d --build trafico
curl -X DELETE http://localhost:8000/reset
sleep 60
curl http://localhost:8000/estadisticas | python3 -m json.tool
```

### Escenario 3 — Falla temporal del Generador de Respuestas

```bash
# Calentar caché primero
sleep 60
curl -X DELETE http://localhost:8000/reset

# Simular falla
docker compose stop respuestas

# Ver reintentos y DLQ en tiempo real
docker compose logs -f --since 5s kafka_consumer

# Recuperar servicio
docker compose start respuestas
sleep 30
curl http://localhost:8000/estadisticas | python3 -m json.tool
```

### Escenario 4 — Multi-consumer (escalamiento horizontal)

```bash
curl -X DELETE http://localhost:8000/reset
docker compose up -d --scale kafka_consumer=3
docker compose ps   # verificar 3 instancias
sleep 60
curl http://localhost:8000/estadisticas | python3 -m json.tool
```

### Escenario 5 — Spike de tráfico

Editar `docker-compose.yml`: cambiar `ESCENARIO=spike`, luego:

```bash
docker compose up -d --build trafico
curl -X DELETE http://localhost:8000/reset
sleep 90
curl http://localhost:8000/estadisticas | python3 -m json.tool
```

---

## Endpoints de Métricas

Base URL: `http://localhost:8000`

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/estadisticas` | Resumen completo: hit rate, throughput, latencias, reintentos, DLQ |
| GET | `/historial?limite=N` | Últimos N eventos del sistema |
| GET | `/resumen_por_tipo` | Métricas agrupadas por tipo de consulta (Q1-Q5) |
| DELETE | `/reset` | Reiniciar todos los contadores |
| POST | `/falla` | Notificar inicio/fin de falla para calcular recovery time |

---

## Variables de Entorno

### `kafka_consumer`

| Variable | Default | Descripción |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Dirección del broker Kafka |
| `REDIS_HOST` | `cache` | Host de Redis |
| `MAX_REINTENTOS` | `3` | Intentos antes de enviar a DLQ |
| `CACHE_TTL` | `60` | TTL en segundos de entradas en caché |
| `PROB_FALLA` | `0.0` | Probabilidad de falla artificial (0.0-1.0) |

### `generador_trafico`

| Variable | Default | Descripción |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Dirección del broker Kafka |
| `ESCENARIO` | `zipf` | Distribución de tráfico: `zipf`, `uniform`, `spike` |
| `NUM_CONSULTAS` | `500` | Consultas por ráfaga |

---

## Comandos Útiles

```bash
# Ver logs de un servicio específico
docker compose logs -f kafka_consumer
docker compose logs -f respuestas
docker compose logs -f trafico

# Ver solo logs recientes
docker compose logs -f --since 10s kafka_consumer

# Reiniciar un servicio
docker compose restart trafico

# Escalar consumers
docker compose up -d --scale kafka_consumer=3

# Inspeccionar topics Kafka
docker exec kafka kafka-topics --bootstrap-server localhost:9092 --list
docker exec kafka kafka-consumer-groups --bootstrap-server localhost:9092 --list

# Detener todo
docker compose down

# Detener y limpiar volúmenes
docker compose down -v
```

---

## Repositorio

[https://github.com/yheanfernandez/Sistemas_distribuidos](https://github.com/yheanfernandez/Sistemas_distribuidos)