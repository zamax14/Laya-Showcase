// Funciones puras compartidas por las páginas; node --test las comprueba.

// Proyección Equal Earth (Šavrič, Patterson y Jenny, 2018): áreas fieles y aspecto amable.
const A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796, M = Math.sqrt(3) / 2;

export function equalEarth(lon, lat) {
  const l = lon * Math.PI / 180;
  const t = Math.asin(M * Math.sin(lat * Math.PI / 180));
  const t2 = t * t, t6 = t2 * t2 * t2;
  const x = l * Math.cos(t) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)));
  const y = t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2));
  return [x, -y]; // En SVG la y crece hacia abajo.
}

// Rampa secuencial de un solo tono, validada contra el océano (#64A8DA).
export const RAMP = ["#F1ECFD", "#CFC1F9", "#A48CF1", "#7757E4", "#4428AE"];

export function colorFor(score) {
  if (score == null) return null; // Sin evaluar: la página usa una trama, no un color de la escala.
  if (!Number.isFinite(score) || score < 0 || score > 1) throw new RangeError("Puntuación fuera de 0–1");
  const position = score * (RAMP.length - 1);
  const index = Math.min(Math.floor(position), RAMP.length - 2);
  const t = position - index;
  const [a, b] = [RAMP[index], RAMP[index + 1]].map(hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)));
  return "#" + a.map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

// Convierte los anillos de un país en un único trazado SVG con agujeros (fill-rule evenodd).
export function pathFor(polygons, project) {
  let d = "";
  for (const polygon of polygons) {
    for (const ring of polygon) {
      d += ring.map(([lon, lat], i) => {
        const [x, y] = project(lon, lat);
        return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      }).join("") + "Z";
    }
  }
  return d;
}

// Rotación sin vueltas largas: de 90° a -90° pasando por el camino corto.
export function nearestAngle(previous, target) {
  const turn = ((target - previous) % 360 + 540) % 360 - 180;
  return previous + turn;
}
