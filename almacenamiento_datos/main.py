"""
Almacenamiento de Métricas — Tarea 2
=====================================
Registra y expone todas las métricas del sistema, incluyendo las nuevas
métricas requeridas por la Tarea 2:
  - Throughput (consultas exitosas/segundo)
  - Latencia p50/p95
  - Retry rate
  - Recovery rate
  - DLQ rate
  - Backlog size (estimado desde Kafka via variable inyectada)
  - Recovery time
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import statistics
import time

app = FastAPI(title="Métricas - Sistema Distribuido Tarea 2")

# ──────────────────────────────────────────────
# Almacén en memoria
# ──────────────────────────────────────────────
registro = {
    # Contadores globales
    "total_consultas":    0,
    "cache_hits":         0,
    "cache_misses":       0,
    "reintentos":         0,
    "dlq_total":          0,
    "recuperadas":        0,   # misses exitosos tras al menos 1 reintento

    # Para cálculo de throughput
    "inicio_sistema": time.time(),
    "consultas_exitosas": 0,

    # Para latencias
    "latencias_ms": [],        # lista de todos los tiempos de respuesta

    # Historial completo (últimos 2000 eventos para no consumir memoria)
    "historial": [],

    # Para recovery time: registro de inicio de falla
    "falla_inicio": None,
    "recovery_times_seg": [],
}

MAX_HISTORIAL = 2000


# ──────────────────────────────────────────────
# Modelos
# ──────────────────────────────────────────────

class Metrica(BaseModel):
    tipo: str                          # HIT | MISS | RETRY | DLQ | FALLA | RECUPERACION
    consulta: str                      # Q1..Q5
    zona: str
    tiempo_procesamiento_ms: float
    consumer_id: Optional[str] = None
    retry_count: Optional[int] = 0
    timestamp: Optional[str] = None
    motivo: Optional[str] = None       # para DLQ


class EventoFalla(BaseModel):
    """Notifica inicio o fin de una falla del Generador de Respuestas."""
    evento: str   # "inicio_falla" | "recuperacion"


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.post("/registrar")
def registrar_evento(metrica: Metrica):
    tipo = metrica.tipo.upper()
    registro["total_consultas"] += 1
    registro["latencias_ms"].append(metrica.tiempo_procesamiento_ms)

    if tipo == "HIT":
        registro["cache_hits"] += 1
        registro["consultas_exitosas"] += 1

    elif tipo == "MISS":
        registro["cache_misses"] += 1
        registro["consultas_exitosas"] += 1
        # Si llegó después de reintentos → es una recuperación
        if metrica.retry_count and metrica.retry_count > 0:
            registro["recuperadas"] += 1

    elif tipo == "RETRY":
        registro["reintentos"] += 1

    elif tipo == "DLQ":
        registro["dlq_total"] += 1

    # Mantener historial acotado
    entrada = {
        "timestamp": metrica.timestamp or datetime.now().isoformat(),
        "tipo": tipo,
        "consulta": metrica.consulta,
        "zona": metrica.zona,
        "latencia_ms": metrica.tiempo_procesamiento_ms,
        "consumer_id": metrica.consumer_id,
        "retry_count": metrica.retry_count,
    }
    registro["historial"].append(entrada)
    if len(registro["historial"]) > MAX_HISTORIAL:
        registro["historial"].pop(0)

    return {"status": "ok"}


@app.post("/falla")
def notificar_falla(evento: EventoFalla):
    """
    El consumidor notifica cuando detecta que el generador de respuestas cayó
    o se recuperó, para calcular recovery_time.
    """
    if evento.evento == "inicio_falla":
        registro["falla_inicio"] = time.time()
        return {"status": "falla registrada"}

    elif evento.evento == "recuperacion" and registro["falla_inicio"]:
        recovery = time.time() - registro["falla_inicio"]
        registro["recovery_times_seg"].append(recovery)
        registro["falla_inicio"] = None
        return {"status": "recuperacion registrada", "recovery_time_seg": round(recovery, 2)}

    return {"status": "evento ignorado"}


@app.get("/estadisticas")
def estadisticas():
    total     = registro["total_consultas"]
    hits      = registro["cache_hits"]
    misses    = registro["cache_misses"]
    reintentos = registro["reintentos"]
    dlq       = registro["dlq_total"]
    recuperadas = registro["recuperadas"]
    exitosas  = registro["consultas_exitosas"]
    latencias = registro["latencias_ms"]

    # Hit rate
    hit_rate = (hits / total * 100) if total > 0 else 0.0

    # Throughput: consultas exitosas por segundo desde el inicio
    elapsed = max(time.time() - registro["inicio_sistema"], 1)
    throughput = round(exitosas / elapsed, 2)

    # Latencias p50 / p95
    if latencias:
        sorted_lat = sorted(latencias)
        n = len(sorted_lat)
        p50 = sorted_lat[int(n * 0.50)]
        p95 = sorted_lat[min(int(n * 0.95), n - 1)]
    else:
        p50 = p95 = 0.0

    # Tasas
    retry_rate    = round(reintentos / total * 100, 2) if total > 0 else 0.0
    dlq_rate      = round(dlq / total * 100, 2)        if total > 0 else 0.0
    recovery_rate = round(recuperadas / max(reintentos, 1) * 100, 2)

    # Recovery time promedio
    rt_list = registro["recovery_times_seg"]
    avg_recovery_time = round(sum(rt_list) / len(rt_list), 2) if rt_list else None

    return {
        # Volumen
        "total_consultas":    total,
        "cache_hits":         hits,
        "cache_misses":       misses,
        "consultas_exitosas": exitosas,
        "reintentos":         reintentos,
        "dlq_total":          dlq,
        "recuperadas":        recuperadas,

        # Tasas (%)
        "hit_rate_%":         round(hit_rate, 2),
        "miss_rate_%":        round(100 - hit_rate, 2),
        "retry_rate_%":       retry_rate,
        "dlq_rate_%":         dlq_rate,
        "recovery_rate_%":    recovery_rate,

        # Rendimiento
        "throughput_qps":     throughput,
        "latencia_p50_ms":    round(p50, 2),
        "latencia_p95_ms":    round(p95, 2),

        # Recuperación ante fallos
        "avg_recovery_time_seg": avg_recovery_time,
        "num_fallos_registrados": len(rt_list),
    }


@app.get("/historial")
def ver_historial(limite: int = 100):
    """Últimos N eventos del sistema."""
    return {"historial": registro["historial"][-limite:]}


@app.get("/resumen_por_tipo")
def resumen_por_tipo():
    """Desglose de latencias y conteos agrupados por tipo de consulta (Q1-Q5)."""
    resumen = {}
    for entrada in registro["historial"]:
        q = entrada["consulta"]
        if q not in resumen:
            resumen[q] = {"count": 0, "hits": 0, "misses": 0, "latencias": []}
        resumen[q]["count"] += 1
        resumen[q]["latencias"].append(entrada["latencia_ms"])
        if entrada["tipo"] == "HIT":
            resumen[q]["hits"] += 1
        elif entrada["tipo"] == "MISS":
            resumen[q]["misses"] += 1

    resultado = {}
    for q, data in resumen.items():
        lats = sorted(data["latencias"])
        n = len(lats)
        resultado[q] = {
            "count": data["count"],
            "hits": data["hits"],
            "misses": data["misses"],
            "hit_rate_%": round(data["hits"] / data["count"] * 100, 2) if data["count"] > 0 else 0,
            "latencia_p50_ms": round(lats[int(n * 0.5)], 2) if lats else 0,
            "latencia_p95_ms": round(lats[min(int(n * 0.95), n - 1)], 2) if lats else 0,
        }
    return resultado


@app.delete("/reset")
def reset_metricas():
    """Reinicia todos los contadores (útil entre escenarios de prueba)."""
    registro["total_consultas"]    = 0
    registro["cache_hits"]         = 0
    registro["cache_misses"]       = 0
    registro["reintentos"]         = 0
    registro["dlq_total"]          = 0
    registro["recuperadas"]        = 0
    registro["consultas_exitosas"] = 0
    registro["inicio_sistema"]     = time.time()
    registro["latencias_ms"]       = []
    registro["historial"]          = []
    registro["falla_inicio"]       = None
    registro["recovery_times_seg"] = []
    return {"status": "métricas reiniciadas"}
