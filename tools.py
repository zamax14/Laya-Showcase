"""Enrutado de herramientas: Laya decide qué llamadas MCP hace falta para una petición.

Cada vuelta son tres preguntas tipadas y una regla:

    ¿ya está cubierta? (noul) → ¿qué servidor? (choice) → ¿qué herramienta? (choice) → prerrequisitos (regla)

Un `choice` sobre las 20 herramientas a la vez no discrimina (medido: 1 de 8 rutas). Preguntando
primero el servidor y luego la herramienta de ese servidor, el servidor elegido pertenece a la ruta
correcta en 7 de 8 peticiones. El orden no se le pregunta: si a una herramienta le falta un
argumento, las reglas ponen delante las que lo producen, como en la Ruta de aprendizaje.
"""
import math
import time

MAX_PROMPT = 300
MAX_TURNS = 4  # Vueltas de decisión; cada una puede añadir varias llamadas encadenadas.
STOP_THRESHOLD = .35  # Por encima, Laya considera cubierta la petición (ajustado sobre las 8 de ejemplo).

# Lo que una herramienta deja disponible: sería el argumento de las siguientes.
DATA = {"eventos": "los eventos de la agenda", "hueco": "un hueco libre", "contacto": "la ficha de un contacto",
        "correos": "una lista de correos", "texto_correo": "el texto de un correo",
        "oportunidades": "las oportunidades del cliente", "documento": "un documento localizado",
        "texto_documento": "el texto de un documento", "tabla": "una tabla de datos",
        "metricas": "métricas calculadas", "grafica": "una gráfica", "tickets": "incidencias de soporte",
        "enlaces": "enlaces de una búsqueda", "pagina": "el contenido de una página"}

# Criterios de servidor en inglés: con los mismos criterios en español, el servidor elegido acertaba
# el primer paso en 3 de 8 peticiones en lugar de 5. La página los muestra siempre en español.
SERVERS = {
    "agenda": ("Agenda", "calendar: meetings, appointments, free slots, what is on my schedule"),
    "correo": ("Correo", "email: inbox, reading a message, writing or sending an email"),
    "crm": ("CRM", "crm: customers, company records, sales opportunities, pipeline, customer notes"),
    "archivos": ("Archivos", "files: documents, contracts, reports stored on the shared drive"),
    "datos": ("Datos", "data: business figures, sales, revenue, database queries, totals and charts"),
    "soporte": ("Soporte", "support: incidents, tickets, reported technical problems"),
    "web": ("Web", "web: internet search, public pages, competitors, news"),
}

