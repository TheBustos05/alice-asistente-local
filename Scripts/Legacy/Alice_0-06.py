import os
import socket
import subprocess
import time
import warnings
import json
import re
import glob
import traceback
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
        # IMPORTANTE: con shell=True en Windows, si pasas una LISTA solo
        # el primer elemento se usa como programa; el resto se pasa como
        # argumentos a cmd.exe (no a "lms"). Con shell=True hay que usar un STRING.
        subprocess.Popen("lms server start", shell=True)
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
            # "lms" suele ser un script .cmd en Windows: sin shell=True,
            # Python no puede ejecutarlo (falla con WinError 193) y el
            # error quedaba silenciado en el except de abajo, dejando
            # el modelo sin cargar para siempre.
            comando = f'lms load "{modelo}" -y'
            res = subprocess.run(
                comando,
                shell=True,
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


# ==================================================
# HERRAMIENTAS REALES DE SISTEMA DE ARCHIVOS (CRUD)
# ==================================================
#
# Esto es lo que faltaba por completo: sin esto, el modelo solo
# generaba TEXTO describiendo una acción sin ejecutar nada. Ahora
# el LLM debe pedir explícitamente una función ("tool calling"),
# nosotros la ejecutamos con Python real, y le devolvemos el
# resultado verdadero para que redacte su respuesta basándose en
# hechos, no en suposiciones.

DIRECTORIO_BASE = os.path.abspath("./alice_workspace")
os.makedirs(DIRECTORIO_BASE, exist_ok=True)

# ==================================================
# MEMORIA DE CORTO PLAZO (historial de la sesión actual)
# ==================================================
#
# Mem0 guarda "recuerdos" filtrados a largo plazo, pero NO mantiene
# el hilo turno-a-turno de la conversación actual. Sin esto, cada
# llamada a chatear() empezaba de cero y el modelo olvidaba lo que
# acababa de hacer un mensaje antes (ej. qué archivo acababa de crear
# y en qué ruta exacta).
#
# Guardamos aquí los últimos turnos reales (usuario + respuesta final
# de Alice) para que el modelo tenga contexto inmediato. Se limita a
# un número de turnos para no exceder el contexto de 4096 tokens.
HISTORIAL_CONVERSACION = []
MAX_TURNOS_HISTORIAL = 8  # 8 turnos = 16 mensajes (usuario+asistente)


def agregar_turno_historial(mensaje_usuario, respuesta_asistente):
    HISTORIAL_CONVERSACION.append({"role": "user", "content": mensaje_usuario})
    HISTORIAL_CONVERSACION.append({"role": "assistant", "content": respuesta_asistente})

    # Recortamos manteniendo solo los últimos N turnos (pares completos).
    exceso = len(HISTORIAL_CONVERSACION) - (MAX_TURNOS_HISTORIAL * 2)
    if exceso > 0:
        del HISTORIAL_CONVERSACION[:exceso]


def _resolver_ruta(ruta):
    """Rutas relativas se resuelven dentro de DIRECTORIO_BASE; las
    absolutas se respetan tal cual."""
    if os.path.isabs(ruta):
        return ruta
    return os.path.abspath(os.path.join(DIRECTORIO_BASE, ruta))


def herramienta_crear_archivo(ruta, contenido=""):
    try:
        ruta_final = _resolver_ruta(ruta)
        os.makedirs(os.path.dirname(ruta_final) or ".", exist_ok=True)
        with open(ruta_final, "w", encoding="utf-8") as f:
            f.write(contenido)
        return {"ok": True, "ruta": ruta_final, "bytes_escritos": len(contenido.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def herramienta_leer_archivo(ruta, max_caracteres=4000):
    try:
        ruta_final = _resolver_ruta(ruta)
        if not os.path.isfile(ruta_final):
            return {"ok": False, "error": f"No existe el archivo: {ruta_final}"}
        with open(ruta_final, "r", encoding="utf-8", errors="replace") as f:
            contenido = f.read()
        truncado = len(contenido) > max_caracteres
        return {"ok": True, "ruta": ruta_final, "contenido": contenido[:max_caracteres], "truncado": truncado}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def herramienta_listar_directorio(ruta="."):
    try:
        ruta_final = _resolver_ruta(ruta)
        if not os.path.isdir(ruta_final):
            return {"ok": False, "error": f"No existe el directorio: {ruta_final}"}
        elementos = []
        for nombre in sorted(os.listdir(ruta_final)):
            completo = os.path.join(ruta_final, nombre)
            elementos.append({"nombre": nombre, "tipo": "carpeta" if os.path.isdir(completo) else "archivo"})
        return {"ok": True, "ruta": ruta_final, "elementos": elementos}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def herramienta_buscar_archivos(patron, ruta="."):
    try:
        ruta_final = _resolver_ruta(ruta)
        coincidencias = glob.glob(os.path.join(ruta_final, "**", patron), recursive=True)
        return {"ok": True, "coincidencias": coincidencias[:50], "total": len(coincidencias)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def herramienta_crear_carpeta(ruta):
    try:
        ruta_final = _resolver_ruta(ruta)
        os.makedirs(ruta_final, exist_ok=True)
        return {"ok": True, "ruta": ruta_final}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def herramienta_eliminar_archivo(ruta):
    try:
        ruta_final = _resolver_ruta(ruta)
        if not os.path.isfile(ruta_final):
            return {"ok": False, "error": f"No existe el archivo: {ruta_final}"}
        os.remove(ruta_final)
        return {"ok": True, "ruta": ruta_final}
    except Exception as e:
        return {"ok": False, "error": str(e)}


FUNCIONES_DISPONIBLES = {
    "crear_archivo": herramienta_crear_archivo,
    "leer_archivo": herramienta_leer_archivo,
    "listar_directorio": herramienta_listar_directorio,
    "buscar_archivos": herramienta_buscar_archivos,
    "crear_carpeta": herramienta_crear_carpeta,
    "eliminar_archivo": herramienta_eliminar_archivo,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "crear_archivo",
            "description": "Crea un archivo de texto con el contenido indicado. Sobrescribe si ya existe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ruta": {"type": "string", "description": "Ruta o nombre del archivo a crear."},
                    "contenido": {"type": "string", "description": "Contenido de texto a escribir en el archivo."}
                },
                "required": ["ruta", "contenido"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "leer_archivo",
            "description": "Lee y devuelve el contenido de un archivo de texto existente.",
            "parameters": {
                "type": "object",
                "properties": {"ruta": {"type": "string", "description": "Ruta del archivo a leer."}},
                "required": ["ruta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "listar_directorio",
            "description": "Lista los archivos y carpetas dentro de un directorio.",
            "parameters": {
                "type": "object",
                "properties": {"ruta": {"type": "string", "description": "Ruta del directorio. Usa '.' para el directorio base de trabajo."}},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_archivos",
            "description": "Busca archivos por patrón (ej. '*.pdf', 'informe*.txt') dentro de un directorio, de forma recursiva.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patron": {"type": "string", "description": "Patrón glob a buscar, ej. '*.pdf'."},
                    "ruta": {"type": "string", "description": "Directorio donde buscar. Por defecto el directorio base."}
                },
                "required": ["patron"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crear_carpeta",
            "description": "Crea una carpeta (y las intermedias necesarias) si no existe.",
            "parameters": {
                "type": "object",
                "properties": {"ruta": {"type": "string", "description": "Ruta de la carpeta a crear."}},
                "required": ["ruta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "eliminar_archivo",
            "description": "Elimina un archivo existente de forma permanente.",
            "parameters": {
                "type": "object",
                "properties": {"ruta": {"type": "string", "description": "Ruta del archivo a eliminar."}},
                "required": ["ruta"]
            }
        }
    }
]


def ejecutar_tool_calls(tool_calls):
    """Ejecuta cada tool_call pedido por el modelo con la función Python
    real correspondiente, y devuelve los mensajes 'tool' con el resultado
    verdadero para reinyectarlos en la conversación."""
    mensajes_resultado = []

    for tc in tool_calls:
        nombre_funcion = tc.function.name
        try:
            argumentos = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            argumentos = {}

        print(f"[HERRAMIENTA] Ejecutando '{nombre_funcion}' con argumentos: {argumentos}")

        funcion = FUNCIONES_DISPONIBLES.get(nombre_funcion)
        if funcion is None:
            resultado = {"ok": False, "error": f"Herramienta desconocida: {nombre_funcion}"}
        else:
            try:
                resultado = funcion(**argumentos)
            except Exception as e:
                resultado = {"ok": False, "error": f"Excepción ejecutando {nombre_funcion}: {e}"}
                traceback.print_exc()

        print(f"[HERRAMIENTA] Resultado: {resultado}")

        mensajes_resultado.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(resultado, ensure_ascii=False)
        })

    return mensajes_resultado


# ==================================================
# RED DE SEGURIDAD ANTI-ALUCINACIÓN
# ==================================================
#
# El system_prompt le PIDE al modelo que use herramientas en vez de
# fingir, pero eso es solo una instrucción de texto: un modelo de 8B
# puede ignorarla (como en el log: dijo "eliminado" sin ejecutar
# nada). Estas dos funciones son una capa técnica, no solo un pedido:
#
# 1) Si el mensaje del usuario suena a una acción sobre archivos,
#    forzamos tool_choice="required" para que el modelo esté
#    OBLIGADO a llamar a alguna herramienta en su primera respuesta.
# 2) Si aun así respondiera con texto afirmando una acción sin haber
#    llamado a nada, lo detectamos y forzamos una segunda ronda
#    obligatoria antes de devolverte la respuesta a ti.

PATRONES_ACCION_ARCHIVO = [
    r"\bcrea(r)?\b", r"\bcread[oa]\b",
    r"\belimina(r)?\b", r"\bborra(r)?\b",
    r"\blee(r)?\b", r"\blista(r)?\b",
    r"\bbusca(r)?\b", r"\bmodifica(r)?\b",
    r"\bmueve(r)?\b", r"\brenombra(r)?\b",
    r"\bguarda(r)?\b", r"\bescrib(e|ir)\b",
]

PATRONES_AFIRMACION_SIN_PRUEBA = [
    r"ha sido (eliminad|cread|modificad|movid|guardad|renombrad)[oa]",
    r"fue(ron)? (eliminad|cread|modificad|movid|guardad|renombrad)[oa]s?",
    r"(eliminad|cread|modificad|movid|guardad|renombrad)[oa] (correctamente|exitosamente|con éxito|de forma permanente)",
]


def parece_requerir_herramienta(mensaje):
    texto = mensaje.lower()
    return any(re.search(p, texto) for p in PATRONES_ACCION_ARCHIVO)


def afirma_accion_sin_ejecutarla(respuesta):
    texto = (respuesta or "").lower()
    return any(re.search(p, texto) for p in PATRONES_AFIRMACION_SIN_PRUEBA)


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
        "HERRAMIENTAS: Tienes acceso a herramientas reales para crear, leer, listar y buscar "
        "archivos. Si el usuario te pide crear, leer, buscar, eliminar o modificar un archivo o "
        "carpeta, DEBES llamar a la herramienta correspondiente en lugar de describir la acción "
        "como si ya la hubieras hecho o de pedir confirmación innecesaria. Nunca digas que "
        "creaste, leíste, eliminaste o modificaste algo si no llamaste a la herramienta "
        "correspondiente y recibiste un resultado exitoso.\n\n"
        "RUTAS: Cuando el usuario da una ruta relativa (ej. 'archivo.txt'), se guarda dentro de "
        f"la carpeta de trabajo: {DIRECTORIO_BASE}. Si el usuario da una ruta absoluta "
        "(ej. 'C:/Users/.../algo.txt'), se usa tal cual, fuera de esa carpeta. Revisa el "
        "historial de la conversación para saber en qué ruta exacta se creó o modificó cada "
        "archivo antes de asumir dónde está.\n\n"
        "MEMORIA RELEVANTE:\n"
        f"{contexto if contexto else 'No hay antecedentes relevantes registrados.'}"
    )

    print(
        "[2/3] Generando respuesta con "
        f"{MODELO}..."
    )

    inicio = time.perf_counter()

    # Incluimos los turnos previos de la sesión (memoria de corto
    # plazo) para que el modelo tenga contexto real de lo que acaba
    # de pasar, y añadimos el mensaje nuevo al final.
    historial = (
        [{"role": "system", "content": system_prompt}]
        + HISTORIAL_CONVERSACION
        + [{"role": "user", "content": mensaje}]
    )

    # Si el mensaje suena a una acción de archivos, obligamos al
    # modelo a llamar a una herramienta en vez de dejarle la opción
    # de simplemente "hablar" de haberlo hecho.
    tool_choice_inicial = "required" if parece_requerir_herramienta(mensaje) else "auto"

    try:
        try:
            response = client.chat.completions.create(
                model=MODELO,
                messages=historial,
                tools=TOOLS,
                tool_choice=tool_choice_inicial,
                temperature=0.7,
                max_tokens=1024
            )
        except Exception as e:
            # Si el backend no soporta tool_choice="required", caemos
            # de vuelta a "auto" en lugar de romper la conversación.
            if tool_choice_inicial == "required":
                print(f"[LLM] tool_choice='required' no soportado ({e}); reintentando con 'auto'.")
                response = client.chat.completions.create(
                    model=MODELO,
                    messages=historial,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=1024
                )
            else:
                raise

        mensaje_modelo = response.choices[0].message

        MAX_RONDAS_HERRAMIENTAS = 5
        rondas = 0

        while getattr(mensaje_modelo, "tool_calls", None) and rondas < MAX_RONDAS_HERRAMIENTAS:
            rondas += 1

            historial.append({
                "role": "assistant",
                "content": mensaje_modelo.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in mensaje_modelo.tool_calls
                ]
            })

            resultados = ejecutar_tool_calls(mensaje_modelo.tool_calls)
            historial.extend(resultados)

            response = client.chat.completions.create(
                model=MODELO,
                messages=historial,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=1024
            )
            mensaje_modelo = response.choices[0].message

        # Obtener la respuesta final de forma segura
        respuesta = mensaje_modelo.content

        # Algunas combinaciones de LM Studio + modelos pueden
        # devolver contenido vacío o parcial.
        if respuesta is None:
            respuesta = ""

        respuesta = str(respuesta).strip()

        # --------------------------------------------------------
        # RED DE SEGURIDAD: el modelo afirmó una acción sin haber
        # llamado a NINGUNA herramienta en este turno. Lo forzamos
        # a corregirse antes de que esa mentira te llegue a ti.
        # --------------------------------------------------------
        if rondas == 0 and parece_requerir_herramienta(mensaje) and afirma_accion_sin_ejecutarla(respuesta):
            print(
                "[ALERTA] El modelo afirmó una acción sin ejecutar "
                "ninguna herramienta. Forzando corrección..."
            )

            historial.append({"role": "assistant", "content": respuesta})
            historial.append({
                "role": "system",
                "content": (
                    "RECORDATORIO: en tu respuesta anterior afirmaste haber realizado una "
                    "acción sobre un archivo o carpeta, pero no llamaste a ninguna "
                    "herramienta. Eso es incorrecto. Llama ahora a la herramienta real "
                    "correspondiente para ejecutar la acción de verdad."
                )
            })

            response = client.chat.completions.create(
                model=MODELO,
                messages=historial,
                tools=TOOLS,
                tool_choice="required",
                temperature=0.3,
                max_tokens=1024
            )
            mensaje_modelo = response.choices[0].message

            if getattr(mensaje_modelo, "tool_calls", None):
                historial.append({
                    "role": "assistant",
                    "content": mensaje_modelo.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        }
                        for tc in mensaje_modelo.tool_calls
                    ]
                })
                resultados = ejecutar_tool_calls(mensaje_modelo.tool_calls)
                historial.extend(resultados)

                response = client.chat.completions.create(
                    model=MODELO,
                    messages=historial,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=1024
                )
                mensaje_modelo = response.choices[0].message
                respuesta = str(mensaje_modelo.content or "").strip()

        try:
            print(
                f"[LLM] Finish reason: "
                f"{response.choices[0].finish_reason}"
            )
        except Exception:
            pass

    except Exception as e:
        print(f"[LLM] Error: {e}")
        traceback.print_exc()
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

    # Guardamos este turno en el historial de corto plazo ANTES de
    # devolver la respuesta, para que el próximo mensaje del usuario
    # ya tenga este contexto disponible.
    agregar_turno_historial(mensaje, respuesta)

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