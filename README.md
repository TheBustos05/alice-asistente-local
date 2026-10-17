# ⚙️ Alice — Asistente de Escritorio Modular con IA Híbrida

> *"Artificial Labile Intelligence Cybernated Existence"*

**Alice** es una asistente virtual de escritorio desarrollada en Python, diseñada específicamente para asistir en flujos de trabajo de **programación (Python)** y **gestión del sistema de archivos**. 

A diferencia de los chatbots tradicionales, Alice cuenta con una arquitectura desacoplada (MVC), memoria vectorial persistente a largo plazo, ejecución de herramientas locales en entorno seguro (*Sandboxing*) y una personalidad compleja (*Tsundere* / Dama Noble perfeccionista) blindada mediante ingeniería de prompts avanzada.

---

## ✨ Características Principales

* **🧠 Enrutador Dinámico de Modelos (local):** Sistema en `cerebro.py` que selecciona el modelo antes de procesar el mensaje:
  * **Recepcionista (`l3-8b-stheno-v3.2-iq-imatrix`):** Especializado en conversación rápida, interpretación de rol (Roleplay) y ejecución de herramientas ligeras.
  * **Especialista (`qwen/qwen3-vl-8b`):** Se selecciona para imágenes adjuntas y solicitudes explícitas de creación, revisión o depuración de código; mencionar de pasada términos como “Python” no basta.
  * El estado se consulta con `lms ps --json`, sin generar una petición artificial de prueba en cada turno. Al cambiar de modelo, Alice descarga los modelos cargados y carga solo el seleccionado con contexto de 4096 tokens y descarga automática tras 15 minutos de inactividad.
* **💾 Memoria Semántica a Largo Plazo:** Implementación de **Mem0** junto con **ChromaDB** y modelos *Embedders* de HuggingFace (`all-MiniLM-L6-v2`). Alice convierte hechos relevantes del usuario en vectores matemáticos, recordando preferencias y proyectos entre sesiones sin saturar la ventana de contexto.
* **🛠️ Sistema Dinámico de Plugins (`skills/`):** Cargador automático de herramientas (*Tool Calling*). Incluye un módulo CRUD (`skill_crud.py`) con *Sandboxing* estricto dentro de `./workspace_ia` para crear, leer, listar, mover y eliminar archivos reales sin riesgo para el sistema operativo.
* **⚡ Interfaz Asíncrona (PyQt6):** Diseño oscuro inspirado en *Catppuccin Mocha*. Utiliza subprocesos (`QThread`) y señales (`pyqtSignal`) para evitar el congelamiento de la ventana durante la carga de modelos en VRAM o la generación de respuestas, incorporando un cronómetro de estado en tiempo real (`QTimer`).

---

## 📂 Arquitectura del Proyecto

~~~text
Alice/
├── main.py              # Lanzador ligero (Inicializador de la aplicación gráfica)
├── interfaz.py          # Vista / Frontend en PyQt6 (UI, QThreads y QTimer)
├── cerebro.py           # Controlador principal, Router de modelos y System Prompt
├── memoria_core.py      # Gestión de memoria vectorial (Mem0 + ChromaDB)
├── .gitignore           # Exclusión de bases de datos locales, cachés y entorno
├── skills/              # Módulos de herramientas (Plugins dinámicos)
│   ├── __init__.py      # Inyector automático de herramientas
│   └── skill_crud.py    # Operaciones de archivos con Sandboxing seguro
├── memoria_local_db/    # (Ignorado en Git) Almacén persistente de ChromaDB
└── workspace_ia/        # (Ignorado en Git) Espacio de trabajo seguro de Alice
~~~

---

## 🚀 Requisitos e Instalación

### 1. Clonar el repositorio
~~~bash
git clone https://github.com/TheBustos05/alice-asistente-local.git
cd alice-asistente-local
~~~

### 2. Instalar dependencias principales
~~~bash
pip install PyQt6 openai mem0ai chromadb sentence-transformers
~~~