TOOLS = [
    {"id": "ver_agenda", "servidor": "agenda", "necesita": [], "produce": ["eventos"],
     "descripcion": "Lee los eventos del calendario en un rango de fechas.",
     "criterio": "agenda: mi calendario, qué tengo, eventos de un día o una semana"},
    {"id": "buscar_hueco", "servidor": "agenda", "necesita": ["eventos"], "produce": ["hueco"],
     "descripcion": "Encuentra un hueco libre común entre varias agendas.",
     "criterio": "hueco: encontrar una hora en la que todos estén libres"},
    {"id": "crear_evento", "servidor": "agenda", "necesita": ["hueco", "contacto"], "produce": [],
     "descripcion": "Crea una reunión con fecha, hora y asistentes.",
     "criterio": "agendar: crear una reunión o cita con asistentes"},
    {"id": "listar_correos", "servidor": "correo", "necesita": [], "produce": ["correos"],
     "descripcion": "Lista los correos recientes con remitente, asunto y fecha.",
     "criterio": "bandeja: correos recientes, quién escribió, últimos mensajes"},
    {"id": "leer_correo", "servidor": "correo", "necesita": ["correos"], "produce": ["texto_correo"],
     "descripcion": "Abre un correo de la lista y devuelve su texto completo.",
     "criterio": "leer correo: el contenido de un mensaje, qué dice"},
    {"id": "enviar_correo", "servidor": "correo", "necesita": ["contacto"], "produce": [],
     "descripcion": "Envía un correo a un contacto.",
     "criterio": "enviar correo: escribir y mandar un mensaje a alguien"},
    {"id": "buscar_cliente", "servidor": "crm", "necesita": [], "produce": ["contacto"],
     "descripcion": "Busca un cliente o una persona en el CRM por su nombre.",
     "criterio": "ficha de cliente: encontrar una persona o empresa en el CRM por su nombre"},
    {"id": "ver_oportunidades", "servidor": "crm", "necesita": ["contacto"], "produce": ["oportunidades"],
     "descripcion": "Lista las oportunidades abiertas de un cliente y su importe.",
     "criterio": "oportunidades: negocios abiertos de un cliente, importe del embudo"},
    {"id": "registrar_nota", "servidor": "crm", "necesita": ["contacto"], "produce": [],
     "descripcion": "Deja una nota escrita en la ficha de un cliente.",
     "criterio": "nota: dejar información escrita en la ficha del cliente"},
    {"id": "mover_oportunidad", "servidor": "crm", "necesita": ["oportunidades"], "produce": [],
     "descripcion": "Cambia de etapa una oportunidad del embudo de ventas.",
     "criterio": "etapa: mover una oportunidad a otra fase del embudo"},
    {"id": "buscar_archivo", "servidor": "archivos", "necesita": [], "produce": ["documento"],
     "descripcion": "Busca documentos por nombre o contenido en la unidad compartida.",
     "criterio": "buscar archivo: documentos, contratos, informes de la unidad compartida"},
    {"id": "leer_documento", "servidor": "archivos", "necesita": ["documento"], "produce": ["texto_documento"],
     "descripcion": "Extrae el texto de un documento encontrado.",
     "criterio": "leer archivo: el texto dentro de un documento"},
    {"id": "crear_documento", "servidor": "archivos", "necesita": [], "produce": ["documento"],
     "descripcion": "Guarda un documento nuevo con lo reunido en los pasos anteriores.",
     "criterio": "archivo nuevo: guardar un informe o documento"},
    {"id": "consultar_sql", "servidor": "datos", "necesita": [], "produce": ["tabla"],
     "descripcion": "Ejecuta una consulta SQL sobre el almacén de datos de la empresa.",
     "criterio": "base de datos: ventas, ingresos, cifras del almacén de datos"},
    {"id": "resumir_metricas", "servidor": "datos", "necesita": ["tabla"], "produce": ["metricas"],
     "descripcion": "Calcula totales, medias y variación de una tabla.",
     "criterio": "totales: suma, media y variación de una tabla"},
    {"id": "graficar", "servidor": "datos", "necesita": ["tabla"], "produce": ["grafica"],
     "descripcion": "Dibuja una gráfica a partir de una tabla.",
     "criterio": "gráfica: dibujar una tabla"},
    {"id": "buscar_ticket", "servidor": "soporte", "necesita": [], "produce": ["tickets"],
     "descripcion": "Busca incidencias de soporte por cliente, estado o fecha.",
     "criterio": "incidencias: tickets de soporte existentes de un cliente"},
    {"id": "crear_ticket", "servidor": "soporte", "necesita": ["contacto"], "produce": [],
     "descripcion": "Abre una incidencia de soporte para un cliente.",
     "criterio": "ticket nuevo: abrir una incidencia de soporte"},
    {"id": "buscar_web", "servidor": "web", "necesita": [], "produce": ["enlaces"],
     "descripcion": "Busca en internet y devuelve enlaces con un resumen de cada uno.",
     "criterio": "buscar en internet: qué se dice en la red, competencia, información pública"},
    {"id": "abrir_pagina", "servidor": "web", "necesita": ["enlaces"], "produce": ["pagina"],
     "descripcion": "Abre uno de los enlaces encontrados y devuelve su contenido.",
     "criterio": "abrir enlace: el contenido de una página encontrada"},
]
CATALOG = {t["id"]: t for t in TOOLS}

QUESTIONS = {
    "cubierta": "Do the tools already called fully cover the `peticion`?",
    "servidor": "Which tool server must serve the first thing the `peticion` needs?",
    "herramienta": "Which of these tools does the `peticion` need?",
}

