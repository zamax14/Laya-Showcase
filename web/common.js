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
