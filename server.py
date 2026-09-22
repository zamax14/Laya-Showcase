"""Servidor local de Laya Showcase: sirve web/ y pone a Laya detrás de una API pequeña.

    python server.py            # abre http://127.0.0.1:8000
    python server.py --port 9000 --no-browser
"""
import argparse
import json
import mimetypes
import queue
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from atlas import MAX_QUERY, Evaluator, country_state, load_countries
from city import MAP, Trip, drive, random_scenario
import courses
import tickets

WEB = Path(__file__).resolve().parent / "web"
PAGES = {"/": "index.html", "/atlas": "atlas.html", "/city": "city.html", "/tickets": "tickets.html",
         "/courses": "courses.html"}
KEEPALIVE = 15  # s sin eventos antes de un ping; así se detecta una pestaña cerrada.


class App:
    """Estado compartido por todas las peticiones: un modelo, un barrido y un viaje."""

    def __init__(self, model, prior=None):
        self.model = model
        countries = load_countries()
        self.atlas = Evaluator(countries, model, prior)
        # Se serializa una vez: la geometría pesa ~1 MB y no cambia. «texto» es exactamente lo que lee Laya.
        self.countries = json.dumps(
            [{"id": c["id"], "name": c["name"], "texto": country_state(c), "polygons": c["polygons"]} for c in countries],
            ensure_ascii=False, separators=(",", ":")).encode()
        self.assigned, self.assigning = {}, threading.Lock()  # Mesa de ayuda: resultados por ticket.
        self.scenario = {}  # Vacío: el viaje por defecto de Trip.
        self.trip, self.trip_lock = Trip(), threading.Lock()
        self.roadmap, self.roadmap_lock = courses.Roadmap(), threading.Lock()

    def status(self):
        return {"model": getattr(self.model, "status", "ready"), "error": getattr(self.model, "error", None),
                "device": getattr(self.model, "device", None)}

    def step(self):
        with self.trip_lock:
            if self.trip.done:
                raise LookupError("El viaje terminó; reinícialo para empezar otro.")
            return {"record": drive(self.trip, self.model.predict), "view": self.trip.view()}

    def reset(self):
        """Repite el escenario actual desde el principio."""
        with self.trip_lock:
            self.trip = Trip(**self.scenario)
            return self.city()

    def shuffle(self):
        with self.trip_lock:
            self.scenario = random_scenario()
            self.trip = Trip(**self.scenario)
            return self.city()

    def city(self):
        return {"map": MAP, "view": self.trip.view()}

    def courses(self):
        return {"cursos": [courses.public(c) for c in courses.COURSES], "objetivos": courses.GOALS,
                "perfiles": courses.PROFILES, "habilidades": courses.SKILLS, "view": self.roadmap.view()}

    def course_step(self):
        with self.roadmap_lock:
            return {"record": self.roadmap.step(self.model.predict), "view": self.roadmap.view()}

    def course_reset(self, query):
        """Empieza otra ruta; sin parámetros repite el objetivo y el perfil actuales."""
        with self.roadmap_lock:
            goal = query.get("objetivo", [self.roadmap.goal])[0]
            profile = query.get("perfil", [self.roadmap.profile])[0]
            try:
                self.roadmap = courses.Roadmap(goal, profile)
            except ValueError as exc:
                raise LookupError(str(exc))
            return {"view": self.roadmap.view()}

    def desk(self):
        return {"tickets": [tickets.public(t) for t in tickets.TICKETS],
                "categorias": {k: {"nombre": name, "experto": owner} for k, (name, owner, _) in tickets.CATEGORIES.items()},
                "prioridades": {k: name for k, (name, _) in tickets.PRIORITIES.items()},
                "expertos": {k: {"nombre": name, "rol": role} for k, (name, role) in tickets.EXPERTS.items()},
                "semaforos": tickets.LIGHTS, "asignados": self.assigned}

    def reset_desk(self):
        if not self.assigning.acquire(blocking=False):
            raise LookupError("Laya está asignando tickets; espera a que termine.")
        try:
            self.assigned.clear()
            return self.desk()
        finally:
            self.assigning.release()


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # La consola queda para errores reales.
            pass

        def send_bytes(self, body, content_type, status=HTTPStatus.OK):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, payload, status=HTTPStatus.OK):
            self.send_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

        def do_GET(self):
            url = urlparse(self.path)
            routes = {"/api/status": lambda: self.send_json(app.status()),
                      "/api/atlas/countries": lambda: self.send_bytes(app.countries, "application/json; charset=utf-8"),
                      "/api/atlas/query": lambda: self.stream_query(parse_qs(url.query).get("q", [""])[0]),
                      "/api/city": lambda: self.send_json(app.city()),
                      "/api/courses": lambda: self.send_json(app.courses()),
                      "/api/tickets": lambda: self.send_json(app.desk()),
                      "/api/tickets/assign": self.stream_assign}
            if url.path in routes:
                return routes[url.path]()
            self.send_static(PAGES.get(url.path, url.path.lstrip("/")))

        def do_POST(self):
            url = urlparse(self.path)
            actions = {"/api/city/step": app.step, "/api/city/reset": app.reset, "/api/city/shuffle": app.shuffle,
                       "/api/tickets/reset": app.reset_desk, "/api/courses/step": app.course_step,
                       "/api/courses/reset": lambda: app.course_reset(parse_qs(url.query))}
            action = actions.get(url.path)
            if action is None:
                return self.send_json({"error": "Ruta desconocida"}, HTTPStatus.NOT_FOUND)
            try:
                self.send_json(action())
            except LookupError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except Exception as exc:  # Laya falló: el viaje no se movió y la interfaz lo dice.
                self.send_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def send_static(self, relative):
            path = (WEB / relative).resolve()
            if not path.is_relative_to(WEB) or not path.is_file():
                return self.send_json({"error": "No encontrado"}, HTTPStatus.NOT_FOUND)
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if kind.startswith("text/") or kind.endswith("javascript"):
                kind += "; charset=utf-8"
            self.send_bytes(path.read_bytes(), kind)

        def stream_query(self, query):
            query = query.strip()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not query or len(query) > MAX_QUERY:
                # Se responde como evento para que la página muestre el motivo.
                return self.write_event("failed", f"Escribe una idea de 1 a {MAX_QUERY} caracteres.")
            events, cancelled = app.atlas.submit(query)
            try:
                while True:
                    try:
                        kind, data = events.get(timeout=KEEPALIVE)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    self.write_event(kind, data)
                    if kind in ("done", "failed"):
                        return
            except (BrokenPipeError, ConnectionResetError):
                pass  # La pestaña cerró o lanzó otra consulta.
            finally:
                cancelled.set()

        def stream_assign(self):
            """Asigna los tickets pendientes uno a uno y emite cada resultado en cuanto sale."""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not app.assigning.acquire(blocking=False):
                return self.write_event("failed", "Ya hay una asignación en curso en otra pestaña.")
            try:
                for ticket in tickets.TICKETS:
                    if ticket["id"] in app.assigned:
                        continue
                    started = time.perf_counter()
                    result = tickets.assign(ticket, app.model.predict)
                    result["segundos"] = round(time.perf_counter() - started, 2)
                    app.assigned[ticket["id"]] = result
                    self.write_event("ticket", result)
                self.write_event("done", len(app.assigned))
            except (BrokenPipeError, ConnectionResetError):
                pass  # La pestaña se cerró: lo asignado hasta aquí se conserva.
            except Exception as exc:
                self.write_event("failed", f"{type(exc).__name__}: {exc}")
            finally:
                app.assigning.release()

        def write_event(self, kind, data):
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode())
            self.wfile.flush()

    return Handler


def serve(app, port=8000, host="127.0.0.1"):
    server = ThreadingHTTPServer((host, port), handler_for(app))
    server.daemon_threads = True
    return server


def warm(app):
    started = time.monotonic()
    try:
        app.atlas.warm()
    except Exception as exc:  # La página también lo muestra en el indicador del modelo.
        print(f"Laya no cargó: {type(exc).__name__}: {exc}", flush=True)
        return
    print(f"Laya lista en {app.model.device.upper()} en {time.monotonic() - started:.1f} s", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Demos de Laya Showcase con el modelo en local")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="dónde corre Laya; auto usa la GPU si torch la ve")
    args = parser.parse_args()
    from fastload import SharedModel
    app = App(SharedModel(device=args.device))
    try:
        server = serve(app, args.port)
    except OSError as exc:
        raise SystemExit(f"No se pudo abrir el puerto {args.port} ({exc.strerror}); prueba con --port 8001")
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Laya Showcase en {url} (Ctrl+C para salir)", flush=True)
    # El modelo se carga mientras se abre la página.
    threading.Thread(target=warm, args=(app,), daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