# Peticiones de ejemplo con la ruta que daría una persona. La referencia solo sirve para medir a
# Laya: no se envía a la página, igual que en la Mesa de ayuda.
EXAMPLES = [
    {"texto": "Agenda una reunión la semana que viene con el cliente Nordia",
     "referencia": ["buscar_cliente", "ver_agenda", "buscar_hueco", "crear_evento"]},
    {"texto": "Enséñame las ventas del último trimestre en una gráfica",
     "referencia": ["consultar_sql", "graficar"]},
    {"texto": "¿Qué pide el último correo de soporte? Ábreme una incidencia con eso",
     "referencia": ["listar_correos", "leer_correo", "buscar_cliente", "crear_ticket"]},
    {"texto": "Busca el contrato de Nordia y dime qué dice sobre la renovación",
     "referencia": ["buscar_archivo", "leer_documento"]},
    {"texto": "Mira qué se dice en internet de nuestro competidor y déjalo en una nota del CRM",
     "referencia": ["buscar_web", "abrir_pagina", "buscar_cliente", "registrar_nota"]},
    {"texto": "¿Cuánto tenemos abierto con Nordia en el embudo?",
     "referencia": ["buscar_cliente", "ver_oportunidades"]},
    {"texto": "Calcula el total de ingresos de este mes y mándaselo por correo a Nordia",
     "referencia": ["consultar_sql", "resumir_metricas", "buscar_cliente", "enviar_correo"]},
    {"texto": "¿Tengo algo en la agenda para mañana?",
     "referencia": ["ver_agenda"]},
]


def public(example):
    return {k: v for k, v in example.items() if k != "referencia"}


def catalog():
    """El catálogo como lo ve la página: en español y con sus dependencias en texto."""
    return [{"id": t["id"], "servidor": t["servidor"], "servidor_nombre": SERVERS[t["servidor"]][0],
             "descripcion": t["descripcion"],
             "necesita": [DATA[d] for d in t["necesita"]], "produce": [DATA[d] for d in t["produce"]]}
            for t in TOOLS]


def servers():
    return {k: name for k, (name, _) in SERVERS.items()}


def distribution(answer, keys):
    """Laya devuelve la distribución en el orden de los criterios; se empareja por posición."""
    values = list(answer["probabilities"].values())
    if len(values) != len(keys) or any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1
                                       for p in values):
        raise ValueError("Distribución inválida")
    if abs(sum(values) - 1) > .02:
        raise ValueError("La distribución no suma 1")
    if answer["choice"] not in keys:
        raise ValueError(f"Respuesta fuera de las opciones: {answer['choice']}")
    confidence = answer["confidence"]
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confianza inválida")
    return {k: round(v, 4) for k, v in sorted(zip(keys, values), key=lambda kv: -kv[1])}


def probability(answer):
    value = answer["noul"]
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Probabilidad fuera de 0–1")
    return value


