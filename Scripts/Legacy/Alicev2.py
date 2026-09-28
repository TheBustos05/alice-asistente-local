import sys
import os
import base64
import socket
import subprocess
import time
import json
import traceback
import logging
import warnings
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QTextEdit,
                             QLineEdit, QPushButton, QHBoxLayout, QFileDialog)
from openai import OpenAI
from mem0 import Memory
from mem0.llms.openai import OpenAILLM

# ==================================================
# CONFIGURACIÓN DE LOGGING (en vez de "except: pass" silenciosos)
# ==================================================
logging.basicConfig(
    filename="asistente_errores.log",
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AsistenteLocal")

# Silenciar advertencias de librerías (no de nuestro propio logging)
os.environ["POSTHOG_DISABLED"] = "1"
warnings.filterwarnings("ignore")

# --- PARCHE DE COMPATIBILIDAD MEM0 / LM STUDIO ---
# Se aplica una sola vez al importar el módulo (no en cada init de memoria).
_original_generate_response = OpenAILLM.generate_response
def _generate_response_patched(self, messages, response_format=None, tools=None, tool_choice=None):
    if response_format and response_format.get("type") == "json_object":
        response_format = None
    return _original_generate_response(
        self, messages=messages, response_format=response_format,
        tools=tools, tool_choice=tool_choice
    )
OpenAILLM.generate_response = _generate_response_patched
# -------------------------------------------------

# ==================================================
# HERRAMIENTAS REALES DE SISTEMA DE ARCHIVOS (CRUD)
# ==================================================
DIRECTORIO_BASE = os.path.abspath("./workspace_ia")
os.makedirs(DIRECTORIO_BASE, exist_ok=True)


def _resolver_ruta(ruta):
    """Evita que la IA escriba fuera del workspace usando rutas relativas
    con '..'. Cualquier intento de escape se corrige hacia el directorio base."""
    if os.path.isabs(ruta):
        ruta_final = os.path.abspath(ruta)
    else:
        ruta_final = os.path.abspath(os.path.join(DIRECTORIO_BASE, ruta))

    if os.path.commonpath([ruta_final, DIRECTORIO_BASE]) != DIRECTORIO_BASE:
        # Si intenta salirse del workspace, se fuerza a quedarse dentro.
        nombre = os.path.basename(ruta_final)
        ruta_final = os.path.join(DIRECTORIO_BASE, nombre)
    return ruta_final


def herramienta_crear_archivo(ruta, contenido=""):
    try:
        ruta_final = _resolver_ruta(ruta)
        os.makedirs(os.path.dirname(ruta_final) or ".", exist_ok=True)
        with open(ruta_final, "w", encoding="utf-8") as f:
            f.write(contenido)
        return {"ok": True, "ruta": ruta_final}
    except Exception as e:
        logger.warning("Error en crear_archivo(%s): %s", ruta, e)
        return {"ok": False, "error": str(e)}


def herramienta_leer_archivo(ruta, max_caracteres=4000):
    try:
        ruta_final = _resolver_ruta(ruta)
        if not os.path.isfile(ruta_final):
            return {"ok": False, "error": f"No existe: {ruta_final}"}
        with open(ruta_final, "r", encoding="utf-8", errors="replace") as f:
            contenido = f.read()
        return {"ok": True, "ruta": ruta_final, "contenido": contenido[:max_caracteres]}
    except Exception as e:
        logger.warning("Error en leer_archivo(%s): %s", ruta, e)
        return {"ok": False, "error": str(e)}


def herramienta_listar_directorio(ruta="."):
    try:
        ruta_final = _resolver_ruta(ruta)
        if not os.path.isdir(ruta_final):
            return {"ok": False, "error": "No existe directorio"}
        elementos = [
            {"nombre": n, "tipo": "carpeta" if os.path.isdir(os.path.join(ruta_final, n)) else "archivo"}
            for n in sorted(os.listdir(ruta_final))
        ]
        return {"ok": True, "ruta": ruta_final, "elementos": elementos}
    except Exception as e:
        logger.warning("Error en listar_directorio(%s): %s", ruta, e)
        return {"ok": False, "error": str(e)}


FUNCIONES_DISPONIBLES = {
    "crear_archivo": herramienta_crear_archivo,
    "leer_archivo": herramienta_leer_archivo,
    "listar_directorio": herramienta_listar_directorio,
}

TOOLS = [
    {"type": "function", "function": {
        "name": "crear_archivo",
        "description": "Crea o sobrescribe un archivo de texto.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"}, "contenido": {"type": "string"}
        }, "required": ["ruta", "contenido"]}}},
    {"type": "function", "function": {
        "name": "leer_archivo",
        "description": "Lee el contenido de un archivo.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"}
        }, "required": ["ruta"]}}},
    {"type": "function", "function": {
        "name": "listar_directorio",
        "description": "Lista archivos en una ruta.",
        "parameters": {"type": "object", "properties": {
            "ruta": {"type": "string"}
        }, "required": []}}}
]


