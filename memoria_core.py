import logging
from mem0 import Memory
from mem0.llms.openai import OpenAILLM

logger = logging.getLogger("Memoria")

# Parche necesario para que Mem0 funcione con LM Studio
_original_generate_response = OpenAILLM.generate_response
def _generate_response_patched(self, messages, response_format=None, tools=None, tool_choice=None):
    if response_format and response_format.get("type") == "json_object": response_format = None
    return _original_generate_response(self, messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice)
OpenAILLM.generate_response = _generate_response_patched

class GestorMemoria:
    def __init__(self):
        self.memoria = None

    def inicializar(self, modelo_cargado):
        try:
            config = {
                "llm": {"provider": "openai", "config": {"model": modelo_cargado, "api_key": "lm-studio", "openai_base_url": "http://localhost:1234/v1"}},
                "embedder": {"provider": "huggingface", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
                "vector_store": {"provider": "chroma", "config": {"collection_name": "asistente_db", "path": "./memoria_local_db"}}
            }
            self.memoria = Memory.from_config(config)
            return True
        except Exception as e:
            logger.error(f"Error al inicializar memoria: {e}")
            return False

    def buscar_contexto(self, texto_usuario, user_id, limite=5):
        if not self.memoria or not texto_usuario: return ""
        try:
            recuerdos = self.memoria.search(query=texto_usuario, filters={"user_id": user_id})
            lista = [m["memory"] for m in (recuerdos.get("results", []) if isinstance(recuerdos, dict) else recuerdos)[:limite]] if recuerdos else []
            return "\n".join([f"- {r}" for r in lista])
        except Exception as e:
            logger.warning(f"Error buscando recuerdos: {e}")
            return ""

    def evaluar_y_guardar(self, texto_usuario, respuesta_ia, user_id):
        if not self.memoria or not texto_usuario: return False
        if len(texto_usuario) > 20 and any(p in texto_usuario.lower() for p in ["prefiero", "mi proyecto", "estoy trabajando", "recuerda", "me gusta", "me llamo"]):
            try:
                self.memoria.add(messages=[{"role": "user", "content": texto_usuario}, {"role": "assistant", "content": respuesta_ia}], user_id=user_id)
                return True
            except Exception as e:
                logger.warning(f"Error guardando memoria: {e}")
        return False