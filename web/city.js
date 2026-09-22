import { $, svg, watchModel } from "./common.js";
import { nearestAngle } from "./lib.js";

const X = i => 150 + i * 150, Y = j => 70 + j * 125; // Cruces en unidades del viewBox.
// Árboles en los márgenes: solo decorado, lejos de STOP, marcadores y nombres de calle.
const TREES = [[190, 28, 13], [420, 26, 11], [560, 30, 14], [760, 27, 12], [880, 30, 10],
               [200, 614, 12], [480, 616, 10], [640, 613, 13], [860, 615, 11], [945, 130, 11], [946, 300, 12], [944, 470, 10]];
const ROAD = 34;
const HEADING = { este: 0, sur: 90, oeste: 180, norte: -90 };
const STEP = { norte: [0, -1], sur: [0, 1], oeste: [-1, 0], este: [1, 0] };
const HOUSES = ["#ffc53d", "#4fa8f0", "#3ddba8", "#ff9b8f", "#b8a4f5"];
const PAUSE = matchMedia("(prefers-reduced-motion: reduce)").matches ? 150 : 800; // ms entre turnos.
const percent = new Intl.NumberFormat("es", { style: "percent", maximumFractionDigits: 1 });
const seconds = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const city = $("#city"), statusLine = $("#status");
let map, view, selected = null, running = false, busy = false, angle = 0, lights = {};

watchModel($("#model"));
({ map, view } = await (await fetch("/api/city")).json());
angle = HEADING[view.heading];
const ACTIONS = map.actions;
const layers = drawCity();
instantly(render);

/* Ciudad: el plano se dibuja una vez; ruta, semáforos, marcadores y coche cambian cada turno. */

