"""Enrutado de herramientas sin modelo: reglas del bucle y encadenado de prerrequisitos."""
import unittest

from tools import CATALOG, DATA, EXAMPLES, MAX_TURNS, Route, SERVERS, TOOLS, public


def fake(server, tool, covered=0.0):
    """Modelo falso: responde el servidor y la herramienta que se le digan."""
    def predict(state, questions):
        answers = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                answers[key] = {"noul": covered}
            else:
                keys = list(q["criteria"])
                choice = server if key == "servidor" else tool
                if choice not in keys:
                    choice = keys[0]
                answers[key] = {"choice": choice, "confidence": .8,
                                "probabilities": {k: 1 / len(keys) for k in keys}}
        return {"answers": answers}
    return predict


class CatalogChecks(unittest.TestCase):
    def test_twenty_tools_with_known_servers_and_data(self):
        self.assertEqual(len(TOOLS), 20)
        self.assertEqual(len(CATALOG), 20)
        for tool in TOOLS:
            self.assertIn(tool["servidor"], SERVERS, tool["id"])
            for datum in tool["necesita"] + tool["produce"]:
                self.assertIn(datum, DATA, tool["id"])
            self.assertTrue(tool["descripcion"] and tool["criterio"], tool["id"])

    def test_every_needed_datum_has_a_producer(self):
        produced = {d for t in TOOLS for d in t["produce"]}
        for tool in TOOLS:
            for datum in tool["necesita"]:
                self.assertIn(datum, produced, tool["id"])

    def test_examples_reference_real_tools_and_hide_it(self):
        for example in EXAMPLES:
            self.assertTrue(example["referencia"])
            for tool in example["referencia"]:
                self.assertIn(tool, CATALOG)
            self.assertNotIn("referencia", public(example))


class LoopChecks(unittest.TestCase):
    def test_rules_put_the_prerequisites_first(self):
        route = Route("Agenda una reunión con Nordia")
        record = route.turn(fake("agenda", "crear_evento"))
        # crear_evento necesita hueco y contacto: las reglas ponen delante quien los produce.
        self.assertEqual(route.called, ["ver_agenda", "buscar_hueco", "buscar_cliente", "crear_evento"])
        self.assertEqual([call["regla"] for call in record["llamadas"]], [True, True, True, False])
        self.assertEqual(record["herramienta"]["id"], "crear_evento")
        self.assertEqual(record["parar"], None)  # No se pregunta en la primera vuelta.
        self.assertEqual(record["llamadas"][1]["porque"], DATA["hueco"])

    def test_a_tool_without_prerequisites_is_called_alone(self):
        route = Route("¿Tengo algo mañana?")
        route.turn(fake("agenda", "ver_agenda"))
        self.assertEqual(route.called, ["ver_agenda"])

    def test_it_stops_when_laya_says_the_request_is_covered(self):
        route = Route("Enséñame las ventas")
        route.turn(fake("datos", "consultar_sql"))
        record = route.turn(fake("datos", "graficar", covered=.9))
        self.assertTrue(route.done)
        self.assertEqual(route.called, ["consultar_sql"])  # La segunda vuelta no llamó a nada.
        self.assertEqual((record["parar"]["para"], record["parar"]["probabilidad"]), (True, 90.0))
        self.assertEqual(record["servidor"], None)
        with self.assertRaises(LookupError):
            route.turn(fake("datos", "graficar"))

    def test_it_keeps_going_when_the_request_is_not_covered(self):
        route = Route("Ventas y una nota")
        route.turn(fake("datos", "consultar_sql"))
        record = route.turn(fake("crm", "registrar_nota", covered=.1))
        self.assertFalse(record["parar"]["para"])
        self.assertEqual(route.called, ["consultar_sql", "buscar_cliente", "registrar_nota"])

    def test_the_loop_always_stops(self):
        route = Route("lo que sea")
        turns = 0
        while not route.done:
            route.turn(fake("crm", "registrar_nota", covered=.0))
            turns += 1
        self.assertLessEqual(turns, MAX_TURNS)
        self.assertIn(route.reason, ("Demasiadas vueltas", "No quedan herramientas",
                                     "Ya se llamó a todo lo de CRM"))

    def test_an_empty_prompt_starts_done_and_a_long_one_is_rejected(self):
        self.assertTrue(Route("   ").done)
        with self.assertRaises(ValueError):
            Route("x" * 301)

    def test_invalid_answers_are_rejected(self):
        def broken(state, questions):
            key = "servidor" if "servidor" in questions else "herramienta"
            return {"answers": {key: {"choice": "nada", "confidence": .5, "probabilities": {"a": 1.0}}}}
        with self.assertRaises(ValueError):
            Route("algo").turn(broken)


if __name__ == "__main__":
    unittest.main()
