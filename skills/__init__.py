import os
import pkgutil
import importlib

FUNCIONES_DISPONIBLES = {}
TOOLS = []

_carpeta_actual = os.path.dirname(__file__)

for _, nombre_modulo, _ in pkgutil.iter_modules([_carpeta_actual]):
    if nombre_modulo.startswith("skill_"):
        modulo = importlib.import_module(f".{nombre_modulo}", package=__name__)
        if hasattr(modulo, "FUNCIONES"):
            FUNCIONES_DISPONIBLES.update(modulo.FUNCIONES)
        if hasattr(modulo, "TOOLS"):
            TOOLS.extend(modulo.TOOLS)