// Selector compartido: la cookie del servidor conserva el modelo entre páginas.

export function watchModel(element) {
  const label = element.querySelector("span");
  const benchmark = document.createElement("a");
  benchmark.className = "bench-link";
  benchmark.href = "/benchmark";
  benchmark.textContent = "Benchmark";
  if (location.pathname !== "/benchmark") element.before(benchmark);
  const picker = document.createElement("label");
  picker.className = "model-picker";
  picker.textContent = "Modelo ";
  const select = document.createElement("select");
  picker.append(select);
  element.before(picker);
  select.addEventListener("change", async () => {
    select.disabled = true;
    try {
      const response = await fetch(`/api/model?name=${encodeURIComponent(select.value)}`, { method: "POST" });
      if (!response.ok) throw new Error("No se pudo cambiar el modelo");
      location.reload();
    } catch (error) {
      label.textContent = error.message;
      select.disabled = false;
    }
  });
  async function check() {
    try {
      const status = await (await fetch("/api/status")).json();
      if (!select.options.length) {
        // Locales primero; los de pago aparte para que se vea que cuestan y van por la red.
        for (const [group, remote] of [["Local", false], ["OpenRouter (API)", true]]) {
          const entries = Object.entries(status.models).filter(([, m]) => m.remote === remote);
          if (!entries.length) continue;
          const optgroup = document.createElement("optgroup");
          optgroup.label = group;
          for (const [key, m] of entries) optgroup.append(new Option(m.name, key));
          select.append(optgroup);
        }
      }
      select.value = status.selected;
      element.dataset.state = status.model;
      const name = status.models[status.selected].name;
      label.textContent = status.model === "ready" ? `${name} ${where(status)}`
                        : status.model === "error" ? `${name}: no disponible`
                        : `${name}: ${status.model === "loading" ? "cargando…" : "pendiente"}`;
      element.title = status.error ?? "";  // El detalle completo, sin desbordar la barra.
      if (status.model === "error" || (status.model === "ready" && status.device !== "api")) return;
      // Los de pago siguen consultándose para que el gasto se vea subir mientras se usan.
      return setTimeout(check, status.model === "ready" ? 3000 : 1000);
    } catch {
      element.dataset.state = "error";
      label.textContent = "Sin conexión con el servidor";
    }
    setTimeout(check, 1000);
  }
  check();
}

export const $ = selector => document.querySelector(selector);

const usd = new Intl.NumberFormat("es", { style: "currency", currency: "USD", maximumSignificantDigits: 2 });

// «en GPU», «en CPU» o «vía OpenRouter · US$0,0012 gastados».
export function where(status) {
  if (status.device !== "api") return status.device === "cuda" ? "en GPU" : "en CPU";
  const cost = status.usage?.cost_usd;
  return cost ? `vía OpenRouter · ${usd.format(cost)} gastados` : "vía OpenRouter";
}

export function svg(tag, attributes = {}, parent) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  parent?.append(node);
  return node;
}

// Modo de las demos: «real» pinta cada decisión al recibirla; «pasos» va a ritmo de lectura.
// Se recuerda entre páginas en este navegador.
const MODE_KEY = "arbiter-modo";

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

// Tiempo de inferencia medido en el servidor, no el de la animación.
export async function showSpeed(element, seconds, count, noun) {
  if (!count) return;
  let place = "";
  try { place = ` ${where(await (await fetch("/api/status")).json()).split(" · ")[0]}`; } catch {}
  const format = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const each = document.createElement("b"), detail = document.createElement("small");
  each.textContent = `${Math.round(1000 * seconds / count)} ms`;
  detail.textContent = `por ${noun}${place} (${count} en ${format.format(seconds)} s)`;
  element.replaceChildren(each, " ", detail);
  element.hidden = false;
}
