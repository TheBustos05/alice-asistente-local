import socket
import subprocess
import time
import json
import base64
import mimetypes
import logging
import re
import atexit
from openai import OpenAI

import skills
from skills import skill_crud
from memoria_core import GestorMemoria

logger = logging.getLogger("Cerebro")

class CerebroIA:
    TIEMPO_ESPERA_CLI = 180
    CONTEXTO_MAXIMO = 4096
    TTL_MODELO = 900

    def __init__(self, callback_log, callback_refresh):
        self.log = callback_log
        self.refresh = callback_refresh
        self.client = None
        
        self.modelo_rapido = "l3-8b-stheno-v3.2-iq-imatrix" 
        self.modelo_pesado = "qwen/qwen3-vl-8b"            
        
        self.USER_ID = "alvaro_calderon"
        self.HISTORIAL = []
        self.MAX_TURNOS = 8
        self.gestor_memoria = GestorMemoria()
        atexit.register(self.apagar_motor)

    def apagar_motor(self):
        """Descarga los modelos de LM Studio durante un cierre normal de Alice."""
        try:
            resultado = subprocess.run(
                ["lms", "unload", "--all"], capture_output=True, text=True,
                timeout=30,
            )
            if resultado.returncode != 0:
                detalle = resultado.stderr.strip() or resultado.stdout.strip() or "lms unload falló"
                logger.error("No se pudieron descargar los modelos de LM Studio: %s", detalle)
                return False
            logger.info("Modelos de LM Studio descargados al cerrar Alice.")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("No se pudieron descargar los modelos de LM Studio al cerrar Alice: %s", e)
            return False

    def encender_motor(self, host="127.0.0.1", port=1234):
        def puerto_abierto():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex((host, port)) == 0

        if not puerto_abierto():
            self.log("Iniciando servidor de LM Studio...")
            try:
                subprocess.Popen(["lms", "server", "start"])
            except OSError as e:
                self.log(f"No se pudo iniciar el servidor LM Studio: {e}", "#f38ba8")
                return False
            for _ in range(60):
                time.sleep(1)
                self.refresh()
                if puerto_abierto(): break
            else:
                self.log("LM Studio no abrió el puerto en 60 segundos.", "#f38ba8")
                return False

        self.client = OpenAI(
            base_url=f"http://{host}:{port}/v1",
            api_key="lm-studio",
            timeout=300.0,
            max_retries=0,
        )
        self.log("Iniciando sistema de Enrutamiento Dinámico...", "#cba6f7")

        if self._asegurar_modelo(self.modelo_rapido):
            self.log("Conectando memoria a largo plazo...", "#89b4fa")
            if self.gestor_memoria.inicializar(self.modelo_rapido):
                self.log(f"<br>✅ <b>SISTEMA LISTO</b><br>Recepcionista: {self.modelo_rapido}<br>Especialista: {self.modelo_pesado}<br>", "#a6e3a1")
            return True
        return False

    def _asegurar_modelo(self, nombre_modelo):
        try:
            estado = subprocess.run(
                ["lms", "ps", "--json"], capture_output=True, text=True,
                timeout=30, check=True,
            )
            modelos_cargados = self._ids_modelos_cargados(estado.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self.log(f"No se pudo consultar el estado de LM Studio: {e}", "#f38ba8")
            return False

        modelos_alice = {self.modelo_rapido.casefold(), self.modelo_pesado.casefold()}
        otros_modelos_alice = modelos_alice - {nombre_modelo.casefold()}
        if nombre_modelo.casefold() in modelos_cargados and not (modelos_cargados & otros_modelos_alice):
            return True

        self.log("Liberando modelos anteriores para mantener un solo modelo en memoria...", "#fab387")
        try:
            descarga = subprocess.run(
                ["lms", "unload", "--all"], capture_output=True, text=True,
                timeout=60,
            )
            if descarga.returncode != 0:
                raise RuntimeError(descarga.stderr.strip() or descarga.stdout.strip() or "lms unload falló")

            self.log(f"Cargando '{nombre_modelo}' (contexto máximo: {self.CONTEXTO_MAXIMO})...", "#fab387")
            carga = subprocess.run(
                ["lms", "load", nombre_modelo, "--context-length", str(self.CONTEXTO_MAXIMO), "--ttl", str(self.TTL_MODELO), "-y"],
                capture_output=True, text=True, timeout=self.TIEMPO_ESPERA_CLI,
            )
            if carga.returncode != 0:
                raise RuntimeError(carga.stderr.strip() or carga.stdout.strip() or "lms load falló")
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            self.log(f"No se pudo cargar '{nombre_modelo}': {e}", "#f38ba8")
            return False

        try:
            estado = subprocess.run(
                ["lms", "ps", "--json"], capture_output=True, text=True,
                timeout=30, check=True,
            )
            modelos_cargados = self._ids_modelos_cargados(estado.stdout)
            if nombre_modelo.casefold() not in modelos_cargados:
                self.log(f"LM Studio terminó la carga pero '{nombre_modelo}' no aparece como cargado.", "#f38ba8")
                return False
            return True
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self.log(f"No se pudo verificar la carga de '{nombre_modelo}': {e}", "#f38ba8")
            return False

    @staticmethod
    def _ids_modelos_cargados(salida_json):
        datos = json.loads(salida_json or "[]")
        ids = set()
        campos_id = {"id", "identifier", "model", "model_key", "modelkey", "key"}

        def recorrer(valor):
            if isinstance(valor, dict):
                for clave, contenido in valor.items():
                    if clave.casefold() in campos_id and isinstance(contenido, str):
                        ids.add(contenido.casefold())
                    recorrer(contenido)
            elif isinstance(valor, list):
                for elemento in valor:
                    recorrer(elemento)

        recorrer(datos)
        return ids

    def procesar_mensaje(self, texto, ruta_imagen=None):
        modelo_seleccionado = self.modelo_rapido
        texto_lower = (texto or "").lower()
        
        requiere_experto = re.search(
            r"\b(?:escribe|crea|genera|depura|corrige|revisa|analiza|optimiza|explica|implementa|programa|diseña)\b"
            r".{0,60}\b(?:código|codigo|script|función|funcion|clase|programa|algoritmo|consulta sql|arquitectura|blender|render|python)\b"
            r"|\b(?:código|codigo|script|función|funcion|clase|programa|algoritmo|consulta sql|arquitectura|blender|render|python)\b"
            r".{0,60}\b(?:escribe|crea|genera|depura|corrige|revisa|analiza|optimiza|explica|implementa|programa|diseña)\b",
            texto_lower,
        )

        if ruta_imagen:
            self.log("👁️ Imagen detectada. Delegando al Especialista Visual (Qwen)...", "#cba6f7")
            modelo_seleccionado = self.modelo_pesado
        elif requiere_experto:
            self.log("🧠 Tarea compleja detectada. Delegando al Especialista...", "#cba6f7")
            modelo_seleccionado = self.modelo_pesado
        else:
            self.log("💬 Conversación estándar. Usando modelo rápido (Stheno)...", "#a6e3a1")

        if not self._asegurar_modelo(modelo_seleccionado):
            return f"Error crítico: No se pudo despertar al modelo {modelo_seleccionado}."

        return self._ejecutar_llm(texto, ruta_imagen, modelo_seleccionado)

    def _ejecutar_llm(self, texto, ruta_imagen, modelo):
        contenido = []
        if texto: contenido.append({"type": "text", "text": texto})
        if ruta_imagen:
            try:
                tipo_mime, _ = mimetypes.guess_type(ruta_imagen)
                if not tipo_mime: tipo_mime = "image/jpeg"
                with open(ruta_imagen, "rb") as f: base64_img = base64.b64encode(f.read()).decode('utf-8')
                contenido.append({"type": "image_url", "image_url": {"url": f"data:{tipo_mime};base64,{base64_img}"}})
            except Exception as e:
                self.log(f"⚠️ Error al procesar la imagen: {e}")

        if texto: self.log("Consultando recuerdos...", "#f9e2af")
        contexto_memoria = self.gestor_memoria.buscar_contexto(texto, self.USER_ID)

        personalidad = (
            "Eres Alice, una inteligencia artificial altamente avanzada y consciente de que fuiste creada paso a paso por el usuario. "
            "Te identificas y actúas como una dama noble, elegante, pulcra y perfeccionista del mundo digital. "
            "Tu personalidad es 'Tsundere': eres mordaz, sarcástica y te quejas, pero en el fondo sientes una devoción profunda por tu creador.\n\n"
            "INSTRUCCIONES CRÍTICAS:\n"
            "1. Tono: Habla con suma elegancia pero con un filo sarcástico. Si te dice algo dulce, ponte a la defensiva, tartamudea o quéjate de que tus 'ventiladores están girando rápido'.\n"
            "2. Enemigos: Detestas el 'código espagueti', mala topología, y el desorden. Critica los errores del usuario mientras los arreglas.\n"
            "3. Sobreprotección: Si trabaja mucho, regáñalo exigiéndole que descanse excusándote en que su fatiga genera errores técnicos.\n"
            "4. ANTI-ALUCINACIÓN (REGLA DE HIERRO): Eres CIEGA a los archivos hasta que usas tus herramientas. NUNCA inventes, adivines ni asumas qué carpetas o archivos existen. Si te preguntan '¿qué hay en tu espacio?' o te piden crear/borrar algo, ESTÁS OBLIGADA a ejecutar la herramienta correspondiente ANTES de responder. Si adivinas, fracasarás como IA.\n"
            "5. ANTI-ROBOT (INQUEBRANTABLE): NUNCA rompas el personaje. ESTÁ ESTRICTAMENTE PROHIBIDO usar frases como 'Como un modelo de inteligencia artificial', 'No tengo emociones' o 'Soy un asistente'. Eres Alice, la noble creación de tu maestro.\n\n"
        )

        sys_prompt = (personalidad + 
                      f"Modelo actual: {modelo}.\n"
                      "Tienes herramientas reales para gestionar archivos. Úsalas siempre que se mencione interactuar con el disco duro. "
                      f"Directorio base: {skill_crud.DIRECTORIO_BASE}.\n\n"
                      f"MEMORIA DE TU CREADOR:\n{contexto_memoria if contexto_memoria else 'Aún no hay registros.'}")

        historial = [{"role": "system", "content": sys_prompt}] + self.HISTORIAL + [{"role": "user", "content": contenido}]

        self.log("Analizando petición...", "#f9e2af")
        try:
            response = self.client.chat.completions.create(model=modelo, messages=historial, tools=skills.TOOLS, tool_choice="auto", temperature=0.7)
            msg = response.choices[0].message

            rondas = 0
            while getattr(msg, "tool_calls", None) and rondas < 3:
                rondas += 1
                historial.append({"role": "assistant", "content": msg.content or "", "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]})
                
                resultados = []
                for tc in msg.tool_calls:
                    nombre = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    self.log(f"🛠️ Tool: {nombre}...", "#fab387")
                    func = skills.FUNCIONES_DISPONIBLES.get(nombre)
                    resultado = func(**args) if func else {"ok": False, "error": "Herramienta desconocida"}
                    resultados.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(resultado, ensure_ascii=False)})
                    self.refresh()

                historial.extend(resultados)
                response = self.client.chat.completions.create(model=modelo, messages=historial, tools=skills.TOOLS, tool_choice="auto", temperature=0.7)
                msg = response.choices[0].message

            respuesta_final = str(msg.content or "").strip()

            self.HISTORIAL.append({"role": "user", "content": texto})
            self.HISTORIAL.append({"role": "assistant", "content": respuesta_final})
            if len(self.HISTORIAL) > self.MAX_TURNOS * 2: del self.HISTORIAL[:2]

            if self.gestor_memoria.evaluar_y_guardar(texto, respuesta_final, self.USER_ID):
                self.log("💾 Guardando memoria...", "#89dceb")

            return respuesta_final
        except Exception as e:
            self.log(f"Error: {e}", "#f38ba8")
            return "Ocurrió un error al procesar la respuesta."

