"""
Kafka Consumer — Tarea 2
=========================
Rol: Núcleo del sistema asíncrono.

Flujo principal:
  1. Consume mensajes del topic 'consultas'
  2. Consulta Redis (caché)
     - HIT  → registra métrica, listo
     - MISS → llama al Generador de Respuestas
        - Éxito  → guarda en caché, registra métrica
        - Falla  → reenvía a 'consultas-retry' (si retry_count < MAX_REINTENTOS)
                   o envía a 'consultas-dlq'  (si retry_count >= MAX_REINTENTOS)

Consumer Group: 'grupo_procesadores'
  Todos los consumidores comparten el mismo group_id, Kafka distribuye
  automáticamente las particiones entre ellos (balanceo de carga).
"""

import os
import time
import json
import redis
import requests
import socket
from datetime import datetime, timezone
from confluent_kafka import Consumer, Producer, KafkaError, KafkaException

# Configuración desde variables de entorno
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
REDIS_HOST              = os.getenv("REDIS_HOST", "cache")
RESPUESTAS_URL          = os.getenv("RESPUESTAS_URL", "http://respuestas:8000")
DATOS_URL               = os.getenv("DATOS_URL", "http://datos:8000")
MAX_REINTENTOS          = int(os.getenv("MAX_REINTENTOS", "3"))
PROB_FALLA              = float(os.getenv("PROB_FALLA", "0.0"))  # Para tests: 0.3 = 30% falla artificial
CACHE_TTL               = int(os.getenv("CACHE_TTL", "60"))

TOPIC_PRINCIPAL = "consultas"
TOPIC_RETRY     = "consultas-retry"
TOPIC_DLQ       = "consultas-dlq"

# Identificador único de esta instancia (útil con múltiples réplicas)
CONSUMER_ID = socket.gethostname()


# Clientes

def crear_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        # Todos los consumers comparten este group_id → Kafka balancea particiones
        "group.id": "grupo_procesadores",
        "auto.offset.reset": "earliest",
        # Desactivamos autocommit para hacer commit manual solo tras procesar
        "enable.auto.commit": False,
    })


def crear_producer() -> Producer:
    return Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "acks": "all",
    })


def crear_redis() -> redis.Redis:
    return redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)


# Lógica de caché

def construir_cache_key(consulta: dict) -> str:
    tipo = consulta["tipo"]
    zona = consulta["zona"]
    if tipo == "q4":
        zona_b = consulta.get("zona_b", "Z1")
        return f"compare:density:{zona}:{zona_b}:conf={consulta['confidence_min']}"
    elif tipo == "q5":
        return f"confidence_dist:{zona}:bins={consulta['bins']}"
    elif tipo == "q1":
        return f"count:{zona}:conf={consulta['confidence_min']}"
    elif tipo == "q2":
        return f"area:{zona}:conf={consulta['confidence_min']}"
    elif tipo == "q3":
        return f"density:{zona}:conf={consulta['confidence_min']}"
    return f"{tipo}:{zona}"


def buscar_en_cache(r: redis.Redis, key: str):
    """Retorna el valor si existe en caché, None si no."""
    val = r.get(key)
    if val:
        return json.loads(val)
    return None


def guardar_en_cache(r: redis.Redis, key: str, valor: dict):
    r.setex(key, CACHE_TTL, json.dumps(valor))


# Llamada al Generador de Respuestas