# ==================================================
# CLASE PRINCIPAL DE LA APLICACIÓN
# ==================================================
class InterfazIA(QWidget):
    def __init__(self):
        super().__init__()
        self.ruta_imagen = None
        self.client = None
        self.modelo_cargado = None

        # Variables de Memoria y estado — como atributos de instancia,
        # no globales, para evitar que se compartan entre ventanas.
        self.memoria = None
        self.USER_ID = "alvaro_calderon"
        self.HISTORIAL_CONVERSACION = []
        self.MAX_TURNOS_HISTORIAL = 8

        self.configurar_ui()
        self.asegurar_motor_local()

    def configurar_ui(self):
        self.setWindowTitle('Mi Asistente Local - v2')
        self.resize(600, 750)
        self.setStyleSheet("background-color: #1e1e2e; color: #cdd6f4; font-size: 14px;")

        layout_principal = QVBoxLayout()
        self.pantalla_chat = QTextEdit()
        self.pantalla_chat.setReadOnly(True)
        self.pantalla_chat.setStyleSheet("background-color: #181825; border: 1px solid #313244; padding: 10px;")
        layout_principal.addWidget(self.pantalla_chat)

        layout_controles = QHBoxLayout()
        self.btn_imagen = QPushButton("📷")
        self.btn_imagen.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; padding: 8px; max-width: 50px;")
        self.btn_imagen.clicked.connect(self.adjuntar_imagen)

        self.entrada_texto = QLineEdit()
        self.entrada_texto.setPlaceholderText("Escribe tu instrucción aquí...")
        self.entrada_texto.setStyleSheet("background-color: #313244; border: none; padding: 8px;")
        self.entrada_texto.returnPressed.connect(self.enviar_mensaje)

        self.btn_enviar = QPushButton("Enviar")
        self.btn_enviar.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold; padding: 8px;")
        self.btn_enviar.clicked.connect(self.enviar_mensaje)

        layout_controles.addWidget(self.btn_imagen)
        layout_controles.addWidget(self.entrada_texto)
        layout_controles.addWidget(self.btn_enviar)
        layout_principal.addLayout(layout_controles)
        self.setLayout(layout_principal)

        self.bloquear_ui(True)

    def bloquear_ui(self, estado):
        self.entrada_texto.setDisabled(estado)
        self.btn_enviar.setDisabled(estado)
        if not estado:
            self.entrada_texto.setFocus()

    def imprimir_estado(self, texto, color="#f38ba8"):
        self.pantalla_chat.append(f"<span style='color: {color};'>[SISTEMA]</span> <i>{texto}</i>")
        QApplication.processEvents()

    # --- 1. INICIALIZACIÓN ---
    def asegurar_motor_local(self, host="127.0.0.1", port=1234, modelos=("qwen/qwen3-vl-8b",)):
        def puerto_abierto():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex((host, port)) == 0

        if not puerto_abierto():
            self.imprimir_estado("Iniciando servidor de LM Studio...")
            subprocess.Popen("lms server start", shell=True)
            for _ in range(15):
                time.sleep(1)
                QApplication.processEvents()
                if puerto_abierto():
                    break

        self.client = OpenAI(base_url=f"http://{host}:{port}/v1", api_key="lm-studio")

        for modelo in modelos:
            self.imprimir_estado(f"Comprobando modelo: {modelo}...")
            if self._probar_modelo(modelo):
                self.modelo_cargado = modelo
                break

            self.imprimir_estado(f"Cargando {modelo} en VRAM (espera unos segundos)...")
            subprocess.run(f'lms load "{modelo}" -y', shell=True, capture_output=True)
            for _ in range(15):
                time.sleep(2)
                QApplication.processEvents()
                if self._probar_modelo(modelo):
                    self.modelo_cargado = modelo
                    break
            if self.modelo_cargado:
                break

        if self.modelo_cargado:
            self.inicializar_memoria()
            self.imprimir_estado(f"<br>✅ <b>SISTEMA LISTO</b> (modelo: {self.modelo_cargado}).<br>", "#a6e3a1")
            self.bloquear_ui(False)
        else:
            self.imprimir_estado("❌ ERROR: No se pudo cargar ningún modelo. Revisa 'asistente_errores.log'.")

    def _probar_modelo(self, modelo):
        try:
            self.client.chat.completions.create(model=modelo, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
            return True
        except Exception as e:
            logger.warning("Modelo '%s' aún no disponible: %s", modelo, e)
            return False

    def inicializar_memoria(self):
        self.imprimir_estado("Conectando base de datos vectorial...")
        try:
            config = {
                "llm": {"provider": "openai", "config": {"model": self.modelo_cargado, "api_key": "lm-studio", "openai_base_url": "http://localhost:1234/v1"}},
                "embedder": {"provider": "huggingface", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
                "vector_store": {"provider": "chroma", "config": {"collection_name": "asistente_db", "path": "./memoria_local_db"}}
            }
            self.memoria = Memory.from_config(config)
        except Exception as e:
            logger.error("No se pudo inicializar Mem0: %s", e)
            self.imprimir_estado("⚠️ No se pudo iniciar la memoria persistente. Seguirá funcionando sin ella.")
            self.memoria = None

    # --- 2. INTERACCIÓN Y UI ---
    def adjuntar_imagen(self):
        archivo, _ = QFileDialog.getOpenFileName(self, "Seleccionar Imagen", "", "Imágenes (*.png *.jpg *.jpeg)")
        if archivo:
            self.ruta_imagen = archivo
            self.pantalla_chat.append(f"<br><i>📎 Imagen preparada: {archivo.split('/')[-1]}</i>")

    def enviar_mensaje(self):
        texto_usuario = self.entrada_texto.text()
        if not texto_usuario and not self.ruta_imagen:
            return

        self.pantalla_chat.append(f"<br><span style='color: #89b4fa;'><b>Tú:</b></span> {texto_usuario}")
        self.entrada_texto.clear()
        self.bloquear_ui(True)
        QApplication.processEvents()

        # Preparar contenido (Soporte Multimodal para Qwen VL)
        contenido = []
        if texto_usuario:
            contenido.append({"type": "text", "text": texto_usuario})
        if self.ruta_imagen:
            try:
                with open(self.ruta_imagen, "rb") as f:
                    base64_img = base64.b64encode(f.read()).decode('utf-8')
                contenido.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}})
            except Exception as e:
                logger.warning("No se pudo leer la imagen adjunta: %s", e)
                self.imprimir_estado("⚠️ No se pudo cargar la imagen adjunta.")
            self.ruta_imagen = None

        self.procesar_ia(texto_usuario, contenido)
        self.bloquear_ui(False)

    # --- 3. CEREBRO, HERRAMIENTAS Y MEMORIA ---
    def procesar_ia(self, texto_usuario, contenido_formateado):
        # 1. Búsqueda de Memoria
        contexto_memoria = ""
        if self.memoria is not None:
            self.imprimir_estado("Consultando recuerdos...", "#f9e2af")
            try:
                recuerdos = self.memoria.search(query=texto_usuario, filters={"user_id": self.USER_ID})
                lista_recuerdos = [
                    m["memory"] for m in
                    (recuerdos.get("results", []) if isinstance(recuerdos, dict) else recuerdos)[:5]
                ] if recuerdos else []
                contexto_memoria = "\n".join([f"- {r}" for r in lista_recuerdos])
            except Exception as e:
                logger.warning("Error buscando en memoria: %s", e)

        # 2. Prompt del Sistema
        system_prompt = (
            "Eres un asistente virtual local. Tienes acceso a herramientas reales en la computadora del usuario. "
            "Si te pide crear, leer o listar archivos, DEBES llamar a la función correspondiente. "
            f"El directorio base de trabajo es: {DIRECTORIO_BASE}.\n\n"
            f"MEMORIA RELEVANTE DEL USUARIO:\n{contexto_memoria if contexto_memoria else 'Ninguna relevante.'}"
        )

        historial = [{"role": "system", "content": system_prompt}] + self.HISTORIAL_CONVERSACION + [{"role": "user", "content": contenido_formateado}]

        # 3. Llamada al LLM y Ciclo de Herramientas (hasta 3 rondas encadenadas)
        self.imprimir_estado("Analizando y generando respuesta...", "#f9e2af")
        try:
            response = self.client.chat.completions.create(
                model=self.modelo_cargado, messages=historial, tools=TOOLS, tool_choice="auto", temperature=0.7
            )
            mensaje_modelo = response.choices[0].message

            rondas = 0
            while getattr(mensaje_modelo, "tool_calls", None) and rondas < 3:
                rondas += 1
                historial.append({
                    "role": "assistant",
                    "content": mensaje_modelo.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in mensaje_modelo.tool_calls
                    ]
                })

                resultados_herramientas = []
                for tc in mensaje_modelo.tool_calls:
                    nombre_func = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                        self.imprimir_estado(f"🛠️ Ejecutando Tool: {nombre_func}...", "#fab387")
                        func = FUNCIONES_DISPONIBLES.get(nombre_func)
                        if func:
                            resultado = func(**args)
                        else:
                            resultado = {"ok": False, "error": f"Herramienta desconocida: {nombre_func}"}
                    except Exception as e:
                        # Un fallo aquí ya no rompe toda la respuesta: se informa
                        # al usuario y al modelo, y se continúa.
                        logger.error("Fallo ejecutando la tool '%s': %s", nombre_func, e)
                        self.imprimir_estado(f"⚠️ Error ejecutando '{nombre_func}': {e}", "#f38ba8")
                        resultado = {"ok": False, "error": f"Excepción al ejecutar la herramienta: {e}"}

                    resultados_herramientas.append({
                        "role": "tool", "tool_call_id": tc.id, "content": json.dumps(resultado, ensure_ascii=False)
                    })

                historial.extend(resultados_herramientas)
                response = self.client.chat.completions.create(
                    model=self.modelo_cargado, messages=historial, tools=TOOLS, tool_choice="auto", temperature=0.7
                )
                mensaje_modelo = response.choices[0].message

            respuesta_final = str(mensaje_modelo.content or "").strip()
            self.pantalla_chat.append(f"<span style='color: #a6e3a1;'><b>IA:</b></span> {respuesta_final.replace(chr(10), '<br>')}")

            # Guardar en contexto a corto plazo
            self.HISTORIAL_CONVERSACION.append({"role": "user", "content": texto_usuario})
            self.HISTORIAL_CONVERSACION.append({"role": "assistant", "content": respuesta_final})
            if len(self.HISTORIAL_CONVERSACION) > self.MAX_TURNOS_HISTORIAL * 2:
                del self.HISTORIAL_CONVERSACION[:2]

            # 4. Evaluación de Memoria a largo plazo
            if self.memoria is not None and len(texto_usuario) > 20 and any(
                p in texto_usuario.lower() for p in
                ["prefiero", "mi proyecto", "estoy trabajando", "recuerda", "me gusta", "me llamo"]
            ):
                self.imprimir_estado("💾 Guardando información en memoria persistente...", "#89dceb")
                try:
                    self.memoria.add(
                        messages=[{"role": "user", "content": texto_usuario}, {"role": "assistant", "content": respuesta_final}],
                        user_id=self.USER_ID
                    )
                except Exception as e:
                    logger.warning("Error guardando en memoria: %s", e)

        except Exception as e:
            logger.error("Error de conexión o procesamiento: %s\n%s", e, traceback.format_exc())
            self.imprimir_estado(f"Error de conexión o procesamiento: {str(e)}", "#f38ba8")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ventana = InterfazIA()
    ventana.show()
    sys.exit(app.exec())