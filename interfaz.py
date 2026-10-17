import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTextEdit, QLineEdit, QPushButton, QHBoxLayout, QFileDialog, QLabel)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from cerebro import CerebroIA

class WorkerInicializador(QThread):
    terminado = pyqtSignal(bool)
    def __init__(self, cerebro):
        super().__init__()
        self.cerebro = cerebro
    def run(self):
        exito = self.cerebro.encender_motor()
        self.terminado.emit(exito)

class WorkerMensaje(QThread):
    respuesta_lista = pyqtSignal(str)
    def __init__(self, cerebro, texto, ruta_imagen):
        super().__init__()
        self.cerebro = cerebro
        self.texto = texto
        self.ruta_imagen = ruta_imagen
    def run(self):
        respuesta = self.cerebro.procesar_mensaje(self.texto, self.ruta_imagen)
        self.respuesta_lista.emit(respuesta)

class WorkerCierre(QThread):
    def __init__(self, cerebro, trabajadores_activos):
        super().__init__()
        self.cerebro = cerebro
        self.trabajadores_activos = trabajadores_activos
        self.descarga_exitosa = False

    def run(self):
        # Primero interrumpe inferencias; luego espera a los trabajadores y
        # descarga otra vez para cubrir cargas que terminaron durante el cierre.
        self.cerebro.apagar_motor()
        for trabajador in self.trabajadores_activos:
            while trabajador.isRunning():
                trabajador.wait(250)
        self.descarga_exitosa = self.cerebro.apagar_motor()

