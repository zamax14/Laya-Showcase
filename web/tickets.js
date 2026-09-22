import { $, modeToggle, showSpeed, watchModel } from "./common.js";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const STEP = REDUCED ? 40 : 330;  // ms por paso: el servidor decide en ~0,35 s, la página lo cuenta despacio.
const HOLD = REDUCED ? 80 : 520;
const CAT_COLORS = { hardware: "#7c8aa5", software: "#9b87f0", redes: "#4fa8f0", accesos: "#2bb3bd", correo: "#e88bb3", seguridad: "#25283d" };
const PRIO_COLORS = { baja: "#cfc1f9", media: "#a48cf1", alta: "#7757e4", critica: "#4428ae" };
const RANGES = { verde: "Más de 80 %", amarillo: "Entre 60 y 80 %", rojo: "Menos de 60 %" };
const pct = n => `${Math.round(n)} %`;
const ms = s => `${Math.round(s * 1000)} ms`;
const frame = () => new Promise(requestAnimationFrame);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

watchModel($("#model"));
const desk = await (await fetch("/api/tickets")).json();
const byId = Object.fromEntries(desk.tickets.map(t => [t.id, t]));
let assigned = { ...desk.asignados };
let group = "categoria", source = null, queue = [], playing = false, current = null, selected = null;
let run = null;  // Tanda en curso: suma de inferencia y tickets, para el indicador de velocidad.
const mode = modeToggle($("#mode"));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "style") node.style.cssText = value;
    else node.setAttribute(key, value);
  }
  node.append(...children.filter(child => child != null));
  return node;
}

const expertColor = key => CAT_COLORS[Object.keys(desk.categorias).find(c => desk.categorias[c].experto === key)];
const initials = name => name.split(" ").map(word => word[0]).join("").slice(0, 2);
const avatar = (key, small) => el("span", { class: small ? "avatar small" : "avatar", style: `background:${expertColor(key)}` },
                                  initials(desk.expertos[key].nombre));
const pending = () => desk.tickets.filter(t => !assigned[t.id] && t.id !== current);

// Arranca aquí, después de definir los ayudantes «const» que usan los renders.
renderAll();
showIdle();

function renderAll() {
  renderQueue();
  renderBoard();
  renderCounters();
  updateButtons();
}

function renderQueue() {
  const items = pending();
  $("#queue-count").textContent = items.length;
  $("#queue").replaceChildren(...(items.length
    ? items.map(t => el("li", { "data-id": t.id }, el("span", { class: "tid" }, t.id), el("p", {}, t.titulo),
                        el("small", {}, `${t.solicitante}, ${t.area}`)))
    : [el("li", { class: "empty" }, "Todo asignado")]));
}

function renderCounters() {
  $("#pending-count").textContent = pending().length + (current ? 1 : 0);
  for (const color of ["verde", "amarillo", "rojo"])
    $(`#count-${color}`).textContent = Object.values(assigned).filter(r => r.semaforo === color).length;
}

/* Tablero: los mismos tickets asignados, agrupados como elija quien mira. */

function groups() {
  if (group === "categoria")
    return Object.entries(desk.categorias).map(([k, c]) => ({ name: c.nombre, color: CAT_COLORS[k], match: r => r.categoria.choice === k }));
  if (group === "prioridad")
    return Object.entries(desk.prioridades).reverse().map(([k, name]) => ({ name, color: PRIO_COLORS[k], match: r => r.prioridad.choice === k }));
  return Object.entries(desk.expertos).map(([k, e]) => ({ name: e.nombre, color: expertColor(k), match: r => r.experto === k }));
}

function renderBoard(newId) {
  const results = desk.tickets.map(t => assigned[t.id]).filter(Boolean);
  const columns = groups();
  $("#columns").style.setProperty("--cols", columns.length);
  $("#columns").replaceChildren(...columns.map(g => {
    const inside = results.filter(g.match);
    return el("div", { class: "column" },
      el("header", {}, el("span", { class: "swatch", style: `background:${g.color}` }), g.name, el("small", {}, inside.length)),
      ...inside.map(r => card(r, r.id === newId)));
  }));
}

