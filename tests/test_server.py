"""API del servidor con un modelo falso."""
import json
import threading
from collections import defaultdict
import unittest
import urllib.error
import urllib.parse
import urllib.request

from city import ACTIONS
from server import App, serve


class FakeModel:
    def __init__(self):
        self.fail = False

    def predict(self, state, questions):
        if self.fail:
            raise RuntimeError("modelo caído")
        answers = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                answers[key] = {"noul": .5}
            elif q["type"] == "score":
                answers[key] = {"score": 1.0, "confidence": .5, "probabilities": {str(i): .25 for i in range(len(q["criteria"]))}}
            else:
                keys = list(q["criteria"])
                choice = "este" if "este" in keys else keys[0]
                answers[key] = {"choice": choice, "confidence": .7, "probabilities": {k: 1 / len(keys) for k in keys}}
        return {"answers": answers}


class ServerChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = FakeModel()
        cls.server = serve(App(cls.model, prior=defaultdict(float)), port=0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, method="GET"):
        request = urllib.request.Request(self.base + path, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers["Content-Type"], response.read()

    def events(self, query=None, path=None):
        found = []
        url = self.base + (path or "/api/atlas/query?q=" + urllib.parse.quote(query))
        with urllib.request.urlopen(url, timeout=20) as r:
            kind = None
            for raw in r:
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: "):
                    found.append((kind, json.loads(line[6:])))
                    if kind in ("done", "failed"):
                        return found
        return found

    def test_pages_and_static_files(self):
        status, kind, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", kind)
        for page in ("/atlas", "/city", "/style.css", "/lib.js"):
            self.assertEqual(self.get(page)[0], 200, page)

    def test_files_outside_web_are_not_served(self):
        for path in ("/../server.py", "/%2e%2e/server.py", "//etc/passwd", "/nada.html"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404, path)

    def test_atlas_streams_every_country(self):
        countries = json.loads(self.get("/api/atlas/countries")[2])
        mexico = next(c for c in countries if c["id"] == "MEX")
        self.assertIn("muy picante", mexico["texto"])
        events = self.events("Comida picante")
        kinds = [kind for kind, _ in events]
        self.assertEqual(set(kinds[:-1]), {"batch"})
        self.assertEqual(kinds[-1], "done")
        scored = {code for kind, data in events if kind == "batch" for code in data}
        self.assertEqual(scored, {c["id"] for c in countries})

    def test_atlas_rejects_empty_or_long_queries(self):
        for query in ("   ", "x" * 501):
            self.assertEqual([kind for kind, _ in self.events(query)], ["failed"])

    def test_city_steps_resets_and_survives_model_errors(self):
        self.get("/api/city/reset", "POST")
        city = json.loads(self.get("/api/city")[2])
        self.assertEqual(city["map"]["cols"], 6)
        self.assertEqual(city["view"]["tick"], 0)
        step = json.loads(self.get("/api/city/step", "POST")[2])
        self.assertEqual(step["view"]["tick"], 1)
        self.assertEqual(step["record"]["winner"], "este")
        self.model.fail = True
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get("/api/city/step", "POST")
            self.assertEqual(error.exception.code, 500)
            self.assertIn("modelo caído", json.loads(error.exception.read())["error"])
        finally:
            self.model.fail = False
        self.assertEqual(json.loads(self.get("/api/city")[2])["view"]["tick"], 1)  # No se movió.
        self.assertEqual(json.loads(self.get("/api/city/reset", "POST")[2])["view"]["tick"], 0)

    def test_shuffle_changes_the_trip_and_reset_repeats_it(self):
        shuffled = json.loads(self.get("/api/city/shuffle", "POST")[2])["view"]
        places = (shuffled["car"], shuffled["passenger"], shuffled["destination"])
        self.assertEqual(len({tuple(p) for p in places}), 3)
        self.get("/api/city/step", "POST")
        again = json.loads(self.get("/api/city/reset", "POST")[2])["view"]
        self.assertEqual((again["car"], again["passenger"], again["destination"], again["tick"]), (*places, 0))


    def test_help_desk_assigns_every_ticket_once(self):
        self.get("/api/tickets/reset", "POST")
        desk = json.loads(self.get("/api/tickets")[2])
        self.assertEqual(len(desk["tickets"]), 20)
        self.assertTrue(all("referencia" not in t for t in desk["tickets"]))  # La respuesta esperada no llega a la página.
        self.assertEqual(desk["asignados"], {})
        events = self.events(path="/api/tickets/assign")
        results = [data for kind, data in events if kind == "ticket"]
        self.assertEqual([r["id"] for r in results], [t["id"] for t in desk["tickets"]])
        self.assertEqual(events[-1], ("done", 20))
        first = results[0]
        self.assertEqual(first["experto"], desk["categorias"][first["categoria"]["choice"]]["experto"])
        self.assertEqual((first["confianza"], first["semaforo"]), (70.0, "amarillo"))
        self.assertEqual(self.events(path="/api/tickets/assign"), [("done", 20)])  # Nada pendiente.
        self.assertEqual(json.loads(self.get("/api/tickets/reset", "POST")[2])["asignados"], {})


if __name__ == "__main__":
    unittest.main()
