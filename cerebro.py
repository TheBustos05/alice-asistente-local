import socket
import subprocess
import time
import json
import base64
import mimetypes
import logging
import re
from openai import OpenAI

import skills
from skills import skill_crud
from memoria_core import GestorMemoria

logger = logging.getLogger("Cerebro")

class CerebroIA:
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

    def encender_motor(self, host="127.0.0.1", port=1234):
        def puerto_abierto():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex((host, port)) == 0

        if not puerto_abierto():
            self.log("Iniciando servidor de LM Studio...")
            subprocess.Popen("lms server start", shell=True)
            for _ in range(15):
                time.sleep(1)
                self.refresh()
                if puerto_abierto(): break

        self.client = OpenAI(base_url=f"http://{host}:{port}/v1", api_key="lm-studio")
        self.log("Iniciando sistema de Enrutamiento Dinámico...", "#cba6f7")

        if self._asegurar_modelo(self.modelo_rapido):
            self.log("Conectando memoria a largo plazo...", "#89b4fa")
            if self.gestor_memoria.inicializar(self.modelo_rapido):
                self.log(f"<br>✅ <b>SISTEMA LISTO</b><br>Recepcionista: {self.modelo_rapido}<br>Especialista: {self.modelo_pesado}<br>", "#a6e3a1")
            return True
        return False

    def _asegurar_modelo(self, nombre_modelo):
        try:
            self.client.chat.completions.create(model=nombre_modelo, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
            return True
        except Exception:
            self.log(f"Cargando '{nombre_modelo}' en VRAM...", "#fab387")
            subprocess.run(f'lms load "{nombre_modelo}" -y', shell=True, capture_output=True)
            for _ in range(15):
                time.sleep(2)
                self.refresh()
                try:
                    self.client.chat.completions.create(model=nombre_modelo, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
                    return True
                except Exception: pass
        return False

    def procesar_mensaje(self, texto, ruta_imagen=None):
        modelo_seleccionado = self.modelo_rapido
        texto_lower = (texto or "").lower()
        
        habla_de_archivos = any(palabra in texto_lower for palabra in ["carpeta", "ruta", "directorio", "archivo", "espacio de trabajo", "readme"])
        requiere_experto = re.search(r"\b(código|script|blender|python|render|analiza)\b", texto_lower)

        if ruta_imagen:
            self.log("👁️ Imagen detectada. Delegando al Especialista Visual (Qwen)...", "#cba6f7")
            modelo_seleccionado = self.modelo_pesado
        elif requiere_experto and not habla_de_archivos:
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

            if modelo == self.modelo_pesado:
                self.log("Tarea pesada finalizada. Devolviendo control al Recepcionista...", "#a6e3a1")
                self._asegurar_modelo(self.modelo_rapido)

            return respuesta_final
        except Exception as e:
            self.log(f"Error: {e}", "#f38ba8")
            return "Ocurrió un error al procesar la respuesta."