function card(r, isNew) {
  const t = byId[r.id];
  return el("button", { type: "button", class: isNew ? "card new" : "card", "data-id": r.id, "aria-current": String(r.id === selected) },
    el("div", { class: "row" }, el("span", {}, r.id), el("span", { class: "dot", "data-color": r.semaforo }), el("b", {}, pct(r.confianza))),
    el("p", {}, t.titulo),
    el("div", { class: "mini" }, avatar(r.experto, true), desk.expertos[r.experto].nombre));
}

document.querySelector(".board .tabs").addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  group = button.dataset.group;
  for (const tab of document.querySelectorAll(".board .tabs button")) tab.setAttribute("aria-pressed", String(tab === button));
  renderBoard();
});



$("#columns").addEventListener("click", event => {
  const target = event.target.closest(".card");
  if (!target || playing) return;
  selected = target.dataset.id;
  showResult(byId[selected], assigned[selected], { label: "Revisión" });
  renderBoard();
});

/* Escenario. */

function showIdle(title) {
  const waiting = pending().length;
  $("#stage").replaceChildren(el("div", { class: "idle" }, el("div", {},
    el("h3", {}, title ?? (waiting ? `${waiting} tickets esperando` : "Todo asignado")),
    el("p", {}, waiting ? "Laya lee cada ticket, decide categoría y prioridad, y lo pasa al experto responsable." : "Toca una tarjeta para revisar su análisis."),
    legend())));
}

function legend() {
  return el("div", { class: "legend" }, ...Object.entries(desk.semaforos).map(([color, attention]) =>
    el("div", {}, trafficLight(color), el("span", {}, el("b", {}, attention), el("small", {}, `Confianza ${RANGES[color].toLowerCase()}`)))));
}

function trafficLight(color) {
  const light = el("div", { class: "light", role: "img", "aria-label": `Semáforo ${color ?? "apagado"}` },
                   el("i", { class: "r" }), el("i", { class: "y" }), el("i", { class: "g" }));
  if (color) light.dataset.color = color;
  return light;
}

// Cada paso se construye apagado; «reveal» enciende barras, escala y semáforo cuando le toca.
function step(n, title, badge, body) {
  return el("li", { class: "step" }, el("span", { class: "num" }, n),
    el("div", {}, el("h4", {}, title, badge ? el("b", {}, badge) : null), body));
}

function reveal(stepNode) {
  for (const bar of stepNode.querySelectorAll("[data-w]")) bar.style.width = bar.dataset.w;
  for (const node of stepNode.querySelectorAll("[data-on]")) node.classList.add(...node.dataset.on.split(" ").filter(Boolean));
  for (const light of stepNode.querySelectorAll("[data-light]")) light.dataset.color = light.dataset.light;
}

function categoryBars(r) {
  const rows = Object.entries(r.categoria.probabilities).sort((a, b) => b[1] - a[1]);
  return el("div", { class: "bars" }, ...rows.map(([key, p]) =>
    el("div", { class: key === r.categoria.choice ? "bar-row win" : "bar-row" },
      el("span", {}, desk.categorias[key].nombre), el("span", {}, pct(100 * p)),
      el("span", { class: "track" }, el("i", { "data-w": `${100 * p}%` })))));
}

function priorityScale(r) {
  const levels = Object.keys(desk.prioridades);
  const chosen = levels.indexOf(r.prioridad.choice);
  return el("div", { class: "scale" }, ...levels.map((key, i) =>
    el("span", { "data-on": i === chosen ? "on win" : i < chosen ? "on" : "" }, desk.prioridades[key])));
}

function expertBlock(r) {
  const expert = desk.expertos[r.experto];
  return el("div", { class: "expert" }, avatar(r.experto),
    el("div", {}, el("b", {}, expert.nombre), el("small", {}, `${expert.rol}. Responsable de ${desk.categorias[r.categoria.choice].nombre}`)));
}

