import { $, svg, watchModel } from "./common.js";
import { RAMP, colorFor, equalEarth, pathFor } from "./lib.js";

const SCALE = 180; // Unidades SVG por unidad de la proyección.
const DEBOUNCE = 900;
const number = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const map = $("#map"), tooltip = $("#tooltip"), input = $("#q"), statusLine = $("#status");
const scores = {}, paths = {};
let selected = null, source = null, timer = null, ranked = [], shadow;
const range = (from, to, step) => Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => from + i * step);

watchModel($("#model"));
$("#ramp").style.background = `linear-gradient(90deg, ${RAMP.join(", ")})`;

const countries = await (await fetch("/api/atlas/countries")).json();
const byId = Object.fromEntries(countries.map(c => [c.id, c]));
const project = (lon, lat) => equalEarth(lon, lat).map(v => v * SCALE);
const base = drawMap();
let view = { ...base };
input.focus();

function drawMap() {
  const defs = svg("defs", {}, map);
  const hatch = svg("pattern", { id: "unscored", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  svg("rect", { width: 6, height: 6, fill: "#ede8de" }, hatch);
  svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#d6cfc1", "stroke-width": 2.5 }, hatch);
  // Relieve: una sombra corta bajo la tierra, como una pieza de puzle sobre el agua.
  const relief = svg("filter", { id: "relief", x: "-5%", y: "-5%", width: "110%", height: "115%" }, defs);
  shadow = svg("feDropShadow", { dx: 0, dy: 1.6, stdDeviation: 0, "flood-color": "#3a78a8", "flood-opacity": .9 }, relief);
  const grid = svg("g", { class: "graticule" }, map);
  for (let lon = -180; lon <= 180; lon += 30)
    svg("polyline", { points: range(-60, 85, 5).map(lat => project(lon, lat).join(",")).join(" ") }, grid);
  for (let lat = -60; lat <= 80; lat += 20)
    svg("polyline", { points: range(-180, 180, 10).map(lon => project(lon, lat).join(",")).join(" ") }, grid);
  const land = svg("g", { filter: "url(#relief)" }, map);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const country of countries) for (const polygon of country.polygons) for (const [lon, lat] of polygon[0]) {
    const [x, y] = project(lon, lat);
    minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  // Los países pequeños se dibujan al final para que queden encima de sus vecinos (Lesoto, Gambia…).
  const size = c => c.polygons.reduce((n, p) => n + p[0].length, 0);
  for (const country of [...countries].sort((a, b) => size(b) - size(a))) {
    paths[country.id] = svg("path", { d: pathFor(country.polygons, project), class: "country",
                                      "fill-rule": "evenodd", fill: "url(#unscored)", "data-id": country.id }, land);
  }
  const pad = 12;
  const area = { x: minX - pad, y: minY - pad, w: maxX - minX + 2 * pad, h: maxY - minY + 2 * pad };
  map.setAttribute("viewBox", `${area.x} ${area.y} ${area.w} ${area.h}`);
  return area;
}

/* Consulta: se lanza al dejar de escribir o con Enter; una nueva cancela la anterior. */

input.addEventListener("input", () => {
  clearTimeout(timer);
  stop();
  clearScores();
  setStatus("");
  if (input.value.trim()) timer = setTimeout(run, DEBOUNCE);
});
$("#ask").addEventListener("submit", event => { event.preventDefault(); clearTimeout(timer); run(); });
$("#examples").addEventListener("click", event => {
  if (event.target.matches(".chip")) { input.value = event.target.textContent; clearTimeout(timer); run(); }
});

function run() {
  stop();
  clearScores();
  const query = input.value.trim();
  setStatus("");
  if (!query) return;
  $("#progress").hidden = false;
  const stream = source = new EventSource("/api/atlas/query?q=" + encodeURIComponent(query));
  stream.addEventListener("batch", event => {
    Object.assign(scores, JSON.parse(event.data));
    paint();
  });
  stream.addEventListener("done", stop);
  stream.addEventListener("failed", event => {
    stop();
    setStatus(`Se detuvo: ${JSON.parse(event.data)}`);
  });
  stream.onerror = () => {
    if (source !== stream) return;
    stop();
    setStatus("Sin conexión con el servidor.");
  };
}

function stop() {
  source?.close();
  source = null;
  $("#progress").hidden = true; // Solo se ve mientras Laya evalúa.
}

function clearScores() {
  for (const key of Object.keys(scores)) delete scores[key];
  paint();
}

function paint() {
  for (const [id, path] of Object.entries(paths)) path.setAttribute("fill", colorFor(scores[id]) ?? "url(#unscored)");
  $("#bar").style.width = `${100 * Object.keys(scores).length / countries.length}%`;
  ranked = Object.keys(scores).sort((a, b) => scores[b] - scores[a] || byId[a].name.localeCompare(byId[b].name, "es"));
  $("#ranking").replaceChildren(...ranked.map(rankItem));
  $("#ranking-panel").hidden = !ranked.length;
  refreshDetail();
}

function rankItem(id) {
  const item = document.createElement("li");
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.id = id;
  button.setAttribute("aria-current", String(id === selected));
  const name = document.createElement("span"), value = document.createElement("b");
  name.textContent = byId[id].name;
  value.textContent = number.format(scores[id]);
  const bar = document.createElement("span"), fill = document.createElement("i");
  bar.className = "bar";
  fill.style.width = `${scores[id] * 100}%`;
  fill.style.background = colorFor(Math.max(scores[id], .35));
  bar.append(fill);
  button.append(name, value, bar);
  item.append(button);
  return item;
}

$("#ranking").addEventListener("click", event => {
  const button = event.target.closest("button[data-id]");
  if (button) select(button.dataset.id);
});

/* País seleccionado. */

function select(id) {
  if (selected) paths[selected]?.classList.remove("selected");
  selected = id;
  paths[id].classList.add("selected");
  for (const button of document.querySelectorAll("#ranking button")) button.setAttribute("aria-current", String(button.dataset.id === id));
  refreshDetail();
}

// El panel muestra exactamente el texto que lee Laya: explica la puntuación sin adivinar.
function refreshDetail() {
  if (!selected) return;
  const country = byId[selected], score = scores[selected];
  const panel = $("#detail");
  panel.hidden = false;
  panel.replaceChildren();
  const add = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    panel.append(node);
    return node;
  };
  add("h3", country.name);
  add("p", score == null ? "—" : number.format(score), "score");
  add("p", country.texto, "texto");
}

/* Zoom, arrastre y selección en el mapa. */

function setView(next) {
  const w = Math.min(base.w, Math.max(base.w / 10, next.w));
  const h = w * base.h / base.w;
  const x = Math.min(base.x + base.w - w, Math.max(base.x, next.x));
  const y = Math.min(base.y + base.h - h, Math.max(base.y, next.y));
  view = { x, y, w, h };
  map.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
  shadow.setAttribute("dy", 1.6 * w / base.w); // El relieve mide lo mismo en pantalla con cualquier zoom.
}

function toMap(clientX, clientY) {
  const box = map.getBoundingClientRect();
  // preserveAspectRatio centra el mapa: se corrige el margen que deja.
  const scale = Math.min(box.width / view.w, box.height / view.h);
  const offsetX = (box.width - view.w * scale) / 2, offsetY = (box.height - view.h * scale) / 2;
  return [view.x + (clientX - box.left - offsetX) / scale, view.y + (clientY - box.top - offsetY) / scale, scale];
}

function zoom(factor, clientX, clientY) {
  const box = map.getBoundingClientRect();
  const [px, py] = toMap(clientX ?? box.left + box.width / 2, clientY ?? box.top + box.height / 2);
  const w = Math.min(base.w, Math.max(base.w / 10, view.w * factor));
  const real = w / view.w;
  setView({ x: px - (px - view.x) * real, y: py - (py - view.y) * real, w });
}

map.addEventListener("wheel", event => { event.preventDefault(); zoom(event.deltaY < 0 ? 1 / 1.2 : 1.2, event.clientX, event.clientY); }, { passive: false });
$("#zoom-in").addEventListener("click", () => zoom(1 / 1.4));
$("#zoom-out").addEventListener("click", () => zoom(1.4));
$("#zoom-reset").addEventListener("click", () => setView(base));

let drag = null;
map.addEventListener("pointerdown", event => {
  drag = { x: event.clientX, y: event.clientY, view: { ...view }, id: event.target.dataset?.id, moved: false };
  map.setPointerCapture(event.pointerId);
});
map.addEventListener("pointermove", event => {
  if (drag) {
    const [, , scale] = toMap(event.clientX, event.clientY);
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (Math.hypot(dx, dy) > 4) { drag.moved = true; map.classList.add("dragging"); tooltip.hidden = true; }
    if (drag.moved) setView({ ...drag.view, x: drag.view.x - dx / scale, y: drag.view.y - dy / scale });
    return;
  }
  showTooltip(event);
});
map.addEventListener("pointerup", () => {
  if (drag && !drag.moved && drag.id) select(drag.id);
  drag = null;
  map.classList.remove("dragging");
});
map.addEventListener("pointerleave", () => { if (!drag) tooltip.hidden = true; });

function showTooltip(event) {
  const id = event.target.dataset?.id;
  if (!id) { tooltip.hidden = true; return; }
  const card = map.parentElement.getBoundingClientRect();
  const score = scores[id];
  tooltip.replaceChildren(byId[id].name);
  const value = document.createElement("b");
  value.textContent = score == null ? "sin evaluar" : number.format(score);
  tooltip.append(value);
  tooltip.style.left = `${event.clientX - card.left}px`;
  tooltip.style.top = `${event.clientY - card.top}px`;
  tooltip.hidden = false;
}

function setStatus(text) {
  statusLine.textContent = text;
}