class Route:
    """La petición, lo que ya se llamó y la ruta de llamadas construida hasta ahora."""

    def __init__(self, prompt=""):
        prompt = " ".join((prompt or "").split())
        if len(prompt) > MAX_PROMPT:
            raise ValueError(f"La petición no puede pasar de {MAX_PROMPT} caracteres.")
        self.prompt = prompt
        self.called, self.data, self.history = [], [], []
        self.done = not prompt
        self.reason = "Escribe una petición" if not prompt else ""

    def state(self):
        """Exactamente lo que lee Laya antes de decidir."""
        return {"peticion": self.prompt,
                "ya_hecho": [t for t in self.called] or ["nada todavía"],
                "ya_tienes": [DATA[d] for d in self.data] or ["nada todavía"]}

    def chain(self, tool, extra=None, depth=0):
        """Regla: delante de una herramienta van las que producen lo que le falta.

        Laya elige qué hacer; encadenar los argumentos no se le pregunta, porque no planifica
        dos pasos (la misma lección que la Ruta de aprendizaje).
        """
        added, data = [], list(self.data) + list(extra or [])
        if depth > 3:
            return added
        for need in tool["necesita"]:
            if need in data:
                continue
            options = [t for t in TOOLS if need in t["produce"]
                       and t["id"] not in self.called and t["id"] not in [a["id"] for a in added]]
            if not options:
                continue
            cheapest = min(options, key=lambda t: sum(n not in data for n in t["necesita"]))
            for step in self.chain(cheapest, [d for a in added for d in CATALOG[a["id"]]["produce"]], depth + 1):
                added.append(step)
                data += CATALOG[step["id"]]["produce"]
            added.append({"id": cheapest["id"], "porque": DATA[need]})
            data += cheapest["produce"]
        return added

    def turn(self, predict):
        """Una vuelta: ¿ya basta? → servidor → herramienta → prerrequisitos."""
        if self.done:
            raise LookupError("La ruta ya está trazada; escribe otra petición para empezar.")
        state = self.state()
        started = time.perf_counter()
        stop = None
        if self.called:
            covered = probability(predict(state, {"cubierta": {"type": "noul", "instructions": QUESTIONS["cubierta"]}})
                                  ["answers"]["cubierta"])
            stop = {"probabilidad": round(100 * covered, 1), "umbral": round(100 * STOP_THRESHOLD),
                    "para": covered > STOP_THRESHOLD}
            if stop["para"]:
                return self.finish("Laya da la petición por cubierta", state, stop, started)
        keys = list(SERVERS)
        answer = predict(state, {"servidor": {"type": "choice", "instructions": QUESTIONS["servidor"],
                                              "criteria": {k: crit for k, (_, crit) in SERVERS.items()}}})["answers"]["servidor"]
        probabilities = distribution(answer, keys)  # Valida antes de usar la respuesta.
        server = {"elegido": answer["choice"], "nombre": SERVERS[answer["choice"]][0],
                  "confianza": round(100 * answer["confidence"], 1), "probabilidades": probabilities}
        inside = [t for t in TOOLS if t["servidor"] == server["elegido"] and t["id"] not in self.called]
        if not inside:
            return self.finish(f"Ya se llamó a todo lo de {server['nombre']}", state, stop, started, server)
        answer = predict(state, {"herramienta": {"type": "choice", "instructions": QUESTIONS["herramienta"],
                                                 "criteria": {t["id"]: t["criterio"] for t in inside}}})["answers"]["herramienta"]
        ids = [t["id"] for t in inside]
        probabilities = distribution(answer, ids)
        tool = CATALOG[answer["choice"]]
        chosen = {"id": tool["id"], "confianza": round(100 * answer["confidence"], 1),
                  "probabilidades": probabilities}
        added = self.chain(tool)
        calls = [{**step, "regla": True} for step in added] + [{"id": tool["id"], "regla": False}]
        for call in calls:
            self.called.append(call["id"])
            self.data += [d for d in CATALOG[call["id"]]["produce"] if d not in self.data]
        record = self.record(state, stop, started, server, chosen, calls)
        if len(self.history) >= MAX_TURNS:
            self.done, self.reason = True, "Demasiadas vueltas"
        elif not [t for t in TOOLS if t["id"] not in self.called]:
            self.done, self.reason = True, "No quedan herramientas"
        return record

    def finish(self, reason, state, stop, started, server=None):
        self.done, self.reason = True, reason
        return self.record(state, stop, started, server, None, [])

    def record(self, state, stop, started, server, chosen, calls):
        record = {"vuelta": len(self.history) + 1, "estado": state, "parar": stop, "servidor": server,
                  "herramienta": chosen, "llamadas": calls, "elapsed": time.perf_counter() - started,
                  "fin": chosen is None}
        self.history.append(record)
        return record

    def view(self):
        return {"peticion": self.prompt, "done": self.done, "reason": self.reason,
                "llamadas": [{"id": call["id"], "regla": call["regla"], "porque": call.get("porque"),
                              "vuelta": record["vuelta"]}
                             for record in self.history for call in record["llamadas"]],
                "datos": [{"id": d, "nombre": DATA[d]} for d in self.data],
                "estado": self.state(), "history": self.history}
