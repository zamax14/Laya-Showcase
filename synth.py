"""Datos sintéticos para la Mesa de ayuda: un LLM escribe textos con la respuesta decidida de antemano y se guardan en CSV.

    python synth.py --prompt "incidencias de TI en un hospital" --n 100            # Ollama local (gemma3:12b)
    python synth.py --prompt "reportes de clientes de un banco" --modelo qwen3-coder:30b
    python synth.py --n 720 --backend openrouter                                    # GPT-5.6 Luna vía OpenRouter

Cada petición al LLM es para una combinación fija de categoría, prioridad y bloqueo, repartidas por igual, así que la
etiqueta de cada texto se conoce por construcción. El prompt solo cambia el contexto: sector, tipo de texto
(tickets, incidencias, reportes, correos), tono. Se descartan los textos que delatan la respuesta y los títulos
repetidos, en el CSV o respecto de los 20 tickets del benchmark. Las filas se añaden a data/sintetico.csv, que es lo
que lee scripts/finetune_mesa.py para reentrenar.
"""
import argparse
import csv
import hashlib
import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from fastload import secret
from remote import OPENROUTER, post
from tickets import CATEGORIES, LEAK_HINTS, PRIORITIES, TICKETS

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "data" / "sintetico.csv"
FIELDS = ["id", "titulo", "solicitante", "area", "descripcion", "categoria", "prioridad", "bloquea",
          "contexto", "modelo", "creado"]
PER_CALL = 5
LEVELS = list(PRIORITIES)
# Baja y media nunca bloquean; alta y crítica pueden o no (un fraude es crítico aunque nadie deje de trabajar).
SPECS = [(c, p, b) for c in CATEGORIES for p in LEVELS for b in ((False,) if p in ("baja", "media") else (False, True))]
AREAS = ["Finanzas", "Ventas", "Marketing", "Operaciones", "Logística", "Recursos Humanos", "Dirección", "Compras",
         "Atención al cliente", "Legal", "Producción", "Almacén"]
PROMPT = '''Escribe {n} textos distintos entre sí, en español, dirigidos al soporte de TI de una organización.
Contexto: {context}

Todos corresponden a esta situación:
- Equipo que debe atenderlo: {team} ({criterion}).
- Prioridad: {priority} ({priority_text}).
- ¿Alguien no puede hacer su trabajo esencial ahora mismo, sin alternativa?: {blocking}.

Reglas:
- Escríbelos como quien los envía, de 50 a 130 palabras. Varía la longitud, el tono y el nivel de detalle.
- Da contexto concreto: desde cuándo, qué equipo o sistema, mensajes de error literales si los hay, qué se probó, a cuántas personas afecta, plazos e impacto.
- No nombres el equipo que debe atenderlo ni la categoría, y no hagas comentarios que den la respuesta («no es un fallo de…», «no hay indicios de…», «corresponde a…»).
- A veces menciona otros sistemas que siguen funcionando o que se ven afectados sin ser la causa, como pasa en la vida real.
- Área del solicitante: una de {areas}. Inventa nombres y apellidos hispanos variados.
- Situaciones distintas de estas, que ya existen: {seen}.'''
DEFAULT_CONTEXT = "tickets de la mesa de ayuda de una empresa mediana"


class Ticket(BaseModel):
    """Un texto generado. Las comprobaciones no entran en el esquema (OpenRouter en modo estricto no las admite)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    titulo: str
    solicitante: str
    area: str
    descripcion: str

    @field_validator("titulo", "solicitante", "area")
    @classmethod
    def not_empty(cls, value):
        if not value:
            raise ValueError("vacío")
        return value

    @field_validator("descripcion")
    @classmethod
    def long_enough(cls, value):
        if len(value.split()) < 25:  # La regla pide de 50 a 130 palabras; por debajo de 25 no hay contexto.
            raise ValueError(f"descripción de {len(value.split())} palabras")
        return value


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickets: list[Ticket]


# El mismo esquema restringe la salida en Ollama (format) y en OpenRouter (json_schema estricto).
SCHEMA = Batch.model_json_schema()


def parse(content):
    """Valida la respuesta del LLM; si no es un lote de tickets bien formado, la llamada se descarta entera."""
    return [t.model_dump() for t in Batch.model_validate_json(content).tickets]


def norm(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", text.encode("ascii", "ignore").decode()).strip()


def leaks(text, category):
    """Frases que delatan la respuesta, o el nombre de la propia categoría."""
    text = text.lower()
    return any(h in text for h in LEAK_HINTS) or CATEGORIES[category][0].lower() in text


def prompt_for(spec, context, seen, rng, count=PER_CALL):
    category, priority, blocking = spec
    name, _, criterion = CATEGORIES[category]
    return PROMPT.format(n=count, context=context, team=name, criterion=criterion, priority=PRIORITIES[priority][0],
                         priority_text=PRIORITIES[priority][1], blocking="sí" if blocking else "no",
                         areas=", ".join(rng.sample(AREAS, 4)), seen="; ".join(seen[-30:]) or "ninguna")


class Ollama:
    def __init__(self, model, url="http://localhost:11434"):
        self.model, self.url, self.parallel = model, url.rstrip("/"), 2  # Una GPU: más hilos solo hacen cola.

    def __call__(self, text):
        body = post(f"{self.url}/api/chat", {"model": self.model, "messages": [{"role": "user", "content": text}],
                                              "format": SCHEMA, "stream": False, "think": False,
                                              "options": {"temperature": 0.9}}, timeout=600)
        return parse(body["message"]["content"]), 0.0

    def unload(self):
        """Libera la VRAM al terminar: el entrenamiento suele ir después en la misma GPU."""
        post(f"{self.url}/api/generate", {"model": self.model, "keep_alive": 0})


class OpenRouter:
    parallel = 8

    def __init__(self, model):
        self.model, self.key = model, secret("OPENROUTER_API_KEY", "openrouter")
        if not self.key:
            raise SystemExit("Falta la llave de OpenRouter: OPENROUTER_API_KEY o el archivo «openrouter» en la raíz")

    def __call__(self, text):
        body = post(f"{OPENROUTER}/chat/completions", {
            "model": self.model, "messages": [{"role": "user", "content": text}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "tickets", "strict": True, "schema": SCHEMA}},
            "reasoning": {"effort": "low"}, "usage": {"include": True}}, self.key)
        cost = float((body.get("usage") or {}).get("cost") or 0)
        return parse(body["choices"][0]["message"]["content"]), cost

    def unload(self):
        pass


def read(path=CSV_PATH):
    """Filas del CSV con la forma de un ticket de tickets.py, para reutilizar ticket_state y benchmark.row."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{"id": r["id"], "titulo": r["titulo"], "solicitante": r["solicitante"], "area": r["area"],
                 "descripcion": r["descripcion"], "referencia": [r["categoria"], r["prioridad"], CATEGORIES[r["categoria"]][1]],
                 "bloquea": r["bloquea"] == "true", "contexto": r["contexto"]} for r in csv.DictReader(f)]


