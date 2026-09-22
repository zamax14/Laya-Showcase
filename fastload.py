"""Carga de Laya rápida y compartida entre las demos.

`build_model` crea el encoder con `AutoModel.from_config`, que rellena al azar 322 M de
parámetros; `load_state_dict(strict=True)` los reemplaza todos. Saltarse ese relleno baja la
carga en CPU de ~14 s a ~1,4 s y da exactamente los mismos pesos y logits.
"""
import os
import threading


def load_agent(subfolder="multilingual", device="cpu"):
    os.environ.setdefault("USE_TF", "0")
    import laya
    try:
        from transformers.initialization import no_init_weights
    except ImportError:  # transformers < 5 lo exponía en modeling_utils.
        from transformers.modeling_utils import no_init_weights
    # El contexto desactiva las funciones de init de torch mientras se construye el modelo.
    with no_init_weights():
        return laya.load("convaiinnovations/laya", subfolder=subfolder, device=device)


class SharedModel:
    """Una instancia de Laya para todas las demos; cada uso del modelo va en serie."""

    def __init__(self, max_len=2048, head_max_len=512):
        self.max_len, self.head_max_len = max_len, head_max_len
        self.agent, self.status, self.error = None, "idle", None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.agent is None:
                self.status = "loading"
                try:
                    # Sin tope de hilos: torch usa los núcleos físicos (medido: 4 hilos era un 35 % más lento).
                    agent = load_agent()
                except Exception as exc:
                    self.status, self.error = "error", f"{type(exc).__name__}: {exc}"
                    raise
                # max_len solo es un tope: el relleno es dinámico, no encarece estados cortos.
                agent.cfg["max_len"], agent.cfg["head_max_len"] = self.max_len, self.head_max_len
                self.agent, self.status = agent, "ready"
        return self.agent

    def tokens(self, text):
        agent = self.load()
        with self.lock:  # El tokenizador rápido no admite usos concurrentes.
            return agent.tok(text)["input_ids"]

    def predict(self, state, questions):
        agent = self.load()
        from laya.common import build_sequence
        with self.lock:
            # Laya trunca el estado sin avisar; aquí se rechaza antes de inferir.
            for question in questions.values():
                full, _ = build_sequence(agent.tok, state, agent._to_internal(question),
                                         10**6, self.head_max_len)
                if len(full) > self.max_len:
                    raise ValueError(f"El estado no cabe en el contexto: {len(full)} de {self.max_len} tokens")
            return agent.predict(state, questions)
