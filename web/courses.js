import { $, modeToggle, showSpeed, watchModel } from "./common.js";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
// Real-Time: cada curso aparece en cuanto el modelo lo elige. Paso a paso: los cuatro pasos del bucle, a ritmo de lectura.
const pace = () => mode() === "pasos" ? { reveal: REDUCED ? 40 : 330, hold: REDUCED ? 80 : 900 }
                                      : { reveal: 0, hold: REDUCED ? 0 : 60 };
const LEVEL = { "básico": "--basico", "intermedio": "--intermedio", "avanzado": "--avanzado" };
const BARS = 6;  // Candidatos con barra; el resto se resume en una línea.
const pct = n => n > 0 && n < .5 ? "<1 %" : `${Math.round(n)} %`;
const ms = s => `${Math.round(s * 1000)} ms`;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const frame = () => new Promise(requestAnimationFrame);

watchModel($("#model"));
const data = await (await fetch("/api/courses")).json();
const CATALOG = Object.fromEntries(data.cursos.map(c => [c.id, c]));
let view = data.view, running = false, last = null;
let run = { inference: 0, count: 0 };  // Inferencia acumulada de la ruta, para el indicador de velocidad.
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

const chip = (text, kind = "") => el("span", { class: `chip ${kind}`.trim() }, text);

for (const [id, goal] of Object.entries(data.objetivos)) $("#goal").append(new Option(goal.nombre, id));
for (const [id, profile] of Object.entries(data.perfiles)) $("#profile").append(new Option(`${profile.nombre}, ${profile.rol.toLowerCase()}`, id));

renderAll();
showIdle();

function renderAll() {
  $("#goal").value = view.objetivo;
  $("#profile").value = view.perfil;
  renderStudent();
  renderRoute();
  updateButtons();
}

/* Estudiante: lo que sabe, lo que le falta y lo que lleva invertido. */

function renderStudent() {
  const profile = data.perfiles[view.perfil];
  const total = view.requiere.length;
  const owned = total - view.falta.length;
  const gained = new Set(last?.gana ?? []);
  const meter = el("i");
  $("#student").replaceChildren(
    el("div", { class: "who" },
      el("span", { class: "avatar" }, profile.nombre[0]),
      el("div", {}, el("b", {}, profile.nombre), el("small", {}, `${profile.rol} · ${profile.horas_semana} h por semana`))),
    el("div", { class: "meter" }, meter),
    el("div", { class: "meter-line" }, el("span", {}, data.objetivos[view.objetivo].nombre),
      el("span", {}, `${owned}/${total}`)),
    el("h3", {}, "Ya sabe"),
    el("div", { class: "chips" }, ...(view.habilidades.length
      ? view.habilidades.map(s => chip(s.nombre, gained.has(s.nombre) ? "own new" : "own"))
      : [chip("nada todavía")])),
    el("h3", {}, "Le falta"),
    el("div", { class: "chips" }, ...(view.falta.length ? view.falta.map(s => chip(s.nombre, "gap")) : [chip("objetivo completo", "own")])),
    el("div", { class: "totals" },
      el("div", { class: "total" }, el("b", {}, view.ruta.length), el("small", {}, "cursos")),
      el("div", { class: "total" }, el("b", {}, view.horas), el("small", {}, "horas")),
      el("div", { class: "total" }, el("b", {}, view.semanas), el("small", {}, "semanas"))));
  requestAnimationFrame(() => { meter.style.width = `${100 * owned / total}%`; });
}

function renderRoute() {
  $("#route-note").textContent = view.done ? view.reason : "";
  $("#track").replaceChildren(...(view.history.length
    ? view.history.map(record => el("div", { class: "stop" },
        el("span", { class: "n" }, record.paso),
        el("b", {}, record.nombre),
        el("small", {}, `${record.nivel} · ${record.horas} h`),
        el("span", { class: record.util ? "tag ok" : "tag no" },
           record.util ? record.aporta.join(", ") : "no hacía falta")))
    : [el("p", { class: "empty" }, "Todavía sin cursos")]));
}

/* Escenario: el bucle de decisión, paso por paso. */

function showIdle(title) {
  $("#stage").replaceChildren(el("div", { class: "idle" }, el("div", {},
    el("h3", {}, title ?? (view.done ? view.reason : data.objetivos[view.objetivo].nombre)),
    el("p", {}, view.done ? `${view.ruta.length} cursos · ${view.horas} horas · ${view.semanas} semanas`
                          : `${view.candidatos.length} cursos con los prerrequisitos cumplidos`),
    el("div", { class: "chips" }, ...(view.done ? [] : view.falta.map(s => chip(s.nombre, "gap")))))));
}

function step(n, title, badge, body) {
  return el("li", { class: "step" }, el("span", { class: "num" }, n),
    el("div", {}, el("h4", {}, title, badge ? el("b", {}, badge) : null), body));
}