def generate(llm, n, context=DEFAULT_CONTEXT, path=CSV_PATH, seed=None):
    """Genera unas n filas repartidas entre las 36 combinaciones y las añade al CSV. Devuelve (filas, costo).

    Cada combinación se escribe en cuanto termina: si el proceso se corta, lo generado queda en el CSV.
    """
    taken = {norm(t["titulo"]) for t in TICKETS} | {norm(r["titulo"]) for r in read(path)}
    seed = seed if seed is not None else time.time_ns()
    specs = random.Random(seed).sample(SPECS, min(n, len(SPECS)))  # Con n < 36, n combinaciones al azar.
    per_spec = -(-n // len(specs))
    path.parent.mkdir(parents=True, exist_ok=True)
    written, lock = [], threading.Lock()

    def save(rows):
        with lock, path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, FIELDS)
            if f.tell() == 0:
                writer.writeheader()
            writer.writerows(rows)
            written.extend(rows)
            print(f"{len(written)}/{len(specs) * per_spec} filas", flush=True)

    def one(spec):
        # Las llamadas de una combinación van en serie para que cada una vea los títulos ya usados.
        category, priority, blocking = spec
        rng, rows, seen, cost = random.Random(f"{seed}-{spec}"), [], [], 0.0
        for _ in range(3 * -(-per_spec // PER_CALL)):  # Margen para los descartes.
            if len(rows) >= per_spec:
                break
            try:
                batch, spent = llm(prompt_for(spec, context, seen, rng, min(PER_CALL, per_spec - len(rows))))
            except ValidationError as exc:
                print(f"{category}/{priority}/{blocking}: respuesta descartada, {exc.error_count()} errores de formato", flush=True)
                continue
            except Exception as exc:
                print(f"{category}/{priority}/{blocking}: {type(exc).__name__}: {exc}", flush=True)
                continue
            cost += spent
            for t in batch:
                title = norm(t["titulo"])
                if title in taken or title in map(norm, seen) or leaks(t["descripcion"], category):
                    continue
                seen.append(t["titulo"])
                rows.append({**t, "id": hashlib.sha1((t["titulo"] + t["descripcion"]).encode()).hexdigest()[:12],
                             "categoria": category, "prioridad": priority, "bloquea": str(blocking).lower(),
                             "contexto": context, "modelo": llm.model,
                             "creado": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        save(rows[:per_spec])
        return cost

    with ThreadPoolExecutor(llm.parallel) as pool:
        cost = sum(pool.map(one, specs))
    llm.unload()
    return written, cost


def main():
    parser = argparse.ArgumentParser(description="Genera tickets sintéticos etiquetados y los añade a un CSV.")
    parser.add_argument("--prompt", default=DEFAULT_CONTEXT,
                        help="contexto: sector, tipo de texto (tickets, incidencias, reportes…), tono")
    parser.add_argument("--n", type=int, default=72, help="filas aproximadas; se reparten entre 36 combinaciones")
    parser.add_argument("--backend", choices=("ollama", "openrouter"), default="ollama")
    # qwen3.5:9b no sirve: sin razonar ignora el esquema y razonando tardó 148 s en devolver una respuesta vacía.
    parser.add_argument("--modelo", help="por defecto gemma3:12b en Ollama y openai/gpt-5.6-luna en OpenRouter")
    parser.add_argument("--ollama", default="http://localhost:11434", help="URL del servidor de Ollama")
    parser.add_argument("--salida", type=Path, default=CSV_PATH)
    args = parser.parse_args()
    llm = (Ollama(args.modelo or "gemma3:12b", args.ollama) if args.backend == "ollama"
           else OpenRouter(args.modelo or "openai/gpt-5.6-luna"))
    started = time.time()
    rows, cost = generate(llm, args.n, args.prompt, args.salida)
    counts = {c: sum(r["categoria"] == c for r in rows) for c in CATEGORIES}
    print(f"{len(rows)} filas nuevas en {args.salida} ({len(read(args.salida))} en total) en {time.time() - started:.0f} s"
          + (f" por US${cost:.3f}" if cost else "") + f" · por categoría: {counts}")


if __name__ == "__main__":
    main()