function drawCity() {
  const ground = svg("g", {}, city);
  for (let i = 0; i < map.cols - 1; i++) for (let j = 0; j < map.rows - 1; j++) drawBlock(ground, i, j);
  const roads = svg("g", { stroke: "#fff", "stroke-width": ROAD, "stroke-linecap": "round" }, city);
  for (let j = 0; j < map.rows; j++) svg("line", { x1: X(0), y1: Y(j), x2: X(map.cols - 1), y2: Y(j) }, roads);
  for (let i = 0; i < map.cols; i++) svg("line", { x1: X(i), y1: Y(0), x2: X(i), y2: Y(map.rows - 1) }, roads);
  for (const [x, y, r] of TREES) {
    svg("circle", { cx: x, cy: y + 3, r, fill: "#6fbf84" }, city);
    svg("circle", { cx: x - 1, cy: y, r, fill: "#8fd6a5" }, city);
  }
  const marks = svg("g", { fill: "none", stroke: "#cfc6b4", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" }, city);
  for (let j = 0; j < map.rows; j++) for (let i = 0; i < map.cols - 1; i++)
    drawLanes(marks, (X(i) + X(i + 1)) / 2, Y(j), map.one_way_rows[j], ["oeste", "este"]);
  for (let i = 0; i < map.cols; i++) for (let j = 0; j < map.rows - 1; j++)
    drawLanes(marks, X(i), (Y(j) + Y(j + 1)) / 2, map.one_way_cols[i], ["sur", "norte"]);
  map.streets.forEach((name, j) => svg("text", { x: X(0) - 40, y: Y(j) + 5, "text-anchor": "end",
    "font-size": 14, "font-weight": 800, fill: "#7a705e" }, city).textContent = name);
  for (const [i, j] of map.stops) drawStop(X(i) - 25, Y(j) - 25);
  for (const [i, j] of map.lights) lights[`${i},${j}`] = drawLight(X(i), Y(j));
  const route = svg("polyline", { fill: "none", stroke: "#6c4ee3", "stroke-width": 6, "stroke-linecap": "round",
                                  "stroke-linejoin": "round", "stroke-dasharray": "1 13", opacity: .9 }, city);
  const passenger = marker("#4fa8f0", "Alex", person, "float");
  const destination = marker("#ffc53d", "Hotel", hotel, "pulse");
  return { route, passenger, destination, car: drawCar() };
}

function drawBlock(parent, i, j) {
  const x = X(i) + 32, y = Y(j) + 30, w = 150 - 64, h = 125 - 60;
  if ((i + 2 * j) % 5 === 0) {
    svg("rect", { x, y, width: w, height: h, rx: 16, fill: "#c9e8cd" }, parent);
    for (const [cx, cy, r] of [[x + 24, y + 24, 14], [x + 56, y + 36, 17], [x + 30, y + h - 14, 9]])
      svg("circle", { cx, cy, r, fill: "#86d198" }, parent);
    return;
  }
  const seed = i * 7 + j * 3;
  [[x + 10, y + 20, 30], [x + 46, y + 12, 36]].forEach(([hx, hy, size], k) => {
    const color = HOUSES[(seed + k) % HOUSES.length];
    svg("rect", { x: hx, y: hy, width: size, height: size, rx: 9, fill: color }, parent);
    svg("rect", { x: hx + size / 2 - 5, y: hy + size / 2 - 5, width: 10, height: 10, rx: 3, fill: "#fff", opacity: .55 }, parent);
  });
}

function drawLanes(parent, x, y, oneWay, [first, second]) {
  const chevron = (cx, cy, direction) => {
    const [dx, dy] = STEP[direction];
    const px = -dy, py = dx; // Perpendicular a la marcha.
    svg("path", { d: `M${cx - 6 * dx + 6 * px},${cy - 6 * dy + 6 * py}L${cx + 2 * dx},${cy + 2 * dy}L${cx - 6 * dx - 6 * px},${cy - 6 * dy - 6 * py}` }, parent);
  };
  if (oneWay) {
    const [dx, dy] = STEP[oneWay];
    chevron(x - 7 * dx, y - 7 * dy, oneWay);
    chevron(x + 7 * dx, y + 7 * dy, oneWay);
    return;
  }
  // Doble sentido: solo la línea central discontinua, sin flechas que compitan con la ruta.
  const half = first === "oeste" ? 150 / 2 - ROAD / 2 - 6 : 125 / 2 - ROAD / 2 - 6;
  svg("line", first === "oeste" ? { x1: x - half, y1: y, x2: x + half, y2: y } : { x1: x, y1: y - half, x2: x, y2: y + half },
      parent).setAttribute("style", "stroke:#e8e2d5;stroke-width:2;stroke-dasharray:7 9");
}

function drawStop(x, y) {
  const g = svg("g", { transform: `translate(${x} ${y})` }, city);
  const points = Array.from({ length: 8 }, (_, k) => {
    const a = Math.PI / 8 + k * Math.PI / 4;
    return `${(14 * Math.cos(a)).toFixed(1)},${(14 * Math.sin(a)).toFixed(1)}`;
  }).join(" ");
  svg("polygon", { points, fill: "#d8344a", stroke: "#fff", "stroke-width": 3 }, g);
  svg("text", { y: 3, "text-anchor": "middle", "font-size": 8, "font-weight": 900, fill: "#fff" }, g).textContent = "STOP";
  svg("title", {}, g).textContent = "STOP: el taxi para un turno antes de seguir";
}

function drawLight(x, y) {
  const g = svg("g", { transform: `translate(${x} ${y})`, "stroke-width": 6, "stroke-linecap": "round" }, city);
  const reach = ROAD / 2 - 4, gap = ROAD / 2 + 6;
  const ew = [-gap, gap].map(dx => svg("line", { x1: dx, y1: -reach, x2: dx, y2: reach }, g));
  const ns = [-gap, gap].map(dy => svg("line", { x1: -reach, y1: dy, x2: reach, y2: dy }, g));
  const title = svg("title", {}, g);
  return { ew, ns, title };
}

// El grupo exterior se coloca por atributo; el interior se anima con CSS sin pisar esa posición.
function marker(color, label, icon, motion) {
  const g = svg("g", {}, city);
  if (motion === "pulse") svg("circle", { r: 18, fill: color, class: "pulse" }, g);
  const body = svg("g", { class: motion === "float" ? "float" : "" }, g);
  svg("circle", { r: 18, fill: color, stroke: "#fff", "stroke-width": 4 }, body);
  icon(body);
  const tag = svg("g", { transform: "translate(0 36)" }, g);
  svg("rect", { x: -30, y: -12, width: 60, height: 24, rx: 12, fill: "#fff" }, tag);
  svg("text", { y: 5, "text-anchor": "middle", "font-size": 13, "font-weight": 900, fill: "#25283d" }, tag).textContent = label;
  return g;
}

function person(g) {
  svg("circle", { cy: -6, r: 5, fill: "#fff" }, g);
  svg("path", { d: "M-9,11 C-9,0 9,0 9,11Z", fill: "#fff" }, g);
}

function hotel(g) {
  svg("text", { y: 6, "text-anchor": "middle", "font-size": 18, "font-weight": 1000, fill: "#25283d" }, g).textContent = "H";
}

function drawCar() {
  const g = svg("g", { id: "car" }, city);
  svg("ellipse", { cx: 3, cy: 5, rx: 25, ry: 15, fill: "#25283d", opacity: .14 }, g);
  for (const [x, y] of [[-17, -17], [9, -17], [-17, 13], [9, 13]])
    svg("rect", { x, y, width: 9, height: 4, rx: 2, fill: "#25283d" }, g); // Ruedas.
  svg("rect", { x: -22, y: -13, width: 44, height: 26, rx: 10, fill: "#ff6b5b" }, g);
  svg("rect", { x: 7, y: -10, width: 8, height: 20, rx: 3, fill: "#fff", opacity: .9 }, g); // Parabrisas.
  svg("rect", { x: -8, y: -6, width: 10, height: 12, rx: 3, fill: "#ffc53d", stroke: "#fff", "stroke-width": 1.5 }, g); // Luz de taxi.
  svg("circle", { cx: 20, cy: -8, r: 2.5, fill: "#fff3c4" }, g);
  svg("circle", { cx: 20, cy: 8, r: 2.5, fill: "#fff3c4" }, g);
  const rider = svg("circle", { cx: -16, cy: 0, r: 5, fill: "#4fa8f0", stroke: "#fff", "stroke-width": 2 }, g);
  return { g, rider };
}

// Coloca el coche sin animarlo (al cargar o reiniciar no debe cruzar la ciudad).
function instantly(draw) {
  layers.car.g.style.transition = "none";
  draw();
  layers.car.g.getBoundingClientRect();
  layers.car.g.style.transition = "";
}

function placeCar() {
  const [i, j] = view.car;
  angle = nearestAngle(angle, HEADING[view.heading]);
  layers.car.g.style.transform = `translate(${X(i)}px, ${Y(j)}px) rotate(${angle}deg)`;
  layers.car.rider.style.display = view.onboard ? "" : "none";
}

/* Panel y estado. */

function render() {
  const record = currentRecord();
  const mission = $("#mission");
  mission.textContent = view.done ? `Alex llegó al Hotel en ${view.tick} turnos` : view.onboard ? "Lleva a Alex al Hotel" : "Recoge a Alex";
  mission.classList.toggle("done", view.done);
  $("#turn").textContent = `Turno ${view.tick}`;
  layers.route.setAttribute("points", view.route.map(([i, j]) => `${X(i)},${Y(j)}`).join(" "));
  layers.passenger.setAttribute("transform", `translate(${X(view.passenger[0])} ${Y(view.passenger[1])})`);
  layers.passenger.style.display = view.onboard ? "none" : "";
  layers.destination.setAttribute("transform", `translate(${X(view.destination[0])} ${Y(view.destination[1])})`);
  for (const { node, ew } of view.lights) {
    const light = lights[node.join(",")];
    // Rojo continuo, verde discontinuo: el estado no depende solo del color.
    const paint = (lines, green) => lines.forEach(line => {
      line.setAttribute("stroke", green ? "#2fbf94" : "#d8344a");
      line.setAttribute("stroke-dasharray", green ? "4 6" : "none");
    });
    paint(light.ew, ew);
    paint(light.ns, !ew);
    light.title.textContent = `Semáforo: verde para ${ew ? "este-oeste" : "norte-sur"}`;
  }
  placeCar();
  renderDecision(record);
  renderHistory();
  $("#drive").dataset.running = running;
  $("#drive span").textContent = running ? "Pausar" : "Conducir";
  $("#drive").disabled = view.done;
  $("#step").disabled = running || busy || view.done;
}

function currentRecord() {
  return view.history.length ? view.history[selected ?? view.history.length - 1] : null;
}

function renderDecision(record) {
  const options = record ? record.options : view.options;
  $("#when").hidden = selected == null;
  if (record) $("#when").textContent = `Turno ${record.step}`;
  $("#actions").replaceChildren(...Object.entries(ACTIONS).map(([action, label]) => {
    const item = document.createElement("li");
    const p = record?.probabilities[action];
    item.classList.toggle("winner", record?.winner === action);
    const top = document.createElement("div");
    top.className = "top";
    const name = document.createElement("span"), value = document.createElement("b");
    name.textContent = label;
    value.textContent = p == null ? "—" : percent.format(p);
    top.append(name, value);
    const bar = document.createElement("div"), fill = document.createElement("i");
    bar.className = "bar";
    fill.style.width = `${(p ?? 0) * 100}%`;
    bar.append(fill);
    const option = options[action];
    item.classList.toggle("blocked", !option.habilitada);
    item.title = option.motivo;
    item.append(top, bar);
    return item;
  }));
  const corrected = record && record.winner !== record.executed;
  const verdict = $("#verdict");
  verdict.hidden = !corrected;
  if (corrected) verdict.textContent = `${ACTIONS[record.winner]} bloqueada (${record.options[record.winner].motivo}): hizo ${ACTIONS[record.executed]}`;
}

function renderHistory() {
  const list = $("#history");
  $("#history-panel").hidden = !view.history.length;
  list.replaceChildren(...view.history.map((record, index) => {
    const item = document.createElement("li"), button = document.createElement("button");
    button.type = "button";
    button.dataset.index = index;
    button.setAttribute("aria-current", String(index === (selected ?? view.history.length - 1)));
    const corrected = record.winner !== record.executed;
    button.classList.toggle("corrected", corrected);
    const step = document.createElement("span"), text = document.createElement("b");
    step.textContent = record.step;
    text.textContent = corrected ? `${ACTIONS[record.winner]} → ${ACTIONS[record.executed]}` : ACTIONS[record.winner];
    button.append(step, text);
    item.append(button);
    return item;
  }));
  if (selected == null) list.scrollTop = list.scrollHeight; // Solo la lista, nunca la página.
  $("#latest").hidden = selected == null;
}

$("#history").addEventListener("click", event => {
  const button = event.target.closest("button[data-index]");
  if (!button) return;
  const index = Number(button.dataset.index);
  selected = index === view.history.length - 1 ? null : index;
  renderDecision(currentRecord());
  renderHistory();
});
$("#latest").addEventListener("click", () => { selected = null; renderDecision(currentRecord()); renderHistory(); });

/* Conducción: cada turno es una petición; el piloto automático encadena turnos tras la animación. */

async function step() {
  if (busy || view.done) return;
  busy = true;
  render();
  setStatus("");
  try {
    const response = await fetch("/api/city/step", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    view = data.view;
    selected = null;
    if (view.done) running = false;
  } catch (error) {
    running = false;
    setStatus(`El taxi no se movió: ${error.message}`);
  } finally {
    busy = false;
    render();
    if (running) setTimeout(step, PAUSE);
  }
}

function toggle() {
  if (view.done) return;
  running = !running;
  render();
  if (running) step();
}

// Reiniciar repite el escenario; sortear coloca taxi, Alex y hotel en cruces nuevos.
async function restart(shuffle) {
  running = false;
  const response = await fetch(shuffle ? "/api/city/shuffle" : "/api/city/reset", { method: "POST" });
  ({ view } = await response.json());
  selected = null;
  angle = HEADING[view.heading];
  instantly(render);
  setStatus("");
}

function inspect() {
  const record = currentRecord();
  const state = selected == null ? view.next_state : record.state;
  $("#state-title").textContent = selected == null ? "Próximo turno" : `Turno ${record.step}`;
  $("#state-json").textContent = JSON.stringify(state, null, 2);
  $("#state-dialog").showModal();
}

$("#drive").addEventListener("click", toggle);
$("#step").addEventListener("click", step);
$("#reset").addEventListener("click", () => restart(false));
$("#shuffle").addEventListener("click", () => restart(true));
$("#inspect").addEventListener("click", inspect);
$("#close-dialog").addEventListener("click", () => $("#state-dialog").close());
document.addEventListener("keydown", event => {
  if (event.code === "Space" && !event.target.closest("button, input, dialog")) { event.preventDefault(); toggle(); }
});

function setStatus(text) {
  statusLine.textContent = text;
}
