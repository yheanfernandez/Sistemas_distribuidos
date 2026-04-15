import time
import random
import requests
import redis
import numpy as np
import os
import json

# URLs internas de Docker (usamos los nombres de los servicios del docker-compose)
REDIS_HOST = "cache"
DATOS_URL = "http://datos:8000"
RESPUESTAS_URL = "http://respuestas:8000" # Ajusta el puerto si en tu Cerebro usaste otro internamente

# Conexión a la Caché Redis
cache = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

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

def simular_trafico(distribucion="uniforme", iteraciones=100):
    print(f"\n--- Iniciando ráfaga de {iteraciones} consultas ({distribucion.upper()}) ---")
    
    for i in range(iteraciones):
        inicio_ms = time.time() * 1000
        
        # 1. Armar la consulta
        tipo_consulta = random.choice(CONSULTAS)
        zona = random.choice(ZONAS) if distribucion == "uniforme" else elegir_zona_zipf()
        
        # 2. Generar la llave para la Caché
        if tipo_consulta == "q4":
            zona_b = random.choice(ZONAS)
            cache_key = f"{tipo_consulta}:{zona}:{zona_b}:conf=0.0"
            params = {"zone_a": zona, "zone_b": zona_b, "confidence_min": 0.0}
        else:
            cache_key = f"{tipo_consulta}:{zona}:conf=0.0"
            if tipo_consulta == "q5":
                params = {"zone_id": zona, "bins": 5}
            else:
                params = {"zone_id": zona, "confidence_min": 0.0}
            
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

    #Limpiamos la caché primero
    limpiar_cache()

    print("Bot esperando 60 segundos a que la Caché y los Cerebros estén listos...")
    time.sleep(60)
    
    # Simular tráfico Uniforme
    simular_trafico("uniforme", 100)
    
    # Simular tráfico Zipf (aquí deberías ver muchos más HITs)
    simular_trafico("zipf", 100)
    
    print("\n¡Simulación terminada! Manteniendo contenedor vivo...")
    while True:
        time.sleep(1000)
