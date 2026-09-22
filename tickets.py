"""Mesa de ayuda de TI: Laya decide categoría y prioridad; la categoría decide el experto."""
import math

# Criterios en inglés: con los mismos tickets clasificaron mejor que en español (medido: prioridad 11/20
# frente a 7/20, misma precisión en categoría). La página muestra solo los nombres en español.
CATEGORIES = {
    "hardware": ("Hardware", "lucia", "hardware: laptops, screens, printers, peripherals, buying equipment"),
    "software": ("Software", "diego", "software: business apps (ERP, CRM), installing programs, licenses, app errors"),
    "redes": ("Redes", "sofia", "network: wifi, VPN, internet, slow or down network, offices offline"),
    "accesos": ("Accesos", "andres", "access: passwords, locked account, new users, folder permissions"),
    "correo": ("Correo y colaboración", "valeria", "email and collaboration: Outlook, missing emails, calendars, Teams calls"),
    "seguridad": ("Seguridad", "tomas", "security: phishing, viruses, trojans, unauthorized account use, fraud"),
}
# De menor a mayor: es una escala, así que Laya la puntúa como «score» y se redondea al nivel más cercano.
PRIORITIES = {
    "baja": ("Baja", "low: request or improvement with no urgency"),
    "media": ("Media", "medium: annoying or slows down, but work can continue"),
    "alta": ("Alta", "high: one person cannot work or a deadline is imminent"),
    "critica": ("Crítica", "critical: many people or a key business process stopped, or an active security risk"),
}
# Cada categoría tiene un responsable, como en una mesa de ayuda real: así el experto nunca contradice
# a la categoría (preguntarlo aparte daba «Hardware» asignado a ciberseguridad).
EXPERTS = {
    "lucia": ("Lucía Romero", "Puestos de trabajo e impresión"),
    "diego": ("Diego Martín", "Aplicaciones de negocio"),
    "sofia": ("Sofía Herrera", "Redes y conectividad"),
    "andres": ("Andrés Castillo", "Identidad y accesos"),
    "valeria": ("Valeria Núñez", "Correo y colaboración"),
    "tomas": ("Tomás Ibarra", "Ciberseguridad"),
}
QUESTIONS = {
    "categoria": {"type": "choice", "instructions": "Which IT category does the problem in the `ticket` belong to?",
                  "criteria": {k: crit for k, (_, _, crit) in CATEGORIES.items()}},
    "prioridad": {"type": "score", "instructions": "How urgent and impactful is the `ticket`?",
                  "criteria": [crit for _, crit in PRIORITIES.values()]},
}
# Semáforo sobre la confianza de la asignación (categoría → experto).
LIGHTS = {"verde": "Asignado sin revisión", "amarillo": "Un humano confirma", "rojo": "Un humano decide"}