function reveal(node) {
  for (const bar of node.querySelectorAll("[data-w]")) bar.style.width = bar.dataset.w;
  for (const target of node.querySelectorAll("[data-on]")) target.classList.add(...target.dataset.on.split(" ").filter(Boolean));
}

function stateBlock(state) {
  return el("div", { class: "state-list" }, ...Object.entries(state).map(([key, value]) =>
    el("div", {}, el("code", {}, key),
      el("div", { class: "chips" }, ...[].concat(value).map(v => chip(v, "small"))))));
}

function candidateBlock(record) {
  return el("div", { class: "chips" }, ...record.candidatos.map(c =>
    el("span", { class: "chip small", "data-on": c.id === record.curso ? "win" : "" }, c.nombre)));
}

function barsBlock(record) {
  const rows = Object.entries(record.probabilidades);
  const rest = rows.slice(BARS);
  return el("div", { class: "bars" }, ...rows.slice(0, BARS).map(([id, p]) =>
      el("div", { class: id === record.curso ? "bar-row win" : "bar-row" },
        el("span", {}, CATALOG[id].nombre), el("span", {}, pct(100 * p)),
        el("span", { class: "track" }, el("i", { "data-w": `${100 * p}%` })))),
    rest.length ? el("small", { class: "muted" }, `y ${rest.length} candidatos más por debajo`) : null);
}

function choiceBlock(record) {
  const course = CATALOG[record.curso];
  return el("div", {},
    el("div", { class: "pickcard" },
      el("span", { class: "level", style: `background:var(${LEVEL[record.nivel]})` }, `${record.horas} h`),
      el("div", {}, el("b", {}, record.nombre),
        el("small", {}, `Nivel ${record.nivel} · enseña ${course.ensena_nombres.join(", ")}`),
        el("div", { class: "chips why" }, ...(record.util ? record.aporta.map(s => chip(s, "own small"))
                                                          : [chip("no hacía falta para el objetivo", "gap small")])))),
    el("div", { class: "conf" }, el("span", { class: "pct" }, pct(record.confianza)),
      el("small", {}, "de confianza")));
}

async function showRecord(record, animate) {
  const steps = [
    step(1, "Estado", `paso ${record.paso}`, stateBlock(record.estado)),
    step(2, "Candidatos", `${record.candidatos.length} de ${data.cursos.length}`, candidateBlock(record)),
    step(3, "Decisión", null, barsBlock(record)),
    step(4, "Curso elegido", null, choiceBlock(record)),
  ];
  $("#stage").replaceChildren(
    el("div", { class: "who-line" }, el("span", { class: "turnpill" }, `Paso ${record.paso}`),
      el("span", { class: "mode" }, `El modelo decidió en ${ms(record.elapsed)}`)),
    el("ol", { class: "steps" }, ...steps));
  if (!animate) return steps.forEach(reveal);
  steps.forEach(node => node.classList.add("pending"));
  for (const node of steps) {
    node.classList.replace("pending", "active");
    await sleep(20);  // Deja pintar el estado apagado para que la transición se vea.
    reveal(node);
    await sleep(pace().reveal);
    node.classList.remove("active");
  }
}

/* Bucle: estado → candidatos → modelo → curso → estado nuevo. */

async function build() {
  if (running || view.done) return;
  running = true;
  run = { inference: 0, count: 0 };
  $("#speed").hidden = true;
  setStatus("");
  updateButtons();
  while (running && !view.done) {
    try {
      const response = await fetch("/api/courses/step", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      view = result.view;
      last = result.record;
      run.inference += last.elapsed;
      run.count += 1;
      await showRecord(last, mode() === "pasos");
      renderStudent();
      renderRoute();
      await (pace().hold ? sleep(pace().hold) : frame());
    } catch (error) {
      running = false;
      setStatus(`La ruta se detuvo: ${error.message}`);
    }
  }
  running = false;
  updateButtons();
  if (view.done && run.count) showSpeed($("#speed"), run.inference, run.count, "decisión");
}

async function restart() {
  running = false;
  const query = `?objetivo=${encodeURIComponent($("#goal").value)}&perfil=${encodeURIComponent($("#profile").value)}`;
  const response = await fetch(`/api/courses/reset${query}`, { method: "POST" });
  const result = await response.json();
  if (!response.ok) return setStatus(result.error);
  ({ view } = result);
  last = null;
  run = { inference: 0, count: 0 };
  $("#speed").hidden = true;
  setStatus("");
  renderAll();
  showIdle();
}

function updateButtons() {
  $("#build").disabled = running || view.done;
  $("#reset").disabled = running;
  $("#goal").disabled = $("#profile").disabled = running;
}

function setStatus(text) {
  $("#status").textContent = text;
}

$("#build").addEventListener("click", build);
$("#reset").addEventListener("click", restart);
$("#goal").addEventListener("change", restart);
$("#profile").addEventListener("change", restart);