### 3. Configurar el Motor de Inferencia
* **Modo Local:** Tener instalado **LM Studio** con el CLI habilitado (`lms`) y los modelos `l3-8b-stheno-v3.2-iq-imatrix` y `qwen/qwen3-vl-8b` descargados.

### 4. Ejecutar a Alice
~~~bash
python main.py
~~~

---

## 🛠️ Bitácora de Ingeniería: Fallos Encontrados y Soluciones

Durante el desarrollo de Alice se presentaron diversos retos técnicos y cuellos de botella. Este apartado documenta los fallos críticos y cómo se resolvieron (o su estado actual):

### 1. Congelamiento de la Interfaz al Iniciar (Main Thread Blocking)
* **El Fallo:** Al ejecutar el programa, la ventana de PyQt6 no aparecía o Windows marcaba *"No responde"* mientras LM Studio cargaba los modelos en segundo plano.
* **Causa:** La carga del motor y las peticiones HTTP se ejecutaban en el mismo hilo de dibujo de la interfaz gráfica.
* **Solución:** Se desacopló `main.py` de `interfaz.py` y se implementaron `WorkerInicializador(QThread)` y `WorkerMensaje(QThread)` junto con un temporizador `QTimer` que muestra los segundos de carga en tiempo real.

### 2. Alucinación de Archivos y Carpetas (Falsa Lectura)
* **El Fallo:** Al preguntarle a Alice qué carpetas existían en su espacio de trabajo, inventaba directorios inexistentes (*"Carpeta Secreta"*, *"Estrategias de Optimización"*) por exceso de creatividad del modelo de Roleplay en lugar de ejecutar `listar_directorio`.
* **Causa:** Los modelos conversacionales priorizan la fluidez narrativa sobre el *Tool Calling* si no tienen una restricción explícita.
* **Solución:** En proceso

### 3. Falsos Positivos en el Enrutador Dinámico
* **El Fallo:** El enrutador anterior activaba el especialista por palabras aisladas como "Python", "Blender" o "analiza", incluso en consultas casuales.
* **Solución:** Ahora requiere una petición de acción técnica vinculada explícitamente con código, scripts, funciones, clases, programas, algoritmos o SQL. Las imágenes siguen activando Qwen.

### 4. ⚠️ Uso de memoria en equipos con 16 GB de RAM
* **El Problema:** El uso real depende de la cuantización, del tamaño de contexto y de la memoria disponible en GPU; dos modelos de 8B pueden provocar paginación en un equipo modesto. Los valores concretos varían por modelo y hardware.
* **Medidas aplicadas al módulo de modelos:** Alice mantiene como máximo un modelo cargado cuando cambia entre Stheno y Qwen, limita el contexto solicitado a 4096 tokens y configura una descarga tras 15 minutos de inactividad. Una solicitud puede tardar hasta 300 segundos; las peticiones no se reintentan automáticamente. La aplicación no puede impedir que otros procesos carguen modelos ni garantizar que 16 GB sean suficientes para cualquier cuantización.
* **Otras ideas en evaluación:**
  1. **Migración del Cerebro a API Externa (OpenRouter):** Mantener la interfaz, las herramientas CRUD y ChromaDB en local (consumo < 150 MB de RAM), delegando la inferencia de Stheno/Qwen a la nube por fracciones de centavo o mediante capas `:free`.
  2. **Optimización del Embedder:** Cambiar `all-MiniLM-L6-v2` por un modelo multilingüe (`paraphrase-multilingual-MiniLM-L12-v2`) para mejorar la precisión semántica en español.
  3. **Implementación de Streaming y Percepción del Sistema:** Añadir lectura de procesos activos (`psutil`) y respuesta por fragmentos para reducir la latencia percibida.

### 5. ⚠️ En proceso de Suspender o Migrar parcialmente el Proyecto a la Nube
---

## 👤 Autor
Desarrollado y diseñado por **A.C.B.** (`TheBustos05`).