function verdictBlock(r) {
  const light = trafficLight(null);
  light.dataset.light = r.semaforo;
  return el("div", { class: "verdict" }, light, el("div", {}, el("span", { class: "pct" }, pct(r.confianza)), el("p", {}, r.atencion)));
}

async function showResult(t, r, { animate = false, label } = {}) {
  const steps = [
    step(1, "Categoría", `confianza ${pct(r.categoria.confidence)}`, categoryBars(r)),
    step(2, "Prioridad", null, priorityScale(r)),
    step(3, "Experto", null, expertBlock(r)),
    step(4, "Semáforo", null, verdictBlock(r)),
  ];
  $("#stage").replaceChildren(
    el("div", { class: "who-line" }, el("span", { class: "tid" }, t.id),
      el("span", { class: "mode" }, label ?? `Laya decidió en ${ms(r.segundos)}`)),
    el("div", { class: "ticket-card" }, el("h3", {}, t.titulo), el("p", {}, t.descripcion), el("small", {}, `${t.solicitante}, ${t.area}`)),
    el("ol", { class: "steps" }, ...steps));
  if (!animate) return steps.forEach(reveal);
  steps.forEach(s => s.classList.add("pending"));
  for (const s of steps) {
    s.classList.replace("pending", "active");
    await sleep(20);  // Deja pintar el estado apagado para que la transición se vea.
    reveal(s);
    await sleep(STEP);
    s.classList.remove("active");
  }
}

/* Asignación: el servidor emite resultados; la página los reproduce en orden, uno a uno. */

async function play() {
  if (playing) return;
  playing = true;
  updateButtons();
  while (queue.length) {
    const r = queue.shift();
    const slow = mode() === "pasos";
    if (slow) {
      document.querySelector(`#queue li[data-id="${r.id}"]`)?.classList.add("leaving");
      await sleep(REDUCED ? 0 : 260);
    }
    current = r.id;
    renderQueue();
    await showResult(byId[r.id], r, { animate: slow });
    if (slow) await sleep(HOLD);
    else await frame();  // Un fotograma por ticket: se ve pasar cada uno sin frenar a Laya.
    run.inference += r.segundos;
    run.count += 1;
    assigned[r.id] = r;
    current = null;
    selected = null;
    renderBoard(r.id);
    renderQueue();
    renderCounters();
  }
  playing = false;
  updateButtons();
  if (!source) finished();
}

function finished() {
  if (run) showSpeed($("#speed"), run.inference, run.count, "ticket");
}

$("#assign").addEventListener("click", () => {
  if (source || !pending().length) return;
  setStatus("");
  showIdle("Laya empieza a leer…");
  run = { inference: 0, count: 0 };
  $("#speed").hidden = true;
  source = new EventSource("/api/tickets/assign");
  updateButtons();
  source.addEventListener("ticket", event => { queue.push(JSON.parse(event.data)); play(); });
  source.addEventListener("done", closeStream);
  source.addEventListener("failed", event => { setStatus(JSON.parse(event.data)); closeStream(); });
  source.onerror = () => { if (source) { setStatus("Sin conexión con el servidor."); closeStream(); } };
});

$("#reset").addEventListener("click", async () => {
  const response = await fetch("/api/tickets/reset", { method: "POST" });
  const data = await response.json();
  if (!response.ok) return setStatus(data.error);
  assigned = { ...data.asignados };
  selected = null;
  $("#speed").hidden = true;
  setStatus("");
  renderAll();
  showIdle();
});

function closeStream() {
  source?.close();
  source = null;
  updateButtons();
  if (!playing) finished();
}

function updateButtons() {
  const busy = Boolean(source) || playing;
  $("#assign").disabled = busy || !pending().length;
  $("#reset").disabled = busy;
}

function setStatus(text) {
  $("#status").textContent = text;
}