# «referencia» es la respuesta que daría un técnico; solo sirve para medir a Laya, no se envía a la página.
TICKETS = [
    {"id": "T-1001", "titulo": "El portátil no enciende", "solicitante": "Marta Gil", "area": "Finanzas",
     "descripcion": "Desde esta mañana mi portátil no enciende, ni con el cargador puesto. Tengo que entregar un informe hoy.",
     "referencia": ("hardware", "alta", "lucia")},
    {"id": "T-1002", "titulo": "No conecta la VPN desde casa", "solicitante": "Jorge Peña", "area": "Ventas",
     "descripcion": "Trabajo en remoto y la VPN da error de conexión desde ayer. Sin ella no puedo entrar a los sistemas.",
     "referencia": ("redes", "alta", "sofia")},
    {"id": "T-1003", "titulo": "Correo raro pidiendo mi contraseña", "solicitante": "Lorena Vidal", "area": "Recursos Humanos",
     "descripcion": "Me llegó un correo que parece del banco pidiendo que verifique mi usuario y contraseña en un enlace. No lo abrí.",
     "referencia": ("seguridad", "alta", "tomas")},
    {"id": "T-1004", "titulo": "Acceso a la carpeta de Finanzas", "solicitante": "Pablo Ríos", "area": "Dirección",
     "descripcion": "Necesito permisos de lectura en la carpeta compartida de Finanzas para revisar el presupuesto del trimestre.",
     "referencia": ("accesos", "media", "andres")},
    {"id": "T-1005", "titulo": "Outlook no sincroniza el calendario", "solicitante": "Elena Sanz", "area": "Marketing",
     "descripcion": "Las reuniones que creo en Outlook no aparecen en el calendario del móvil desde la semana pasada.",
     "referencia": ("correo", "media", "valeria")},
    {"id": "T-1006", "titulo": "El ERP falla en el cierre contable", "solicitante": "Raúl Ortega", "area": "Finanzas",
     "descripcion": "Al ejecutar el cierre de mes en el ERP aparece un error y se detiene. Todo el equipo contable está parado y el cierre vence mañana.",
     "referencia": ("software", "critica", "diego")},
    {"id": "T-1007", "titulo": "La impresora imprime con rayas", "solicitante": "Nuria Campos", "area": "Operaciones",
     "descripcion": "La impresora de la planta 3 saca las hojas con rayas grises. Se puede leer, pero queda feo.",
     "referencia": ("hardware", "baja", "lucia")},
    {"id": "T-1008", "titulo": "Sin wifi en la oficina de Monterrey", "solicitante": "Iván Soto", "area": "Operaciones",
     "descripcion": "Se cayó el wifi en toda la oficina de Monterrey. Nadie tiene internet y hay 40 personas sin poder trabajar.",
     "referencia": ("redes", "critica", "sofia")},
    {"id": "T-1009", "titulo": "Alta de usuario para nueva empleada", "solicitante": "Carmen León", "area": "Recursos Humanos",
     "descripcion": "El lunes entra una analista nueva en Ventas. Necesita usuario, correo y acceso al CRM.",
     "referencia": ("accesos", "media", "andres")},
    {"id": "T-1010", "titulo": "El antivirus detectó un troyano", "solicitante": "Sergio Molina", "area": "Logística",
     "descripcion": "Me salió un aviso del antivirus diciendo que encontró un troyano en un archivo que descargué de un correo.",
     "referencia": ("seguridad", "critica", "tomas")},
    {"id": "T-1011", "titulo": "Licencia de Adobe Acrobat", "solicitante": "Beatriz Luna", "area": "Marketing",
     "descripcion": "¿Me pueden instalar Adobe Acrobat con licencia? Lo necesito para editar algunos PDF cuando se pueda.",
     "referencia": ("software", "baja", "diego")},
    {"id": "T-1012", "titulo": "No llegan correos de clientes", "solicitante": "Hugo Navarro", "area": "Ventas",
     "descripcion": "Desde ayer no recibo correos de clientes externos; los internos sí llegan. Estoy perdiendo pedidos.",
     "referencia": ("correo", "alta", "valeria")},
    {"id": "T-1013", "titulo": "Cuenta bloqueada", "solicitante": "Alicia Ramos", "area": "Logística",
     "descripcion": "Me equivoqué varias veces con la contraseña y la cuenta quedó bloqueada. No puedo entrar a nada.",
     "referencia": ("accesos", "alta", "andres")},
    {"id": "T-1014", "titulo": "La pantalla externa parpadea", "solicitante": "Óscar Prieto", "area": "Dirección",
     "descripcion": "El monitor externo parpadea de vez en cuando. Puedo trabajar con la pantalla del portátil mientras tanto.",
     "referencia": ("hardware", "baja", "lucia")},
    {"id": "T-1015", "titulo": "Teams se congela en llamadas", "solicitante": "Rosa Delgado", "area": "Ventas",
     "descripcion": "En las videollamadas de Teams con clientes la imagen se congela y se corta el audio. Me pasa en casi todas.",
     "referencia": ("correo", "media", "valeria")},
    {"id": "T-1016", "titulo": "El CRM no carga y la red va lenta", "solicitante": "Manuel Cruz", "area": "Ventas",
     "descripcion": "El CRM tarda minutos en cargar y a veces no abre. También noto que todo lo de internet va lentísimo en la oficina.",
     "referencia": ("redes", "alta", "sofia")},
    {"id": "T-1017", "titulo": "Cambiar el fondo de pantalla", "solicitante": "Laura Fuentes", "area": "Marketing",
     "descripcion": "Me gustaría poner el nuevo fondo de pantalla con el logo de la campaña en los equipos del área.",
     "referencia": ("software", "baja", "diego")},
    {"id": "T-1018", "titulo": "Alguien aprobó un pago con mi usuario", "solicitante": "Andrea Vega", "area": "Finanzas",
     "descripcion": "En el sistema aparece un pago aprobado con mi usuario esta madrugada y yo no fui. Puede ser un fraude.",
     "referencia": ("seguridad", "critica", "tomas")},
    {"id": "T-1019", "titulo": "Portátiles para el equipo de ventas", "solicitante": "Diego Serrano", "area": "Ventas",
     "descripcion": "Necesitamos cinco portátiles nuevos para las incorporaciones del próximo mes.",
     "referencia": ("hardware", "media", "lucia")},
    {"id": "T-1020", "titulo": "Ayuda urgente", "solicitante": "Pedro Vargas", "area": "Operaciones",
     "descripcion": "No me funciona nada, ayuda por favor, es urgente.",
     "referencia": (None, "alta", None)},  # Sin datos para saber categoría ni experto: debería salir en rojo.
]


def ticket_state(ticket):
    return {"ticket": f"{ticket['titulo']}. {ticket['descripcion']} (Solicitante: {ticket['solicitante']}, área de {ticket['area']}.)"}


def public(ticket):
    return {k: v for k, v in ticket.items() if k != "referencia"}


def light(confidence):
    """Verde por encima de 80, amarillo de 60 a 80 (ambos incluidos), rojo por debajo de 60 (en %)."""
    color = "verde" if confidence > 80 else "amarillo" if confidence >= 60 else "rojo"
    return color, LIGHTS[color]


def _probabilities(answer, keys):
    values = list(answer["probabilities"].values())
    if len(values) != len(keys) or not all(isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1 for p in values):
        raise ValueError("Probabilidades inválidas")
    return dict(zip(keys, values))


def assign(ticket, predict):
    """Una inferencia responde categoría y prioridad; el semáforo usa la confianza de la categoría."""
    answers = predict(ticket_state(ticket), QUESTIONS)["answers"]
    category, priority = answers["categoria"], answers["prioridad"]
    if category["choice"] not in CATEGORIES:
        raise ValueError("Categoría desconocida")
    levels = list(PRIORITIES)
    score = priority["score"]
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        raise ValueError("Prioridad inválida")
    confidence = round(100 * category["confidence"], 1)
    color, attention = light(confidence)
    return {"id": ticket["id"],
            "categoria": {"choice": category["choice"], "confidence": confidence,
                          "probabilities": _probabilities(category, list(CATEGORIES))},
            "prioridad": {"choice": levels[min(len(levels) - 1, max(0, round(score)))], "score": round(score, 2),
                          "confidence": round(100 * priority["confidence"], 1),
                          "probabilities": _probabilities(priority, levels)},
            "experto": CATEGORIES[category["choice"]][1],
            "confianza": confidence, "semaforo": color, "atencion": attention}
