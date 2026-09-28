import os
import socket
import subprocess
import time
import warnings
import json
import re
import openai
from mem0 import Memory
from mem0.llms.openai import OpenAILLM

# Silenciar advertencias
os.environ["POSTHOG_DISABLED"] = "1"
warnings.filterwarnings("ignore")

def asegurar_servidor_y_modelo(
    host="127.0.0.1",
    port=1234,
    modelos=("qwen/qwen3-vl-8b", "google/gemma-4-e4b")
):
    """
    Verifica que LM Studio esté activo y que un modelo LLM esté efectivamente
    cargado en la memoria RAM/VRAM listo para responder.
    """
    def puerto_abierto():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0

    # 1. Iniciar servidor si está apagado
    if not puerto_abierto():
        print("Iniciando el servidor local de LM Studio...")
        subprocess.Popen(["lms", "server", "start"], shell=True)
        for _ in range(10):
            time.sleep(1)
            if puerto_abierto():
                break
        time.sleep(2)

    client_test = openai.OpenAI(
        base_url=f"http://{host}:{port}/v1",
        api_key="lm-studio"
    )

    for modelo in modelos:
        print(f"Comprobando el modelo '{modelo}'...")

        try:
            client_test.chat.completions.create(
                model=modelo,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1
            )
            print(f"Modelo activo: {modelo}")
            return modelo
        except Exception:
            pass

        print(f"Cargando el modelo '{modelo}' en memoria RAM/VRAM...")
        try:
            res = subprocess.run(
                ["lms", "load", modelo, "-y"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            salida = (res.stdout + res.stderr).strip()
            if salida:
                print(f"[LM Studio]: {salida}")
            if res.returncode != 0:
                print(f"El modelo '{modelo}' no pudo iniciar; probando el siguiente.")
                continue
        except Exception as e:
            print(f"Aviso al ejecutar CLI: {e}")

        for _ in range(15):
            time.sleep(2)
            try:
                client_test.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1
                )
                print(f"Modelo cargado exitosamente: {modelo}")
                return modelo
            except Exception:
                pass

        print(f"El modelo '{modelo}' no pudo iniciar; probando el siguiente.")

    raise RuntimeError(
        "Ninguno de los modelos configurados pudo cargar en LM Studio."
    )

# Ejecutar verificación activa antes de iniciar la memoria
MODELO = asegurar_servidor_y_modelo()

# --- PARCHE DE COMPATIBILIDAD MEM0 / LM STUDIO ---
_original_generate_response = OpenAILLM.generate_response

def generate_response_patched(self, messages, response_format=None, tools=None, tool_choice=None):
    if response_format and response_format.get("type") == "json_object":
        response_format = None
    return _original_generate_response(
        self, 
        messages=messages, 
        response_format=response_format, 
        tools=tools, 
        tool_choice=tool_choice
    )

OpenAILLM.generate_response = generate_response_patched
# -------------------------------------------------

config = {
    "llm": {
        "provider": "openai",
        "config": {
            "model": MODELO,
            "api_key": "lm-studio",
            "openai_base_url": "http://localhost:1234/v1"
        }
    },
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": "sentence-transformers/all-MiniLM-L6-v2"
        }
    },
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "asistente_memoria",
            "path": "./memoria_local_db"
        }
    }
}

memoria = Memory.from_config(config)

USER_ID = "alvaro_calderon"
client = openai.OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio"
)

# ==================================================
# CONFIGURACIÓN DE MEMORIA LOCAL
# ==================================================

ARCHIVO_MEMORIA_PENDIENTE = "./memoria_pendiente.json"

# Número máximo de candidatos antes de enviarlos a Mem0.
# 5 permite reducir bastante las llamadas sin acumular
# demasiada información sin procesar.
MAX_CANDIDATOS = 5

# Frases que indican explícitamente que el usuario quiere
# que algo sea recordado.
PATRONES_MEMORIA_EXPLICITA = [
    r"\brecuerda\b",
    r"\brecuérdame\b",
    r"\bacuérdate\b",
    r"\bacuérdate de\b",
    r"\bguarda esto\b",
    r"\bguarda que\b",
    r"\bmemoriza\b",
    r"\bten presente\b",
    r"\bten en cuenta\b",
    r"\bno olvides\b",
    r"\bno te olvides\b",
    r"\bde ahora en adelante\b",
    r"\ba partir de ahora\b",
    r"\bquiero que recuerdes\b",
    r"\bquiero que tengas presente\b"
]

