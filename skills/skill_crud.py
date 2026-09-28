import os
import shutil

DIRECTORIO_BASE = os.path.abspath("./workspace_ia")
os.makedirs(DIRECTORIO_BASE, exist_ok=True)

def _resolver_ruta(ruta):
    ruta_final = os.path.abspath(ruta) if os.path.isabs(ruta) else os.path.abspath(os.path.join(DIRECTORIO_BASE, ruta))
    if os.path.commonpath([ruta_final, DIRECTORIO_BASE]) != DIRECTORIO_BASE:
        ruta_final = os.path.join(DIRECTORIO_BASE, os.path.basename(ruta_final))
    return ruta_final

def herramienta_crear_archivo(ruta, contenido=""):
    try:
        ruta_final = _resolver_ruta(ruta)
        os.makedirs(os.path.dirname(ruta_final) or ".", exist_ok=True)
        with open(ruta_final, "w", encoding="utf-8") as f: f.write(contenido)
        return {"ok": True, "ruta": ruta_final}
    except Exception as e: return {"ok": False, "error": str(e)}

def herramienta_leer_archivo(ruta, max_caracteres=4000):
    try:
        ruta_final = _resolver_ruta(ruta)
        if not os.path.isfile(ruta_final): return {"ok": False, "error": "No existe."}
        with open(ruta_final, "r", encoding="utf-8", errors="replace") as f: return {"ok": True, "contenido": f.read()[:max_caracteres]}
    except Exception as e: return {"ok": False, "error": str(e)}

def herramienta_listar_directorio(ruta="."):
    try:
        ruta_final = _resolver_ruta(ruta)
        elementos = [{"nombre": n, "tipo": "carpeta" if os.path.isdir(os.path.join(ruta_final, n)) else "archivo"} for n in sorted(os.listdir(ruta_final))]
        return {"ok": True, "elementos": elementos}
    except Exception as e: return {"ok": False, "error": str(e)}

def herramienta_crear_carpeta(ruta):
    try:
        os.makedirs(_resolver_ruta(ruta), exist_ok=True)
        return {"ok": True, "mensaje": "Carpeta creada."}
    except Exception as e: return {"ok": False, "error": str(e)}

def herramienta_eliminar(ruta):
    try:
        ruta_final = _resolver_ruta(ruta)
        if os.path.isfile(ruta_final): os.remove(ruta_final)
        elif os.path.isdir(ruta_final): shutil.rmtree(ruta_final)
        else: return {"ok": False, "error": "No existe."}
        return {"ok": True, "mensaje": "Eliminado."}
    except Exception as e: return {"ok": False, "error": str(e)}

def herramienta_mover(origen, destino):
    try:
        shutil.move(_resolver_ruta(origen), _resolver_ruta(destino))
        return {"ok": True, "mensaje": "Movido exitosamente."}
    except Exception as e: return {"ok": False, "error": str(e)}

FUNCIONES = {
    "crear_archivo": herramienta_crear_archivo,
    "leer_archivo": herramienta_leer_archivo,
    "listar_directorio": herramienta_listar_directorio,
    "crear_carpeta": herramienta_crear_carpeta,
    "eliminar": herramienta_eliminar,
    "mover": herramienta_mover,
}

TOOLS = [
    {"type": "function", "function": {"name": "crear_archivo", "description": "Crea o sobrescribe un archivo de texto.", "parameters": {"type": "object", "properties": {"ruta": {"type": "string"}, "contenido": {"type": "string"}}, "required": ["ruta", "contenido"]}}},
    {"type": "function", "function": {"name": "leer_archivo", "description": "Lee el contenido de un archivo.", "parameters": {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": ["ruta"]}}},
    {"type": "function", "function": {"name": "listar_directorio", "description": "Lista archivos en una ruta.", "parameters": {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "crear_carpeta", "description": "Crea una nueva carpeta.", "parameters": {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": ["ruta"]}}},
    {"type": "function", "function": {"name": "eliminar", "description": "Elimina un archivo o carpeta.", "parameters": {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": ["ruta"]}}},
    {"type": "function", "function": {"name": "mover", "description": "Mueve un archivo o carpeta.", "parameters": {"type": "object", "properties": {"origen": {"type": "string"}, "destino": {"type": "string"}}, "required": ["origen", "destino"]}}}
]