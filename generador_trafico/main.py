import time
import random
import requests
import redis
import numpy as np
import os
import json

# URLs internas de Docker
REDIS_HOST = "cache"
DATOS_URL = "http://datos:8000"
RESPUESTAS_URL = "http://respuestas:8000" 

# Conexión a la Caché Redis
cache = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

CONFIDENCES = [0.0, 0.25, 0.5, 0.75]
ZONAS = ["Z1", "Z2", "Z3", "Z4", "Z5"]
CONSULTAS = ["q1", "q2", "q3", "q4", "q5"]

def limpiar_cache():
    print("Limpiando la caché (Cold Start)...")
    try:
        # Nos conectamos a Redis usando la misma variable del docker-compose
        r = redis.Redis(host=os.getenv("REDIS_HOST", "cache"), port=6379, db=0)
        r.flushall()
        print("¡Caché limpia y lista para la prueba!")
    except Exception as e:
        print(f"No se pudo limpiar la caché: {e}")

def elegir_zona_zipf():
    """Ley de Zipf: Unas pocas zonas reciben casi todo el tráfico."""
    rango = np.random.zipf(1.5)
    while rango > len(ZONAS):
        rango = np.random.zipf(1.5)
    return ZONAS[rango - 1]

def simular_trafico(distribucion="uniforme", iteraciones=5000):
    print(f"\n--- Iniciando ráfaga de {iteraciones} consultas ({distribucion.upper()}) ---")
    
    for i in range(iteraciones):
        inicio_ms = time.time() * 1000

        print(f"iteracion N{i}")
        
        # 1. Armar la consulta
        tipo_consulta = random.choice(CONSULTAS)
        zona = random.choice(ZONAS) if distribucion == "uniforme" else elegir_zona_zipf()
        conf_min = random.choice(CONFIDENCES)
        
        # 2. Generar la llave para la Caché
        if tipo_consulta == "q1":
            cache_key = f"count:{zona}:conf={conf_min}"
            params = {"zone_id": zona, "confidence_min": conf_min}
        elif tipo_consulta == "q2":
            cache_key = f"area:{zona}:conf={conf_min}"
            params = {"zone_id": zona, "confidence_min": conf_min}
        elif tipo_consulta == "q3":
            cache_key = f"density:{zona}:conf={conf_min}"
            params = {"zone_id": zona, "confidence_min": conf_min}
        elif tipo_consulta == "q4":
            zona_b = random.choice(ZONAS)
            cache_key = f"compare:density:{zona}:{zona_b}:conf={conf_min}"
            params = {"zone_a": zona, "zone_b": zona_b, "confidence_min": conf_min}
        elif tipo_consulta == "q5":
            bins = 5
            cache_key = f"confidence_dist:{zona}:bins={bins}"
            params = {"zone_id": zona, "bins": bins}
            
        # 3. INTERCEPTAR CON CACHÉ
        respuesta_cache = cache.get(cache_key)
        
        if respuesta_cache:
            evento = "HIT"
            print(f"[{evento}] {cache_key}")
        else:
            evento = "MISS"
            print(f"[{evento}] {cache_key} -> Calculando en Cerebro...")
            
            # Pedimos el cálculo al Generador de Respuestas
            try:
                respuesta_cerebro = requests.get(f"{RESPUESTAS_URL}/{tipo_consulta}", params=params)
                if respuesta_cerebro.status_code == 200:
                    # Guardamos en Caché por 60 segundos (TTL)
                    cache.setex(cache_key, 60, json.dumps(respuesta_cerebro.json()))
            except Exception as e:
                print(f"Error conectando al cerebro: {e}")

        latencia = (time.time() * 1000) - inicio_ms
        
        # 4. Anotar en el Cuaderno de Métricas
        metrica = {
            "tipo": evento,
            "consulta": tipo_consulta.upper(),
            "zona": zona,
            "tiempo_procesamiento_ms": latencia
        }
        try:
            requests.post(f"{DATOS_URL}/registrar", json=metrica)
        except Exception as e:
            pass
        
        # Pausa breve entre consultas
        time.sleep(0.1)

if __name__ == "__main__":

    # 1. Limpieza inicial
    limpiar_cache()

    print("Bot esperando 90 segundos a que la Caché y los Cerebros estén listos...")
    time.sleep(90)
    
    # METRICAS: UNIFORME
    simular_trafico("uniforme", 5000)
    
    print("\n==================================================")
    print("📊 RESULTADOS DE LA RÁFAGA UNIFORME:")
    try:
        resultados_uniforme = requests.get(f"{DATOS_URL}/estadisticas").json()
        print(json.dumps(resultados_uniforme, indent=2))
        
        # --- REINICIO TOTAL PARA SEGUNDO ESCENARIO ---
        requests.delete(f"{DATOS_URL}/reset") # Limpia métricas
        limpiar_cache()                       # Limpia Redis (Cold Start)
        # ---------------------------------------------
        
    except Exception as e:
        print(f"Error al reiniciar: {e}")
    print("==================================================\n")
    
    time.sleep(5) 
    
    # METRICA: ZIPF
    simular_trafico("zipf", 5000)
    
    print("\n==================================================")
    print("📊 RESULTADOS DE LA RÁFAGA ZIPF:")
    try:
        resultados_zipf = requests.get(f"{DATOS_URL}/estadisticas").json()
        print(json.dumps(resultados_zipf, indent=2))
    except Exception as e:
        print(f"Error al obtener métricas: {e}")
    print("==================================================\n")
    
    print("\n¡Simulación terminada! Manteniendo contenedor vivo...")
    while True:
        time.sleep(1000)
