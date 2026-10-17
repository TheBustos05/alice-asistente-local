import html, os, re, threading, time
import psutil, pyqtgraph as pg
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton, QFileDialog, QLabel, QFrame, QSplitter
from cerebro import CerebroIA

class CircularGauge(QWidget):
    def __init__(self,title="RAM",color1="#89dceb",color2="#cba6f7"):
        super().__init__(); self.title=title; self.value=0.; self.c1=QColor(color1); self.c2=QColor(color2); self.setMinimumSize(135,135)
    def set_value(self,v): self.value=max(0.,min(100.,float(v))); self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); r=QRectF(14,14,self.width()-28,self.height()-28)
        p.setPen(QPen(QColor("#313244"),10,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawArc(r,0,360*16)
        g=QLinearGradient(r.topLeft(),r.bottomRight()); g.setColorAt(0,self.c1); g.setColorAt(1,self.c2); p.setPen(QPen(g,10,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawArc(r,90*16,int(-self.value*3.6*16))
        p.setPen(QColor("#a6adc8")); p.setFont(QFont("Segoe UI",9,QFont.Weight.Bold)); p.drawText(r.adjusted(0,-16,0,0),Qt.AlignmentFlag.AlignCenter,self.title)
        p.setPen(QColor("#cdd6f4")); p.setFont(QFont("Segoe UI",16,QFont.Weight.Bold)); p.drawText(r.adjusted(0,14,0,0),Qt.AlignmentFlag.AlignCenter,f"{int(self.value)}%")

class WorkerTelemetria(QThread):
    datos_actualizados=pyqtSignal(float,float,float)
    def __init__(self): super().__init__(); self.stop_event=threading.Event()
    def run(self):
        psutil.cpu_percent(interval=None)
        while not self.stop_event.wait(1):
            cpu=psutil.cpu_percent(interval=None); ram=psutil.virtual_memory(); self.datos_actualizados.emit(cpu,ram.percent,ram.used/(1024**3))
    def detener(self):
        self.stop_event.set()
        if self.isRunning() and QThread.currentThread()!=self: self.wait()

class WorkerInicializador(QThread):
    terminado=pyqtSignal(bool)
    def __init__(self,cerebro): super().__init__(); self.cerebro=cerebro
    def run(self):
        try: self.terminado.emit(bool(self.cerebro.encender_motor()))
        except Exception: self.terminado.emit(False)

class WorkerMensaje(QThread):
    respuesta_lista=pyqtSignal(str,float,str)
    def __init__(self,cerebro,texto,ruta): super().__init__(); self.cerebro=cerebro; self.texto=texto; self.ruta=ruta
    def run(self):
        t=time.monotonic()
        try: answer=self.cerebro.procesar_mensaje(self.texto,self.ruta); model=getattr(self.cerebro,"ultimo_modelo_usado",None) or "Modelo no identificado"
        except Exception: answer="Ocurrió un error al procesar la respuesta."; model=getattr(self.cerebro,"ultimo_modelo_usado",None) or "Modelo no identificado"
        self.respuesta_lista.emit(str(answer),time.monotonic()-t,str(model))

class WorkerCierre(QThread):
    def __init__(self,cerebro,workers,tele): super().__init__(); self.cerebro=cerebro; self.workers=tuple(workers); self.tele=tele
    def run(self):
        if self.tele: self.tele.detener()
        self.cerebro.apagar_motor()
        for worker in self.workers:
            while worker.isRunning(): worker.wait(250)
        self.cerebro.apagar_motor()

class InterfazBase(QWidget):
    senial_log=pyqtSignal(str,str)
    def __init__(self):
        super().__init__(); self.ruta_imagen=None; self.t0=time.monotonic(); self.tokens=0; self.cpu=[0.]*40; self.ram=[0.]*40; self._cierre_completado=False; self._worker_cierre=None
        self.worker_init=self.worker_mensaje=self.worker_telemetria=None; self.configurar_ui(); self.senial_log.connect(self.procesar_log_sistema)
        self.cerebro=CerebroIA(callback_log=self._emitir_log,callback_refresh=lambda:None)
        self.worker_telemetria=WorkerTelemetria(); self.worker_telemetria.datos_actualizados.connect(self.actualizar_graficos_hardware); self.worker_telemetria.start(); self.iniciar_motor_async()
    def configurar_ui(self):
        self.setWindowTitle("Alice — Centro de Control & Núcleo Conversacional"); self.resize(1100,740)
        self.setStyleSheet("QWidget{background:#11111b;color:#cdd6f4;font-family:'Segoe UI'} QFrame#Panel{background:#181825;border:1px solid #313244;border-radius:10px} QTextEdit{background:#11111b;border:1px solid #313244;border-radius:8px;padding:8px} QLineEdit{background:#1e1e2e;border:1px solid #45475a;padding:10px;border-radius:6px;color:#cdd6f4} QPushButton{border-radius:6px;font-weight:bold;padding:8px}")
        root=QVBoxLayout(self); split=QSplitter(Qt.Orientation.Horizontal); left=QWidget(); lv=QVBoxLayout(left)
        tele=QFrame(); tele.setObjectName("Panel"); tv=QVBoxLayout(tele); tv.addWidget(QLabel("📊 TELEMETRÍA EN VIVO")); d=QHBoxLayout()
        self.gauge_ram=CircularGauge("RAM","#a6e3a1"); self.gauge_cpu=CircularGauge("CPU","#89b4fa","#f38ba8"); d.addWidget(self.gauge_ram); d.addWidget(self.gauge_cpu); tv.addLayout(d)
        self.lbl_vram_info=QLabel("● VRAM: No disponible"); tv.addWidget(self.lbl_vram_info)
        pg.setConfigOptions(antialias=True); self.grafica=pg.PlotWidget(); self.grafica.setBackground("#11111b"); self.grafica.setFixedHeight(140); self.grafica.setYRange(0,100); self.grafica.hideAxis("bottom"); self.grafica.showGrid(x=False,y=True,alpha=.15)
        self.curva_cpu=self.grafica.plot(pen=pg.mkPen("#89b4fa",width=2),fillLevel=0,brush=(137,180,250,35)); self.curva_ram=self.grafica.plot(pen=pg.mkPen("#fab387",width=2),fillLevel=0,brush=(250,179,135,35)); tv.addWidget(self.grafica); lv.addWidget(tele)
        boot=QFrame(); boot.setObjectName("Panel"); bv=QVBoxLayout(boot); bv.addWidget(QLabel("☑️ SECUENCIA DE ARRANQUE")); self.consola_boot=QTextEdit(); self.consola_boot.setReadOnly(True); bv.addWidget(self.consola_boot)
        row=QHBoxLayout(); self.lbl_tokens=QLabel("⚡ TOKENS/S ESTIMADOS: --<br>🪙 TOKENS ESTIMADOS: 0"); self.lbl_reloj_boot=QLabel("⏱️ 0s"); row.addWidget(self.lbl_tokens); row.addWidget(self.lbl_reloj_boot); bv.addLayout(row); lv.addWidget(boot)
        chat=QFrame(); chat.setObjectName("Panel"); cv=QVBoxLayout(chat); head=QHBoxLayout(); head.addWidget(QLabel("💬 NÚCLEO CONVERSACIONAL — ALICE")); head.addStretch(); self.badge_modo=QLabel("MODO HÍBRIDO (INICIANDO)"); head.addWidget(self.badge_modo); cv.addLayout(head)
        self.pantalla_chat=QTextEdit(); self.pantalla_chat.setReadOnly(True); cv.addWidget(self.pantalla_chat); self.hud_tool=QLabel(); self.hud_tool.hide(); cv.addWidget(self.hud_tool)
        controls=QHBoxLayout(); self.btn_imagen=QPushButton("📷"); self.btn_imagen.clicked.connect(self.adjuntar_imagen); self.entrada=QLineEdit(); self.entrada.setPlaceholderText("Escribe tu instrucción aquí..."); self.entrada.returnPressed.connect(self.enviar_mensaje); self.btn_enviar=QPushButton("Enviar"); self.btn_enviar.clicked.connect(self.enviar_mensaje)
        controls.addWidget(self.btn_imagen); controls.addWidget(self.entrada); controls.addWidget(self.btn_enviar); cv.addLayout(controls)
        split.addWidget(left); split.addWidget(chat); split.setSizes([440,640]); root.addWidget(split); self.label_estado=QLabel("⏳ Inicializando Alice…"); root.addWidget(self.label_estado); self.bloquear_ui(True)
    def actualizar_graficos_hardware(self,cpu,ram_pct,ram_gb):
        self.gauge_cpu.set_value(cpu); self.gauge_ram.set_value(ram_pct); self.lbl_vram_info.setText(f"● VRAM: No disponible | RAM del sistema: {ram_gb:.1f} GB")
        self.cpu=self.cpu[1:]+[cpu]; self.ram=self.ram[1:]+[ram_pct]; self.curva_cpu.setData(self.cpu); self.curva_ram.setData(self.ram)
    def bloquear_ui(self,v):
        self.entrada.setDisabled(v); self.btn_enviar.setDisabled(v); self.btn_imagen.setDisabled(v)
        if not v: self.entrada.setFocus()
    def _emitir_log(self,text,color="#f38ba8"): self.senial_log.emit(str(text),str(color))
    def procesar_log_sistema(self,text,color):
        clean=text.replace("<br>"," ").strip(); safe=html.escape(clean).replace("&lt;b&gt;","<b>").replace("&lt;/b&gt;","</b>")
        color=color if re.fullmatch(r"#[0-9a-fA-F]{6}",color) else "#89b4fa"
        if "🛠️ Tool:" in text: self.hud_tool.setText(html.escape(text)); self.hud_tool.show()
        tag="OK" if "SISTEMA LISTO" in clean else ("ACTIVO" if any(x in clean for x in ("Cargando","Iniciando","Delegando")) else "INFO")
        self.consola_boot.append(f"<span style='color:#7f849c'>[{time.monotonic()-self.t0:05.2f}s]</span> <span style='color:{color}'>{safe}</span> <b>{tag}</b>")
    def iniciar_motor_async(self):
        self.segundos=0; self.timer_carga=QTimer(self); self.timer_carga.timeout.connect(self.actualizar_temporizador); self.timer_carga.start(1000)
        self.worker_init=WorkerInicializador(self.cerebro); self.worker_init.terminado.connect(self.al_terminar_motor); self.worker_init.start()
    def actualizar_temporizador(self):
        self.segundos+=1; self.lbl_reloj_boot.setText(f"⏱️ {self.segundos}s"); self.label_estado.setText(f"⏳ Sincronizando modelos y memoria [{self.segundos}s]")
    def al_terminar_motor(self,ok):
        self.timer_carga.stop(); self.badge_modo.setText("MODO HÍBRIDO (ACTIVO)" if ok else "FALLO DE CARGA"); self.label_estado.setText("✅ Sistema en línea" if ok else "❌ Fallo de carga — verifica LM Studio")
        if ok: self.bloquear_ui(False)
        else: self.imprimir_chat_sistema("No se pudo inicializar Alice. Revisa LM Studio.","#f38ba8")
    def adjuntar_imagen(self):
        path,_=QFileDialog.getOpenFileName(self,"Seleccionar imagen","","Imágenes (*.png *.jpg *.jpeg *.webp)")
        if path: self.ruta_imagen=path; self.pantalla_chat.append(f"📎 Imagen preparada: <b>{html.escape(os.path.basename(path))}</b>")
    def imprimir_chat_sistema(self,text,color):
        color=color if re.fullmatch(r"#[0-9a-fA-F]{6}",color) else "#89b4fa"; self.pantalla_chat.append(f"<span style='color:{color}'><b>[SISTEMA]</b></span> {html.escape(str(text)).replace(chr(10),'<br>')}")
    def enviar_mensaje(self):
        text=self.entrada.text().strip()
        if not text and not self.ruta_imagen: return
        self.pantalla_chat.append(f"<b style='color:#89b4fa'>Tú:</b><div>{html.escape(text).replace(chr(10),'<br>')}</div>")
        self.entrada.clear(); self.bloquear_ui(True); self.hud_tool.hide(); self.label_estado.setText("⏳ Alice está procesando…")
        self.worker_mensaje=WorkerMensaje(self.cerebro,text,self.ruta_imagen); self.worker_mensaje.respuesta_lista.connect(self.al_terminar_mensaje); self.worker_mensaje.start()
    def al_terminar_mensaje(self,answer,latency,model):
        self.hud_tool.hide(); self.ruta_imagen=None; count=max(1,int(len(answer.split())*1.35)); self.tokens+=count; tps=count/max(.1,latency)
        shown=f"Qwen 3 VL 8B ({model})" if model==getattr(self.cerebro,"modelo_pesado",None) else (f"Stheno 8B ({model})" if model==getattr(self.cerebro,"modelo_rapido",None) else model)
        self.lbl_tokens.setText(f"⚡ TOKENS/S ESTIMADOS: {tps:.1f}<br>🪙 TOKENS ESTIMADOS: {self.tokens}")
        self.pantalla_chat.append(f"<b style='color:#cba6f7'>👑 [{html.escape(shown)}] Alice</b> <small>{tps:.1f} t/s estimados | Latencia {int(latency*1000)} ms</small><div style='color:#a6e3a1'>{html.escape(answer).replace(chr(10),'<br>')}</div>")
        bar=self.pantalla_chat.verticalScrollBar(); bar.setValue(bar.maximum()); self.label_estado.setText("✅ Sistema en línea"); self.bloquear_ui(False)
    def closeEvent(self,event):
        if self._cierre_completado: event.accept(); return
        event.ignore()
        if self._worker_cierre is not None and self._worker_cierre.isRunning(): return
        self.setEnabled(False); self.label_estado.setText("Cerrando Alice y descargando modelos…")
        active=[w for w in (self.worker_init,self.worker_mensaje) if w is not None and w.isRunning()]
        self._worker_cierre=WorkerCierre(self.cerebro,active,self.worker_telemetria); self._worker_cierre.finished.connect(self._cierre_terminado); self._worker_cierre.start()
    def _cierre_terminado(self): self._cierre_completado=True; self.close()
