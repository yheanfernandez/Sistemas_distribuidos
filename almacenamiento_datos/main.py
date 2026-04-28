from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np
import time

app = FastAPI()

# Memoria temporal para nuestras métricas
registro_metricas = {
    "total_consultas": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "latencias": [] #Aquí guardaremos todos los tiempos para calcular p50 y p95
}

# Registramos cuándo arrancó el sistema para poder calcular el Throughput (consultas por segundo)
inicio_sistema = time.time()

class Metrica(BaseModel):
    tipo: str  # "HIT" o "MISS"
    consulta: str # "Q1", "Q2", etc.
    zona: str
    tiempo_procesamiento_ms: float

@app.post("/registrar")
def registrar_evento(metrica: Metrica):
    """Recibe un evento del Bot y lo anota en el registro."""
    registro_metricas["total_consultas"] += 1
    
    # 1. GUARDAMOS LA LATENCIA (Vital para la rúbrica)
    registro_metricas["latencias"].append(metrica.tiempo_procesamiento_ms)
    
    if metrica.tipo.upper() == "HIT":
        registro_metricas["cache_hits"] += 1
    elif metrica.tipo.upper() == "MISS":
        registro_metricas["cache_misses"] += 1
        
    return {"status": "registrado", "evento": metrica.tipo}

@app.get("/estadisticas")
def ver_estadisticas():
    """Devuelve el resumen de cómo va el sistema con las métricas del profesor."""
    total = registro_metricas["total_consultas"]
    hits = registro_metricas["cache_hits"]
    misses = registro_metricas["cache_misses"]
    latencias = registro_metricas["latencias"]
    
    # Cálculos básicos
    hit_rate = (hits / total * 100) if total > 0 else 0.0
    miss_rate = (misses / total * 100) if total > 0 else 0.0
    
    # 2. CÁLCULO DE PERCENTILES (p50 y p95 exigidos)
    if len(latencias) > 0:
        p50 = np.percentile(latencias, 50)
        p95 = np.percentile(latencias, 95)
    else:
        p50 = 0.0
        p95 = 0.0
        
    # 3. CÁLCULO DE THROUGHPUT (Consultas procesadas por segundo)
    tiempo_transcurrido_segundos = time.time() - inicio_sistema
    throughput = total / tiempo_transcurrido_segundos if tiempo_transcurrido_segundos > 0 else 0.0
    
    return {
        "total_consultas": total,
        "cache_hits": hits,
        "cache_misses": misses,
        "hit_rate_porcentaje": round(hit_rate, 2),
        "miss_rate_porcentaje": round(miss_rate, 2),
        "latencia_p50_ms": round(p50, 2),
        "latencia_p95_ms": round(p95, 2),
        "throughput_req_por_segundo": round(throughput, 2)
    }
