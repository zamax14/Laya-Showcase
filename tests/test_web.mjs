// node --test tests/test_web.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { RAMP, colorFor, equalEarth, nearestAngle, pathFor } from "../web/lib.js";

test("la proyección conserva orientación y límites", () => {
  assert.deepEqual(equalEarth(0, 0), [0, -0]);
  const [east] = equalEarth(180, 0);
  assert.ok(east > 2.7 && east < 2.71);
  assert.ok(equalEarth(0, 80)[1] < 0, "el norte queda arriba");
  assert.ok(Math.abs(equalEarth(-180, 0)[0] + east) < 1e-12, "simétrica");
});

test("la escala va de la rampa clara a la oscura y rechaza basura", () => {
  assert.equal(colorFor(0).toUpperCase(), RAMP[0]);
  assert.equal(colorFor(1).toUpperCase(), RAMP.at(-1));
  assert.equal(colorFor(null), null);
  assert.equal(colorFor(undefined), null);
  for (const bad of [NaN, Infinity, -0.1, 1.1]) assert.throws(() => colorFor(bad), RangeError);
  const dark = hex => parseInt(hex.slice(1, 3), 16);
  assert.ok(dark(colorFor(.2)) > dark(colorFor(.8)), "más afinidad, más oscuro");
});

test("trazados con agujeros y giros por el camino corto", () => {
  const square = [[[0, 0], [1, 0], [1, 1], [0, 0]], [[.2, .2], [.4, .2], [.2, .4], [.2, .2]]];
  const d = pathFor([square], (x, y) => [x, y]);
  assert.equal((d.match(/M/g) || []).length, 2);
  assert.equal(nearestAngle(90, -90), -90);
  assert.equal(nearestAngle(180, -90), 270);
  assert.equal(nearestAngle(0, 270), -90);
});