def llamar_generador(consulta: dict) -> dict | None:
    """
    Llama al endpoint correspondiente del Generador de Respuestas.
    Retorna el resultado o None si hay error.
    """
    import random
    # Falla artificial para pruebas (controlada por PROB_FALLA)
    if PROB_FALLA > 0 and random.random() < PROB_FALLA:
        raise Exception(f"Falla simulada artificial (prob={PROB_FALLA})")

    tipo = consulta["tipo"]
    try:
        if tipo == "q4":
            params = {
                "zone_a": consulta["zona"],
                "zone_b": consulta.get("zona_b", "Z1"),
                "confidence_min": consulta["confidence_min"],
            }
        elif tipo == "q5":
            params = {"zone_id": consulta["zona"], "bins": consulta["bins"]}
        else:
            params = {
                "zone_id": consulta["zona"],
                "confidence_min": consulta["confidence_min"],
            }

        resp = requests.get(
            f"{RESPUESTAS_URL}/{tipo}",
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()

    except Exception as e:
        raise Exception(f"Error llamando al generador ({tipo}): {e}")


# Registro de métricas

def registrar_metrica(evento: str, consulta: dict, latencia_ms: float, extra: dict = None):
    """Envía una métrica al módulo de almacenamiento. No bloquea si falla."""
    payload = {
        "tipo": evento,
        "consulta": consulta["tipo"].upper(),
        "zona": consulta["zona"],
        "tiempo_procesamiento_ms": latencia_ms,
        "consumer_id": CONSUMER_ID,
        "retry_count": consulta.get("retry_count", 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    try:
        requests.post(f"{DATOS_URL}/registrar", json=payload, timeout=2)
    except Exception:
        pass  # Las métricas no deben bloquear el flujo principal


# Manejo de reintentos y DLQ

def reenviar_a_retry(producer: Producer, consulta: dict):
    """Incrementa retry_count y reenvía al topic de reintentos."""
    consulta["retry_count"] = consulta.get("retry_count", 0) + 1
    consulta["ultimo_intento"] = datetime.now(timezone.utc).isoformat()
    producer.produce(
        TOPIC_RETRY,
        key=consulta["id"],
        value=json.dumps(consulta),
    )
    producer.poll(0)
    print(f"[RETRY] Consulta {consulta['id'][:8]}... → retry #{consulta['retry_count']}")


def enviar_a_dlq(producer: Producer, consulta: dict, motivo: str):
    """Envía la consulta a la Dead Letter Queue con el motivo del fallo."""
    consulta["dlq_motivo"] = motivo
    consulta["dlq_timestamp"] = datetime.now(timezone.utc).isoformat()
    producer.produce(
        TOPIC_DLQ,
        key=consulta["id"],
        value=json.dumps(consulta),
    )
    producer.flush()
    print(f"[DLQ] Consulta {consulta['id'][:8]}... enviada a DLQ. Motivo: {motivo}")
    registrar_metrica("DLQ", consulta, 0, {"motivo": motivo})


# Procesamiento de una consulta

def procesar_consulta(consulta: dict, r: redis.Redis, producer: Producer):
    """
    Lógica completa de procesamiento de una sola consulta.
    Retorna True si se procesó con éxito (hit o miss+respuesta),
    False si hubo error y se reenció a retry/DLQ.
    """
    inicio = time.time()
    cache_key = construir_cache_key(consulta)

    # 1. Intentar cache hit
    resultado = buscar_en_cache(r, cache_key)
    if resultado is not None:
        latencia = (time.time() - inicio) * 1000
        print(f"[HIT]  {cache_key} ({latencia:.1f}ms)")
        registrar_metrica("HIT", consulta, latencia)
        return True

    # 2. Cache miss → llamar al Generador de Respuestas
    try:
        resultado = llamar_generador(consulta)
        guardar_en_cache(r, cache_key, resultado)
        latencia = (time.time() - inicio) * 1000
        print(f"[MISS] {cache_key} → calculado ({latencia:.1f}ms)")
        registrar_metrica("MISS", consulta, latencia)
        return True

    except Exception as e:
        latencia = (time.time() - inicio) * 1000
        retry_count = consulta.get("retry_count", 0)

        if retry_count < MAX_REINTENTOS:
            # Todavía tiene intentos disponibles → topic de reintento
            reenviar_a_retry(producer, consulta)
            registrar_metrica("RETRY", consulta, latencia, {"error": str(e)})
        else:
            # Agotó todos los reintentos → DLQ
            enviar_a_dlq(producer, consulta, str(e))

        return False


# Loop principal del consumidor

def ejecutar_consumer():
    print(f"[CONSUMER {CONSUMER_ID}] Iniciando...")
    print(f"  Kafka:    {KAFKA_BOOTSTRAP_SERVERS}")
    print(f"  Redis:    {REDIS_HOST}")
    print(f"  Max reintentos: {MAX_REINTENTOS}")

    consumer = crear_consumer()
    producer = crear_producer()
    r        = crear_redis()

    # Suscribirse a topic principal Y al topic de retry
    # (mismo consumer group: Kafka asignará particiones automáticamente)
    consumer.subscribe([TOPIC_PRINCIPAL, TOPIC_RETRY])
    print(f"[CONSUMER {CONSUMER_ID}] Suscrito a: {TOPIC_PRINCIPAL}, {TOPIC_RETRY}")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # Fin de partición — normal, seguimos esperando
                    continue
                else:
                    raise KafkaException(msg.error())

            # Deserializar el mensaje
            try:
                consulta = json.loads(msg.value().decode("utf-8"))
            except json.JSONDecodeError as e:
                print(f"[CONSUMER] Error deserializando mensaje: {e}")
                consumer.commit(message=msg)
                continue

            topic_origen = msg.topic()
            print(f"[CONSUMER {CONSUMER_ID}] Procesando desde '{topic_origen}': "
                  f"id={consulta.get('id','?')[:8]}... "
                  f"tipo={consulta.get('tipo')} zona={consulta.get('zona')} "
                  f"retry={consulta.get('retry_count', 0)}")

            procesar_consulta(consulta, r, producer)

            # Commit manual: solo confirmamos que procesamos DESPUÉS de terminar
            consumer.commit(message=msg)

    except KeyboardInterrupt:
        print(f"\n[CONSUMER {CONSUMER_ID}] Detenido por el usuario.")
    finally:
        consumer.close()
        print(f"[CONSUMER {CONSUMER_ID}] Conexión cerrada.")


if __name__ == "__main__":
    # Esperar a que Kafka esté completamente disponible
    print("[CONSUMER] Esperando 20s para que Kafka inicialice...")
    time.sleep(20)
    ejecutar_consumer()