class InterfazBase(QWidget):
    senial_log = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.ruta_imagen = None
        self._cierre_completado = False
        self._worker_cierre = None
        self.configurar_ui()
        
        self.senial_log.connect(self.imprimir_estado_seguro)
        self.cerebro = CerebroIA(callback_log=self._emitir_log, callback_refresh=lambda: None)
        self.iniciar_motor_async()

    def configurar_ui(self):
        self.setWindowTitle('Mi Asistente Local - Alice')
        self.resize(600, 750)
        self.setStyleSheet("background-color: #1e1e2e; color: #cdd6f4; font-size: 14px;")

        layout = QVBoxLayout()
        self.pantalla_chat = QTextEdit()
        self.pantalla_chat.setReadOnly(True)
        self.pantalla_chat.setStyleSheet("background-color: #181825; border: 1px solid #313244; padding: 10px; border-radius: 8px;")
        layout.addWidget(self.pantalla_chat)

        self.label_estado = QLabel("⏳ Esperando inicialización...")
        self.label_estado.setStyleSheet("color: #fab387; font-weight: bold; padding: 5px;")
        layout.addWidget(self.label_estado)

        controles = QHBoxLayout()
        self.btn_imagen = QPushButton("📷")
        self.btn_imagen.setStyleSheet("background-color: #89b4fa; color: #11111b; font-weight: bold; padding: 8px; border-radius: 4px; max-width: 50px;")
        self.btn_imagen.clicked.connect(self.adjuntar_imagen)

        self.entrada = QLineEdit()
        self.entrada.setPlaceholderText("Escribe tu instrucción aquí...")
        self.entrada.setStyleSheet("background-color: #313244; border: none; padding: 10px; border-radius: 4px;")
        self.entrada.returnPressed.connect(self.enviar_mensaje)

        self.btn_enviar = QPushButton("Enviar")
        self.btn_enviar.setStyleSheet("background-color: #a6e3a1; color: #11111b; font-weight: bold; padding: 8px; border-radius: 4px;")
        self.btn_enviar.clicked.connect(self.enviar_mensaje)

        controles.addWidget(self.btn_imagen)
        controles.addWidget(self.entrada)
        controles.addWidget(self.btn_enviar)
        layout.addLayout(controles)
        self.setLayout(layout)
        self.bloquear_ui(True)

    def bloquear_ui(self, estado):
        self.entrada.setDisabled(estado)
        self.btn_enviar.setDisabled(estado)
        if not estado: self.entrada.setFocus()

    def _emitir_log(self, texto, color="#f38ba8"):
        self.senial_log.emit(texto, color)

    def imprimir_estado_seguro(self, texto, color):
        self.pantalla_chat.append(f"<span style='color: {color};'>[SISTEMA]</span> <i>{texto}</i>")
        self.pantalla_chat.verticalScrollBar().setValue(self.pantalla_chat.verticalScrollBar().maximum())

    def iniciar_motor_async(self):
        self.imprimir_estado_seguro("Inicializando entorno...", "#89b4fa")
        
        self.segundos_transcurridos = 0
        self.timer_carga = QTimer()
        self.timer_carga.timeout.connect(self.actualizar_temporizador)
        self.timer_carga.start(1000)
        
        self.worker_init = WorkerInicializador(self.cerebro)
        self.worker_init.terminado.connect(self.al_terminar_motor)
        self.worker_init.start()

    def actualizar_temporizador(self):
        self.segundos_transcurridos += 1
        puntos = "." * (self.segundos_transcurridos % 4)
        self.label_estado.setText(f"⏳ Despertando a Alice, cargando IA en VRAM{puntos} ({self.segundos_transcurridos}s)")

    def al_terminar_motor(self, exito):
        self.timer_carga.stop()
        if exito: 
            self.label_estado.setText("✅ Sistema En Línea y Listo")
            self.label_estado.setStyleSheet("color: #a6e3a1; font-weight: bold; padding: 5px;")
            self.bloquear_ui(False)
        else: 
            self.label_estado.setText("❌ Fallo Crítico en Carga")
            self.label_estado.setStyleSheet("color: #f38ba8; font-weight: bold; padding: 5px;")
            self.imprimir_estado_seguro("Revisa que el nombre del modelo coincida en LM Studio.", "#f38ba8")

    def adjuntar_imagen(self):
        archivo, _ = QFileDialog.getOpenFileName(self, "Seleccionar Imagen", "", "Imágenes (*.png *.jpg *.jpeg *.webp)")
        if archivo:
            self.ruta_imagen = archivo
            self.pantalla_chat.append(f"<br><i>📎 Imagen preparada: {archivo.split('/')[-1]}</i>")

    def enviar_mensaje(self):
        texto = self.entrada.text()
        if not texto and not self.ruta_imagen: return

        self.pantalla_chat.append(f"<br><span style='color: #89b4fa;'><b>Tú:</b></span> {texto}")
        self.entrada.clear()
        self.bloquear_ui(True)
        
        self.label_estado.setText("⏳ Alice está procesando...")
        self.label_estado.setStyleSheet("color: #89dceb; font-weight: bold; padding: 5px;")
        
        self.worker_mensaje = WorkerMensaje(self.cerebro, texto, self.ruta_imagen)
        self.worker_mensaje.respuesta_lista.connect(self.al_terminar_mensaje)
        self.worker_mensaje.start()

    def closeEvent(self, event):
        if self._cierre_completado:
            event.accept()
            return

        event.ignore()
        if self._worker_cierre is not None and self._worker_cierre.isRunning():
            return

        self.setEnabled(False)
        self.label_estado.setText("Cerrando Alice y descargando modelos de LM Studio…")
        trabajadores = [
            trabajador for trabajador in (
                getattr(self, "worker_init", None),
                getattr(self, "worker_mensaje", None),
            )
            if trabajador is not None and trabajador.isRunning()
        ]
        self._worker_cierre = WorkerCierre(self.cerebro, trabajadores)
        self._worker_cierre.finished.connect(self._cierre_terminado)
        self._worker_cierre.start()

    def _cierre_terminado(self):
        self._cierre_completado = True
        self.close()

    def al_terminar_mensaje(self, respuesta_ia):
        self.pantalla_chat.append(f"<span style='color: #a6e3a1;'><b>IA:</b></span> {respuesta_ia.replace(chr(10), '<br>')}")
        self.pantalla_chat.verticalScrollBar().setValue(self.pantalla_chat.verticalScrollBar().maximum())
        self.ruta_imagen = None
        
        self.label_estado.setText("✅ Sistema En Línea y Listo")
        self.label_estado.setStyleSheet("color: #a6e3a1; font-weight: bold; padding: 5px;")
        self.bloquear_ui(False)

