"""
Generador de Tráfico — Tarea 2
================================
Rol: Kafka Producer puro.
- Ya NO interactúa directamente con Redis ni con el Generador de Respuestas.
- Genera consultas Q1-Q5 con distribución Zipf o Uniforme y las publica en el
  topic 'consultas' de Kafka.
- Soporta escenario 'spike': ráfaga repentina de alta carga en un intervalo corto.
"""

import os
import time
import uuid
import random
import json
import numpy as np
from datetime import datetime, timezone
from confluent_kafka import Producer

# ──────────────────────────────────────────────
# Configuración desde variables de entorno
# ──────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
ESCENARIO = os.getenv("ESCENARIO", "zipf")        # uniform | zipf | spike
NUM_CONSULTAS = int(os.getenv("NUM_CONSULTAS", "500"))
TOPIC_PRINCIPAL = "consultas"

ZONAS = ["Z1", "Z2", "Z3", "Z4", "Z5"]
CONSULTAS = ["q1", "q2", "q3", "q4", "q5"]


def crear_producer() -> Producer:
    conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        # Garantía de entrega: esperar ACK del broker
        "acks": "all",
    }
    return Producer(conf)


def delivery_report(err, msg):
    """Callback que se llama cuando Kafka confirma (o rechaza) un mensaje."""
    if err:
        print(f"[PRODUCER] Error al enviar mensaje: {err}")


def construir_consulta(tipo: str, zona: str) -> dict:
    """Construye el payload de una consulta con todos los metadatos necesarios."""
    consulta = {
        "id": str(uuid.uuid4()),
        "tipo": tipo,
        "zona": zona,
        "confidence_min": 0.0,
        "bins": 5,
        "timestamp_creacion": datetime.now(timezone.utc).isoformat(),
        "retry_count": 0,
    }
    # Q4 necesita dos zonas
    if tipo == "q4":
        zona_b = random.choice([z for z in ZONAS if z != zona])
        consulta["zona_b"] = zona_b
    return consulta


def elegir_zona_zipf() -> str:
    """Distribución Zipf (α=1.5): pocas zonas concentran la mayoría del tráfico."""
    while True:
        val = np.random.zipf(1.5)
        if val <= len(ZONAS):
            return ZONAS[val - 1]


def elegir_zona_uniforme() -> str:
    return random.choice(ZONAS)


def publicar_consulta(producer: Producer, consulta: dict):
    """Serializa y publica una consulta en el topic principal de Kafka."""
    producer.produce(
        TOPIC_PRINCIPAL,
        key=consulta["id"],
        value=json.dumps(consulta),
        callback=delivery_report,
    )
    # poll() para activar los callbacks de entrega sin bloquear
    producer.poll(0)


def rafaga_normal(producer: Producer, distribucion: str, n: int, delay: float = 0.05):
    """Genera N consultas con la distribución indicada."""
    print(f"\n[TRAFICO] Iniciando ráfaga {distribucion.upper()} — {n} consultas")
    for i in range(n):
        tipo = random.choice(CONSULTAS)
        zona = elegir_zona_zipf() if distribucion == "zipf" else elegir_zona_uniforme()
        consulta = construir_consulta(tipo, zona)
        publicar_consulta(producer, consulta)
        if i % 50 == 0:
            print(f"[TRAFICO] Publicadas {i}/{n} consultas...")
        time.sleep(delay)
    producer.flush()
    print(f"[TRAFICO] Ráfaga {distribucion.upper()} completada — {n} mensajes en Kafka")


def rafaga_spike(producer: Producer, n_base: int = 100, n_spike: int = 500):
    """
    Escenario spike: tráfico normal → pico repentino → vuelta a normal.
    Simula una sobrecarga inesperada para evaluar backlog y recuperación.
    """
    print("\n[TRAFICO] Escenario SPIKE iniciado")

    print(f"[TRAFICO] Fase 1: tráfico normal ({n_base} consultas)")
    rafaga_normal(producer, "uniform", n_base, delay=0.1)

    print(f"\n[TRAFICO] Fase 2: SPIKE — {n_spike} consultas sin delay")
    for i in range(n_spike):
        tipo = random.choice(CONSULTAS)
        zona = elegir_zona_zipf()
        consulta = construir_consulta(tipo, zona)
        publicar_consulta(producer, consulta)
        if i % 100 == 0:
            print(f"[TRAFICO] Spike: {i}/{n_spike}...")
    producer.flush()
    print(f"[TRAFICO] Spike completado — {n_spike} mensajes publicados sin delay")

    print(f"\n[TRAFICO] Fase 3: vuelta a tráfico normal ({n_base} consultas)")
    rafaga_normal(producer, "uniform", n_base, delay=0.1)


if __name__ == "__main__":
    print(f"[TRAFICO] Esperando 30s para que Kafka esté listo...")
    time.sleep(30)

    producer = crear_producer()
    print(f"[TRAFICO] Producer conectado a {KAFKA_BOOTSTRAP_SERVERS}")
    print(f"[TRAFICO] Escenario: {ESCENARIO} | Consultas: {NUM_CONSULTAS}")

    if ESCENARIO == "spike":
        rafaga_spike(producer, n_base=100, n_spike=NUM_CONSULTAS)
    elif ESCENARIO == "zipf":
        rafaga_normal(producer, "zipf", NUM_CONSULTAS)
    else:
        rafaga_normal(producer, "uniform", NUM_CONSULTAS)

    print("\n[TRAFICO] Simulación completada. Contenedor en espera...")
    while True:
        time.sleep(1000)
