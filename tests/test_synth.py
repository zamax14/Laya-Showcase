"""Generador de datos sintéticos con un LLM falso: reparto, filtros y CSV."""
import random
import tempfile
import unittest
from pathlib import Path

import synth
from tickets import CATEGORIES, TICKETS


class FakeLLM:
    model, parallel = "falso", 1

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        good = [{"titulo": f"Caso {self.calls}-{i}", "solicitante": "Ana Ruiz", "area": "Ventas",
                 "descripcion": f"Desde ayer falla algo en mi puesto ({self.calls}-{i})."} for i in range(3)]
        bad = [{"titulo": TICKETS[0]["titulo"], "solicitante": "x", "area": "x", "descripcion": "copia del benchmark"},
               {"titulo": "Pista", "solicitante": "x", "area": "x", "descripcion": "Esto no es un fallo de red."}]
        return good + bad, 0.001

    def unload(self):
        pass


class SynthChecks(unittest.TestCase):
    def test_generates_balanced_rows_without_leaks_and_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "casos.csv"
            rows, cost = synth.generate(FakeLLM(), 72, "tickets de un hospital", path, seed=1)
            self.assertEqual(len(rows), 72)
            self.assertEqual({r["categoria"] for r in rows}, set(CATEGORIES))
            self.assertTrue(all(r["titulo"] not in (TICKETS[0]["titulo"], "Pista") for r in rows))
            self.assertGreater(cost, 0)
            cases = synth.read(path)
            self.assertEqual(len(cases), 72)
            first = cases[0]
            self.assertEqual(first["referencia"][2], CATEGORIES[first["referencia"][0]][1])  # El experto de la categoría.
            self.assertIsInstance(first["bloquea"], bool)
            self.assertFalse(any(c["bloquea"] for c in cases if c["referencia"][1] in ("baja", "media")))
            synth.generate(FakeLLM(), 36, "otro contexto", path, seed=2)  # Se añade sin repetir la cabecera.
            self.assertEqual(len(synth.read(path)), 108)

    def test_categories_limit_the_combinations_and_prompt_demands_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, _ = synth.generate(FakeLLM(), 12, "banco", Path(tmp) / "c.csv", seed=3, categories=["seguridad"])
        self.assertEqual({r["categoria"] for r in rows}, {"seguridad"})
        self.assertEqual(len(rows), 12)
        prompt = synth.prompt_for(("seguridad", "alta", False), "banco", [], random.Random(0))
        self.assertIn(synth.SIGNALS["seguridad"], prompt)
        self.assertEqual(set(synth.SIGNALS), set(CATEGORIES))

    def test_parse_rejects_free_text_and_thin_tickets(self):
        words = " ".join(["palabra"] * 30)
        good = '{"tickets": [{"titulo": " VPN caída ", "solicitante": "Ana", "area": "Ventas", "descripcion": "%s"}]}' % words
        self.assertEqual(synth.parse(good)[0]["titulo"], "VPN caída")  # Se recortan los espacios.
        for bad in ("**Ticket 1**\nSujeto: VPN", good.replace(words, "muy corta"), good.replace('"Ana"', '""'),
                    good.replace('"area"', '"extra": 1, "area"')):
            with self.assertRaises(synth.ValidationError):
                synth.parse(bad)

    def test_leaks_detects_hints_and_category_names(self):
        self.assertTrue(synth.leaks("Parece un problema de Seguridad", "seguridad"))
        self.assertTrue(synth.leaks("no hay indicios de ataque", "correo"))
        self.assertFalse(synth.leaks("La VPN se desconecta cada hora", "redes"))


if __name__ == "__main__":
    unittest.main()
