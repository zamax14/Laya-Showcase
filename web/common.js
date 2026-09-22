// Estado del modelo en la barra superior; se consulta hasta que Laya carga o falla.
const LABELS = { idle: "Preparando Laya…", loading: "Cargando Laya…", ready: "Laya lista", error: "Laya no cargó" };

export function watchModel(element) {
  const label = element.querySelector("span");
  async function check() {
    try {
      const status = await (await fetch("/api/status")).json();
      element.dataset.state = status.model;
      label.textContent = status.model === "ready" && status.device ? `Laya en ${status.device === "cuda" ? "GPU" : "CPU"}`
                                                                    : LABELS[status.model] ?? status.model;
      element.title = status.error ?? "";
      if (status.model === "ready" || status.model === "error") return;
    } catch {
      element.dataset.state = "error";
      label.textContent = "Sin conexión con el servidor";
    }
    setTimeout(check, 1000);
  }
  check();
}

export const $ = selector => document.querySelector(selector);

export function svg(tag, attributes = {}, parent) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  parent?.append(node);
  return node;
}

// Modo de las demos: «real» pinta cada decisión en cuanto Laya la toma; «pasos» va a ritmo de lectura.
// Se recuerda entre páginas en este navegador.
const MODE_KEY = "laya-modo";

export function modeToggle(container) {
  let mode = "real";
  try { if (localStorage.getItem(MODE_KEY) === "pasos") mode = "pasos"; } catch {}
  container.className = "tabs";
  container.setAttribute("role", "group");
  container.setAttribute("aria-label", "Velocidad");
  const buttons = [["real", "Real-Time"], ["pasos", "Paso a paso"]].map(([value, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.mode = value;
    button.textContent = label;
    return button;
  });
  container.replaceChildren(...buttons);
  const set = value => {
    mode = value;
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.dataset.mode === value));
    try { localStorage.setItem(MODE_KEY, value); } catch {}
  };
  container.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (button) set(button.dataset.mode);
  });
  set(mode);
  return () => mode;
}

// Velocidad real de Laya: tiempo de inferencia medido en el servidor, no el de la animación.
export async function showSpeed(element, seconds, count, noun) {
  if (!count) return;
  let where = "";
  try { where = (await (await fetch("/api/status")).json()).device === "cuda" ? " en GPU" : " en CPU"; } catch {}
  const format = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const each = document.createElement("b"), detail = document.createElement("small");
  each.textContent = `${Math.round(1000 * seconds / count)} ms`;
  detail.textContent = `por ${noun}${where} (${count} en ${format.format(seconds)} s)`;
  element.replaceChildren(each, " ", detail);
  element.hidden = false;
}