# Palabras que suelen indicar información persistente.
# No significan automáticamente que haya que guardar:
# simplemente aumentan la probabilidad.
PALABRAS_IMPORTANTES = [
    "prefiero",
    "prefiere",
    "me gusta",
    "no me gusta",
    "mi proyecto",
    "mi trabajo",
    "estoy trabajando",
    "estoy estudiando",
    "estudio",
    "trabajo en",
    "estoy aprendiendo",
    "estoy desarrollando",
    "estoy haciendo",
    "mi objetivo",
    "mi meta",
    "mi computadora",
    "mi pc",
    "mi equipo",
    "mi asistente",
    "mi programa",
    "mi aplicación",
    "mi juego",
    "mi videojuego",
    "mi empresa",
    "mi negocio",
    "mi carpeta",
    "uso",
    "utilizo",
    "tengo",
    "necesito que",
    "quiero que",
    "debo",
    "voy a",
    "planeo",
    "estoy creando"
]

# ==================================================
# FUNCIONES DE MEMORIA
# ==================================================

def cargar_memoria_pendiente():
    """
    Carga los candidatos de memoria que todavía no han
    sido enviados a Mem0.
    """

    if not os.path.exists(ARCHIVO_MEMORIA_PENDIENTE):
        return []

    try:
        with open(
            ARCHIVO_MEMORIA_PENDIENTE,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(archivo)

            if isinstance(datos, list):
                return datos

    except Exception as e:
        print(f"[MEMORIA] No se pudo leer memoria pendiente: {e}")

    return []


def guardar_memoria_pendiente(candidatos):
    """
    Guarda localmente los candidatos pendientes.
    """

    try:
        with open(
            ARCHIVO_MEMORIA_PENDIENTE,
            "w",
            encoding="utf-8"
        ) as archivo:

            json.dump(
                candidatos,
                archivo,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        print(f"[MEMORIA] Error guardando candidatos: {e}")


def memoria_es_explicita(mensaje):
    """
    Determina si el usuario está pidiendo explícitamente
    recordar algo.
    """

    mensaje_normalizado = mensaje.lower().strip()

    for patron in PATRONES_MEMORIA_EXPLICITA:
        if re.search(patron, mensaje_normalizado):
            return True

    return False


def evaluar_candidato_memoria(mensaje):
    """
    Evaluación heurística ligera.

    Devuelve:
        0 = probablemente no es memoria
        1 = posible memoria
        2 = memoria bastante probable
        3 = memoria explícita
    """

    texto = mensaje.lower().strip()

    # ----------------------------------------------
    # Memoria explícita
    # ----------------------------------------------

    if memoria_es_explicita(texto):
        return 3

    # ----------------------------------------------
    # Mensajes demasiado cortos
    # ----------------------------------------------

    if len(texto) < 20:
        return 0

    puntuacion = 0

    # ----------------------------------------------
    # Información personal/proyectos/preferencias
    # ----------------------------------------------

    for palabra in PALABRAS_IMPORTANTES:
        if palabra in texto:
            puntuacion += 1

    # ----------------------------------------------
    # Estructuras lingüísticas que suelen contener
    # información persistente.
    # ----------------------------------------------

    patrones_informacion = [
        r"\bsoy\b",
        r"\bsoy de\b",
        r"\btengo\b",
        r"\bmi\b",
        r"\bmis\b",
        r"\bme gusta\b",
        r"\bprefiero\b",
        r"\bquiero\b",
        r"\bnecesito\b",
        r"\buso\b",
        r"\butilizo\b",
        r"\bestoy\b",
        r"\btrabajo\b",
        r"\bestudio\b",
        r"\baprendo\b",
        r"\bdesarrollo\b",
        r"\bdesarrollando\b"
    ]

    for patron in patrones_informacion:
        if re.search(patron, texto):
            puntuacion += 1

    # ----------------------------------------------
    # Mensajes suficientemente largos suelen contener
    # más información que una conversación casual.
    # ----------------------------------------------

    if len(texto) > 100:
        puntuacion += 1

    if len(texto) > 200:
        puntuacion += 1

    # ----------------------------------------------
    # Clasificación
    # ----------------------------------------------

    if puntuacion >= 4:
        return 2

    if puntuacion >= 2:
        return 1

    return 0


def agregar_candidato_memoria(mensaje, respuesta):
    """
    Agrega una posible memoria a un archivo local.

    Esto NO llama al LLM.
    Por eso es prácticamente instantáneo.
    """

    candidatos = cargar_memoria_pendiente()

    candidato = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_message": mensaje,
        "assistant_response": respuesta
    }

    candidatos.append(candidato)

    guardar_memoria_pendiente(candidatos)

    return candidatos


def procesar_memoria_pendiente(forzar=False):
    """
    Envía los candidatos acumulados a Mem0.

    Esta es la operación cara.

    Se ejecuta solamente cuando:
    - alcanzamos MAX_CANDIDATOS
    - se fuerza manualmente
    - se cierra el programa
    """

    candidatos = cargar_memoria_pendiente()

    if not candidatos:
        return

    if not forzar and len(candidatos) < MAX_CANDIDATOS:
        return

    print(
        f"[MEMORIA] Procesando {len(candidatos)} "
        f"candidatos con Mem0..."
    )

    inicio = time.perf_counter()

    # ----------------------------------------------
    # Convertimos varios mensajes en una sola llamada
    # a Mem0.
    # ----------------------------------------------

    mensajes = []

    for candidato in candidatos:

        mensajes.append({
            "role": "user",
            "content": candidato["user_message"]
        })

        mensajes.append({
            "role": "assistant",
            "content": candidato["assistant_response"]
        })

    try:

        memoria.add(
            messages=mensajes,
            user_id=USER_ID
        )

        tiempo = time.perf_counter() - inicio

        print(
            f"[MEMORIA] Mem0 terminó en "
            f"{tiempo:.2f} segundos."
        )

        # ------------------------------------------
        # Solo eliminamos los candidatos después de
        # confirmar que Mem0 terminó correctamente.
        # ------------------------------------------

        guardar_memoria_pendiente([])

    except Exception as e:

        print(
            f"[MEMORIA] Error procesando memoria: {e}"
        )

        print(
            "[MEMORIA] Los candidatos se conservarán "
            "para intentar procesarlos posteriormente."
        )

def chatear(mensaje):

    inicio_total = time.perf_counter()

    # ==================================================
    # 1. BUSCAR MEMORIA
    # ==================================================

    print("\n[1/3] Buscando recuerdos...")
    inicio = time.perf_counter()

    try:

        recuerdos = memoria.search(
            query=mensaje,
            filters={"user_id": USER_ID}
        )

    except Exception as e:

        print(f"[MEMORIA] Error buscando recuerdos: {e}")
        recuerdos = []

    tiempo_search = time.perf_counter() - inicio

    print(
        f"    memoria.search(): "
        f"{tiempo_search:.2f} segundos"
    )

    # ==================================================
    # PROCESAR RECUERDOS
    # ==================================================

    if isinstance(recuerdos, dict):

        lista_recuerdos = [
            m["memory"]
            for m in recuerdos.get("results", [])
            if "memory" in m
        ]

    elif isinstance(recuerdos, list):

        lista_recuerdos = [
            m["memory"]
            for m in recuerdos
            if isinstance(m, dict) and "memory" in m
        ]

    else:

        lista_recuerdos = []

    # Limitar el contexto para no enviar una cantidad
    # excesiva de recuerdos al modelo.
    lista_recuerdos = lista_recuerdos[:8]

    contexto = "\n".join(
        [f"- {r}" for r in lista_recuerdos]
    )

    # ==================================================
    # 2. GENERAR RESPUESTA
    # ==================================================

    system_prompt = (
        "Eres un asistente virtual local con personalidad. "
        "Utiliza la siguiente información recordada sobre el "
        "usuario únicamente cuando sea relevante para responder. "
        "No menciones que estás utilizando memoria a menos que "
        "el usuario pregunte directamente.\n\n"
        "MEMORIA RELEVANTE:\n"
        f"{contexto if contexto else 'No hay antecedentes relevantes registrados.'}"
    )

    print(
        "[2/3] Generando respuesta con "
        f"{MODELO}..."
    )

    inicio = time.perf_counter()

    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": mensaje
                }
            ],
            temperature=0.7,
            max_tokens=1024
        )

        # Obtener la respuesta de forma segura
        respuesta = response.choices[0].message.content

        # Algunas combinaciones de LM Studio + modelos pueden
        # devolver contenido vacío o parcial.
        if respuesta is None:
            respuesta = ""

        respuesta = str(respuesta).strip()

        try:
            print(
                f"[LLM] Finish reason: "
                f"{response.choices[0].finish_reason}"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"[LLM] Error: {e}")
        return (
            "Lo siento, ocurrió un error al "
            "generar la respuesta."
        )

    # Diagnóstico temporal
    if not respuesta:
        print("\n[DEBUG] La respuesta llegó vacía.")
        print("[DEBUG] Respuesta completa recibida:")
        print(response)
        print()

        respuesta = (
            "El modelo generó una respuesta vacía. "
            "Se imprimió la respuesta completa en la consola "
            "para diagnosticar el problema."
        )

    tiempo_llm = time.perf_counter() - inicio

    print(
        f"    LLM: "
        f"{tiempo_llm:.2f} segundos"
    )

    # ==================================================
    # 3. EVALUAR SI EL MENSAJE MERECE MEMORIA
    # ==================================================

    print("[3/3] Evaluando memoria...")

    puntuacion = evaluar_candidato_memoria(mensaje)

    candidatos = cargar_memoria_pendiente()

    if puntuacion == 3:

        # ----------------------------------------------
        # MEMORIA EXPLÍCITA
        # ----------------------------------------------

        print(
            "[MEMORIA] El usuario pidió explícitamente "
            "guardar esta información."
        )

        agregar_candidato_memoria(
            mensaje,
            respuesta
        )

        # Procesamos inmediatamente.
        procesar_memoria_pendiente(
            forzar=True
        )

    elif puntuacion >= 1:

        # ----------------------------------------------
        # POSIBLE MEMORIA
        # ----------------------------------------------

        print(
            f"[MEMORIA] Posible recuerdo detectado "
            f"(nivel {puntuacion})."
        )

        candidatos = agregar_candidato_memoria(
            mensaje,
            respuesta
        )

        print(
            f"[MEMORIA] Candidatos pendientes: "
            f"{len(candidatos)}/{MAX_CANDIDATOS}"
        )

        # Solo llamamos a Mem0 cuando tenemos suficientes
        # candidatos acumulados.
        if len(candidatos) >= MAX_CANDIDATOS:

            procesar_memoria_pendiente()

    else:

        # ----------------------------------------------
        # CONVERSACIÓN NORMAL
        # ----------------------------------------------

        print(
            "[MEMORIA] No parece necesario "
            "guardar este mensaje."
        )

    # ==================================================
    # TIEMPO TOTAL
    # ==================================================

    tiempo_total = time.perf_counter() - inicio_total

    print("------------------------------------------")
    print(
        f"Tiempo total: "
        f"{tiempo_total:.2f} segundos"
    )
    print("------------------------------------------")

    return respuesta

if __name__ == "__main__":

    print(
        "--- Asistente con Memoria Activo "
        "(Escribe 'salir' para finalizar) ---"
    )

    try:

        while True:

            entrada = input("\nTú: ").strip()

            if entrada.lower() in ["salir", "exit"]:

                print(
                    "\n[MEMORIA] Guardando "
                    "candidatos pendientes..."
                )

                procesar_memoria_pendiente(
                    forzar=True
                )

                print("Asistente finalizado.")
                break

            if not entrada:
                continue

            respuesta = chatear(entrada)

            print(
                f"\nAsistente: {respuesta}"
            )

    except KeyboardInterrupt:

        print(
            "\n\n[MEMORIA] Interrupción detectada."
        )

        procesar_memoria_pendiente(
            forzar=True
        )

        print("Asistente finalizado.")