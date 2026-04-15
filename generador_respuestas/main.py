from fastapi import FastAPI, HTTPException
import pandas as pd
import numpy as np
import os

app = FastAPI()

# Áreas aproximadas en km2 para Q3
ZONAS_KM2 = {
    "Z1": 9.5,   # Providencia
    "Z2": 20.0,  # Las Condes
    "Z3": 35.0,  # Maipú
    "Z4": 15.0,  # Santiago Centro
    "Z5": 40.0   # Pudahuel
}

# Bounding boxes extraídas del enunciado oficial de la tarea
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
    """Se ejecuta al iniciar el contenedor. Lee el CSV y filtra por zonas."""
    ruta_csv = "dataset_edificios.csv.gz"
    
    if not os.path.exists(ruta_csv):
        print(f"¡ADVERTENCIA! No se encontró el archivo {ruta_csv}. Asegúrate de subirlo a la carpeta.")
        return
        
    print(f"Cargando dataset real desde {ruta_csv}...")
    # Leemos el archivo completo con Pandas
    df_completo = pd.read_csv(ruta_csv)
    
    # Filtramos los edificios y los guardamos en su zona correspondiente
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

# --- ENDPOINTS DE CONSULTAS (Q1 a Q5) ---

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
        "consulta": "Q2",
        "zone_id": zone_id,
        "avg_area": float(edificios_validos['area_in_meters'].mean()),
        "total_area": float(edificios_validos['area_in_meters'].sum()),
        "n": len(edificios_validos)
    }

@app.get("/q3")
def q3_density(zone_id: str, confidence_min: float = 0.0):
    # La densidad necesita el conteo (Q1) dividido por el area total de la zona
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
    
    # Calculamos el histograma con numpy
    counts, edges = np.histogram(scores, bins=bins, range=(0.0, 1.0))
    
    distribucion = []
    for i in range(bins):
        distribucion.append({
            "bucket": i,
            "min": float(edges[i]),
            "max": float(edges[i+1]),
            "count": int(counts[i])
        })
        
    return {"consulta": "Q5", "zone_id": zone_id, "distribution": distribucion}

