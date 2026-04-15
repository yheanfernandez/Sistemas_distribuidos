from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime

app = FastAPI()

# Memoria temporal para nuestras métricas
registro_metricas = {
    "total_consultas": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "historial": []
}

class Metrica(BaseModel):
    tipo: str  # "HIT" o "MISS"
    consulta: str # "Q1", "Q2", etc.
    zona: str
    tiempo_procesamiento_ms: float

@app.post("/registrar")
def registrar_evento(metrica: Metrica):
    """Recibe un evento del Bot y lo anota en el registro."""
    registro_metricas["total_consultas"] += 1
    
    if metrica.tipo.upper() == "HIT":
        registro_metricas["cache_hits"] += 1
    elif metrica.tipo.upper() == "MISS":
        registro_metricas["cache_misses"] += 1
        
    return {"status": "registrado", "evento": metrica.tipo}

@app.get("/estadisticas")
def ver_estadisticas():
    """Devuelve el resumen de cómo va el sistema."""
    total = registro_metricas["total_consultas"]
    hits = registro_metricas["cache_hits"]
    
    hit_rate = (hits / total * 100) if total > 0 else 0.0
    
    return {
        "total_consultas": total,
        "cache_hits": hits,
        "cache_misses": registro_metricas["cache_misses"],
        "hit_rate_porcentaje": round(hit_rate, 2)
    }
