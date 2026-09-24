import { $, modeToggle, showSpeed, watchModel } from "./common.js";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
// Real-Time: la ruta entera de una tirada. Paso a paso: cada pregunta de la vuelta a ritmo de lectura.
const pace = () => mode() === "pasos" ? { reveal: REDUCED ? 40 : 340, hold: REDUCED ? 80 : 900 }
                                      : { reveal: 0, hold: REDUCED ? 0 : 60 };
const pct = n => n > 0 && n < .5 ? "<1 %" : `${Math.round(n)} %`;
const ms = s => `${Math.round(s * 1000)} ms`;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const frame = () => new Promise(requestAnimationFrame);

watchModel($("#model"));
const data = await (await fetch("/api/tools")).json();
const CATALOG = Object.fromEntries(data.herramientas.map(t => [t.id, t]));
let view = data.view, running = false;
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

$("#examples").replaceChildren(...data.ejemplos.map(example => {
  const button = el("button", { type: "button" }, example.texto);
  button.addEventListener("click", () => { $("#prompt").value = example.texto; trace(); });
  return button;
}));

renderCatalog();
renderRoute();
showIdle();

/* Catálogo: las 20 herramientas con su descripción, agrupadas por servidor. */

function renderCatalog() {
  const order = Object.keys(data.servidores);
  const called = new Map(view.llamadas.map((call, index) => [call.id, { n: index + 1, rule: call.regla }]));
  $("#catalog").replaceChildren(...order.map(server => el("div", { class: "server" },
    el("h3", {}, el("span", { class: "swatch", style: `background:var(--${server})` }), data.servidores[server]),
    ...data.herramientas.filter(tool => tool.servidor === server).map(tool => {
      const mark = called.get(tool.id);
      return el("div", { class: mark ? "tool used" : "tool" },
        mark ? el("span", { class: mark.rule ? "n rule" : "n" }, mark.n) : el("span", {}),
        el("div", {}, el("code", {}, tool.id), el("small", {}, tool.descripcion)));
    }))));
}

function renderRoute() {
  $("#route-note").textContent = view.done ? view.reason : "";
  $("#track").replaceChildren(...(view.llamadas.length
    ? view.llamadas.map((call, index) => el("div", { class: "stop" },
        el("span", { class: call.regla ? "n rule" : "n" }, index + 1),
        el("code", {}, call.id),
        el("small", {}, CATALOG[call.id].servidor_nombre),
        call.regla ? el("span", { class: "tag" }, `hace falta ${call.porque}`) : null))
    : [el("p", { class: "empty" }, "Todavía sin llamadas")]));
}

/* Escenario: las tres preguntas de la vuelta y lo que añaden las reglas. */

function showIdle(title) {
  $("#stage").replaceChildren(el("div", { class: "idle" }, el("div", {},
    el("h3", {}, title ?? (view.peticion || "Escribe una petición o toca un ejemplo")),
    el("p", {}, view.done && view.llamadas.length
      ? `${view.llamadas.length} llamadas · ${view.reason}`
      : "El modelo elige servidor y herramienta; las reglas encadenan los argumentos"))));
}

function step(n, title, badge, body, wide) {
  return el("li", { class: wide ? "step wide" : "step" }, el("span", { class: "num" }, n),
    el("div", {}, el("h4", {}, title, badge ? el("b", {}, badge) : null), body));
}

function reveal(node) {
  for (const bar of node.querySelectorAll("[data-w]")) bar.style.width = bar.dataset.w;
  for (const target of node.querySelectorAll("[data-on]")) target.classList.add(...target.dataset.on.split(" ").filter(Boolean));
}

function stateBlock(state) {
  return el("div", { class: "state-list" }, ...Object.entries(state).map(([key, value]) =>
    el("div", {}, el("code", {}, key),
      Array.isArray(value) ? el("div", { class: "chips" }, ...value.map(v => chip(v)))
                           : el("p", {}, value))));
}

// La probabilidad de «ya está cubierta» frente al umbral con el que para el bucle.
function stopBlock(stop) {
  if (!stop) return el("p", { class: "first" }, "Primera vuelta: todavía no hay nada llamado.");
  return el("div", {},
    el("div", { class: "gauge" }, el("i", { "data-w": `${stop.probabilidad}%` }),
      el("span", { class: "mark", style: `left:${stop.umbral}%` })),
    el("div", { class: "verdict" }, el("span", { class: "pct" }, pct(stop.probabilidad)),
      el("small", {}, stop.para ? `por encima del ${stop.umbral} %: para` : `por debajo del ${stop.umbral} %: sigue`)));
}

