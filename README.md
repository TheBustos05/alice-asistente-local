# ⚙️ Alice — Asistente de Escritorio Modular con IA Híbrida

> *"Artificial Labile Intelligence Cybernated Existence"*

**Alice** es una asistente virtual de escritorio desarrollada en Python, diseñada específicamente para asistir en flujos de trabajo de **programación (Python)** y **gestión del sistema de archivos**. 

A diferencia de los chatbots tradicionales, Alice cuenta con una arquitectura desacoplada (MVC), memoria vectorial persistente a largo plazo, ejecución de herramientas locales en entorno seguro (*Sandboxing*) y una personalidad compleja (*Tsundere* / Dama Noble perfeccionista) blindada mediante ingeniería de prompts avanzada.

---

## ✨ Características Principales

* **🧠 Enrutador Dinámico de Modelos (MoE Local/Híbrido):** Sistema inteligente en `cerebro.py` que evalúa la complejidad del mensaje antes de procesarlo:
  * **Recepcionista (`l3-8b-stheno-v3.2-iq-imatrix`):** Especializado en conversación rápida, interpretación de rol (Roleplay) y ejecución de herramientas ligeras.
  * **Especialista (`qwen/qwen3-vl-8b`):** Se activa automáticamente al detectar imágenes adjuntas o consultas pesadas de código, scripts y arquitectura.
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
* **El Fallo:** Cuando el usuario mencionaba que tenía una carpeta llamada *"Programación"* o *"Blender"*, el enrutador creía que se le estaba pidiendo una tarea pesada y cargaba innecesariamente el modelo especialista (Qwen VL).
* **Solución:** En proceso

### 4. ⚠️ Limitación Actual: Cuello de Botella de RAM / VRAM (En evaluación) (Solo tengo 16GB de RAM)
* **El Problema:** En su primer arranque (compilación de caché), el modelo tardó más de **10 minutos** en inicializar (reduciéndose luego a ~1 minuto). Mantener dos modelos de 8B de parámetros (`Stheno` y `Qwen VL`) haciendo *Model Swapping* exige entre **6 GB y 8 GB de VRAM/RAM libre**. En hardware modesto, el sistema operativo recurre a la paginación en disco duro, degradando el rendimiento general de la PC.
* **Soluciones Propuestas (Hoja de Ruta):**
  1. **Migración del Cerebro a API Externa (OpenRouter):** Mantener la interfaz, las herramientas CRUD y ChromaDB en local (consumo < 150 MB de RAM), delegando la inferencia de Stheno/Qwen a la nube por fracciones de centavo o mediante capas `:free`.
  2. **Optimización del Embedder:** Cambiar `all-MiniLM-L6-v2` por un modelo multilingüe (`paraphrase-multilingual-MiniLM-L12-v2`) para mejorar la precisión semántica en español.
  3. **Implementación de Streaming y Percepción del Sistema:** Añadir lectura de procesos activos (`psutil`) y respuesta por fragmentos para reducir la latencia percibida.

### 5. ⚠️ En proceso de Suspender o Migrar parcialmente el Proyecto a la Nube
---

## 👤 Autor
Desarrollado y diseñado por **A.C.B.** (`TheBustos05`).