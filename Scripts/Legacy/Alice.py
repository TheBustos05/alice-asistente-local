import sys
import base64
import socket
import subprocess
import time
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QTextEdit, 
                             QLineEdit, QPushButton, QHBoxLayout, QFileDialog)
from openai import OpenAI

class InterfazIA(QWidget):
    def __init__(self):
        super().__init__()
        self.ruta_imagen = None
        self.client = None
        self.configurar_ui()
        # Iniciar el motor automáticamente al abrir la app
        self.asegurar_motor_local()

    def configurar_ui(self):
        self.setWindowTitle('Mi Asistente Local - Auto Inicializable')
        self.resize(550, 700)
        self.setStyleSheet("background-color: #1e1e2e; color: #cdd6f4; font-size: 14px;")
        
        layout_principal = QVBoxLayout()

        self.pantalla_chat = QTextEdit()
        self.pantalla_chat.setReadOnly(True)
        self.pantalla_chat.setStyleSheet("background-color: #181825; border: 1px solid #313244; padding: 10px;")
        layout_principal.addWidget(self.pantalla_chat)

        layout_controles = QHBoxLayout()
        
        self.btn_imagen = QPushButton("📷 Adjuntar")
        self.btn_imagen.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; padding: 8px;")
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
        
        # Desactivar controles mientras carga
        self.entrada_texto.setEnabled(False)
        self.btn_enviar.setEnabled(False)

    def imprimir_estado(self, texto):
        self.pantalla_chat.append(f"<span style='color: #f38ba8;'>[SISTEMA]</span> <i>{texto}</i>")
        QApplication.processEvents()

    def asegurar_motor_local(self, host="127.0.0.1", port=1234, modelos=("qwen2.5-vl-7b-instruct", "qwen/qwen3-vl-8b")):
        """Basado en la lógica de Alice_0-06.py para iniciar LM Studio desde la App."""
        def puerto_abierto():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex((host, port)) == 0

        # 1. Iniciar servidor
        if not puerto_abierto():
            self.imprimir_estado("Iniciando el servidor local de LM Studio en segundo plano...")
            try:
                subprocess.Popen("lms server start", shell=True)
                for _ in range(15):
                    time.sleep(1)
                    QApplication.processEvents()
                    if puerto_abierto():
                        break
            except Exception as e:
                self.imprimir_estado(f"Error al iniciar el servidor: {e}")
        else:
            self.imprimir_estado("El servidor local ya estaba en ejecución.")

        # Conectar cliente temporal para probar
        self.client = OpenAI(base_url=f"http://{host}:{port}/v1", api_key="lm-studio")
        modelo_cargado = None

        # 2. Comprobar y cargar modelos
        for modelo in modelos:
            self.imprimir_estado(f"Comprobando si el modelo '{modelo}' está activo...")
            try:
                self.client.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1
                )
                modelo_cargado = modelo
                self.imprimir_estado(f"<b>Modelo activo y listo: {modelo}</b>")
                break
            except Exception:
                pass

            self.imprimir_estado(f"Cargando el modelo '{modelo}' en la VRAM (esto puede tardar unos segundos)...")
            try:
                comando = f'lms load "{modelo}" -y'
                subprocess.run(comando, shell=True, capture_output=True, text=True)
            except Exception as e:
                self.imprimir_estado(f"Aviso al ejecutar CLI: {e}")

            # Esperar a que el modelo cargue
            for _ in range(15):
                time.sleep(2)
                QApplication.processEvents()
                try:
                    self.client.chat.completions.create(
                        model=modelo,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=1
                    )
                    modelo_cargado = modelo
                    self.imprimir_estado(f"<b>Modelo cargado exitosamente: {modelo}</b>")
                    break
                except Exception:
                    pass
            
            if modelo_cargado:
                break
            else:
                self.imprimir_estado(f"El modelo '{modelo}' no pudo iniciar; probando el siguiente.")

        if modelo_cargado:
            self.imprimir_estado("<br>✅ <b>SISTEMA LISTO.</b> Ya puedes chatear y enviar imágenes.<br>")
            self.entrada_texto.setEnabled(True)
            self.btn_enviar.setEnabled(True)
            self.entrada_texto.setFocus()
        else:
            self.imprimir_estado("❌ <b>ERROR CRÍTICO:</b> No se pudo cargar ningún modelo. Verifica LM Studio.")

    def adjuntar_imagen(self):
        archivo, _ = QFileDialog.getOpenFileName(self, "Seleccionar Imagen", "", "Imágenes (*.png *.jpg *.jpeg)")
        if archivo:
            self.ruta_imagen = archivo
            nombre_archivo = archivo.split('/')[-1]
            self.pantalla_chat.append(f"<br><i>📎 Imagen preparada: {nombre_archivo}</i>")

    def enviar_mensaje(self):
        texto_usuario = self.entrada_texto.text()
        if not texto_usuario and not self.ruta_imagen:
            return

        self.pantalla_chat.append(f"<br><span style='color: #89b4fa;'><b>Tú:</b></span> {texto_usuario}")
        self.entrada_texto.clear()
        QApplication.processEvents()

        contenido = []
        if texto_usuario:
            contenido.append({"type": "text", "text": texto_usuario})
        
        if self.ruta_imagen:
            with open(self.ruta_imagen, "rb") as archivo_img:
                imagen_base64 = base64.b64encode(archivo_img.read()).decode('utf-8')
            contenido.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{imagen_base64}"}
            })
            self.ruta_imagen = None 

        self.pantalla_chat.append("<i>La IA está procesando...</i>")
        QApplication.processEvents()

        try:
            respuesta = self.client.chat.completions.create(
                model="local-model",
                messages=[{"role": "user", "content": contenido}],
                temperature=0.7
            )
            texto_ia = respuesta.choices[0].message.content
            texto_html = texto_ia.replace('\n', '<br>')
            self.pantalla_chat.append(f"<span style='color: #a6e3a1;'><b>IA:</b></span> {texto_html}")
        except Exception as e:
            self.pantalla_chat.append(f"<b>Error de conexión:</b> {str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ventana = InterfazIA()
    ventana.show()
    sys.exit(app.exec())