function barsBlock(probabilities, winner, label) {
  const rows = Object.entries(probabilities);
  return el("div", { class: "bars" }, ...rows.map(([key, p]) =>
    el("div", { class: key === winner ? "bar-row win" : "bar-row" },
      el("span", {}, label(key)), el("span", {}, pct(100 * p)),
      el("span", { class: "track" }, el("i", { "data-w": `${100 * p}%` })))));
}

function callsBlock(record) {
  return el("div", { class: "calls" }, ...record.llamadas.map(call =>
    el("div", { class: call.regla ? "call rule" : "call" }, el("code", {}, call.id),
      el("small", {}, call.regla ? `hace falta ${call.porque}` : "lo eligió el modelo"))));
}

async function showRecord(record, animate) {
  const steps = [step(1, "Estado", `vuelta ${record.vuelta}`, stateBlock(record.estado)),
                 step(2, "¿Ya está cubierta?", null, stopBlock(record.parar))];
  if (record.servidor)
    steps.push(step(3, "Servidor", `confianza ${pct(record.servidor.confianza)}`,
                    barsBlock(record.servidor.probabilidades, record.servidor.elegido, key => data.servidores[key])));
  if (record.herramienta)
    steps.push(step(4, "Herramienta", `confianza ${pct(record.herramienta.confianza)}`,
                    barsBlock(record.herramienta.probabilidades, record.herramienta.id, key => key)));
  if (record.llamadas.length)
    steps.push(step(5, "Llamadas de esta vuelta", `${record.llamadas.length}`, callsBlock(record), true));
  if (record.fin)
    steps.push(step(steps.length + 1, "Ruta lista", view.reason,
                    el("div", { class: "calls" }, ...view.llamadas.map((call, index) =>
                      el("div", { class: call.regla ? "call rule" : "call" },
                        el("code", {}, `${index + 1}. ${call.id}`)))), true));
  $("#stage").replaceChildren(
    el("div", { class: "who-line" }, el("span", { class: "turnpill" }, `Vuelta ${record.vuelta}`),
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

/* Bucle: petición → vueltas de decisión hasta que el modelo la da por cubierta. */

async function trace() {
  if (running) return;
  const prompt = $("#prompt").value.trim();
  if (!prompt) return setStatus("Escribe qué quieres que haga el agente.");
  running = true;
  run = { inference: 0, count: 0 };
  $("#speed").hidden = true;
  setStatus("");
  updateButtons();
  try {
    const response = await fetch(`/api/tools/reset?q=${encodeURIComponent(prompt)}`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    ({ view } = result);
    renderCatalog();
    renderRoute();
    showIdle("El modelo lee la petición…");
    while (running && !view.done) {
      const step = await fetch("/api/tools/step", { method: "POST" });
      const payload = await step.json();
      if (!step.ok) throw new Error(payload.error);
      view = payload.view;
      run.inference += payload.record.elapsed;
      run.count += 1;
      await showRecord(payload.record, mode() === "pasos");
      renderCatalog();
      renderRoute();
      await (pace().hold ? sleep(pace().hold) : frame());
    }
  } catch (error) {
    setStatus(`La ruta se detuvo: ${error.message}`);
  } finally {
    running = false;
    updateButtons();
    if (view.done && run.count) showSpeed($("#speed"), run.inference, run.count, "vuelta");
  }
}

async function clear() {
  running = false;
  const response = await fetch("/api/tools/reset", { method: "POST" });
  ({ view } = await response.json());
  $("#prompt").value = "";
  $("#speed").hidden = true;
  setStatus("");
  renderCatalog();
  renderRoute();
  showIdle();
}

function updateButtons() {
  $("#trace").disabled = running;
  $("#clear").disabled = running;
  $("#prompt").disabled = running;
}

function setStatus(text) {
  $("#status").textContent = text;
}

$("#ask").addEventListener("submit", event => { event.preventDefault(); trace(); });
$("#clear").addEventListener("click", clear);
