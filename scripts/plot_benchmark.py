"""Genera gráficas SVG y PNG a partir de las corridas guardadas del benchmark."""

import argparse
from html import escape
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "web" / "results"
OUTPUT = ROOT / "assets" / "benchmark"
WIDTH, HEIGHT = 880, 440
LEFT, RIGHT, TOP, BOTTOM = 72, 840, 126, 354
INK, GRID, MUTED = "#0d0d0d", "#d4d5d9", "#696969"
COLORS = {"laya": "#4fa8f0", "laya-mesa": "#2fbf94", "jev": "#ff8e3c", "gpt-luna": "#d9376e"}


def load_runs(laya_path, tuned_path=None):
    """Laya base, la Laya ajustada si hay corrida (github.com/zamax14/Laya-Finetune), Jev y Luna."""
    runs = []
    for key in COLORS:
        if key == "laya-mesa" and not (tuned_path and tuned_path.exists()):
            continue
        path = laya_path if key == "laya" else tuned_path if key == "laya-mesa" else RESULTS / f"{key}.json"
        run = json.loads(path.read_text(encoding="utf-8"))
        if run["status"] != "complete" or len(run["rows"]) != 20 or run["calls"] != 21:
            raise ValueError(f"Corrida incompleta: {key}")
        runs.append(run)
    if len({(run["suite"], run["fingerprint"]) for run in runs}) != 1:
        raise ValueError("Las corridas no usan el mismo conjunto de evaluación")
    return runs


def text(x, y, label, *, size=12, color=INK, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
            f'font-family="Nunito,system-ui,sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}">{escape(str(label))}</text>')


def chart(title, subtitle, groups, runs, values, labels, ticks, tick_label, footer):
    span = BOTTOM - TOP
    scale = lambda value: BOTTOM - value / ticks[-1] * span
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
             f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(title)}">',
             f'<rect x="4" y="4" width="875" height="435" rx="12" fill="{INK}"/>',
             f'<rect x="1" y="1" width="875" height="435" rx="12" fill="white" stroke="{INK}" stroke-width="2"/>',
             text(24, 36, title, size=20, weight=700),
             text(24, 57, subtitle, size=12, color=MUTED)]
    for index, run in enumerate(runs):
        x = 72 + index * min(230, 760 // len(runs))
        parts += [f'<rect x="{x}" y="74" width="15" height="15" rx="3" fill="{COLORS[run["key"]]}" '
                  f'stroke="{INK}" stroke-width="2"/>',
                  text(x + 23, 87, run["name"], size=12, weight=700)]
    for tick in ticks:
        y = scale(tick)
        dash = '' if tick == 0 else ' stroke-dasharray="3 4"'
        parts.append(f'<line x1="{LEFT}" x2="{RIGHT}" y1="{y:.1f}" y2="{y:.1f}" '
                     f'stroke="{GRID}"{dash}/>')
        parts.append(text(LEFT - 10, y + 4, tick_label(tick), color=MUTED, anchor="end"))
    group_width = (RIGHT - LEFT) / len(groups)
    inner_width = min(group_width * .72, 230)
    bar_width = (inner_width - 3 * (len(runs) - 1)) / len(runs)
    for group_index, group in enumerate(groups):
        start = LEFT + group_index * group_width + (group_width - inner_width) / 2
        for model_index, run in enumerate(runs):
            value = values(run)[group_index]
            x = start + model_index * (bar_width + 3)
            if value == 0:
                parts.append(text(round(x + bar_width / 2, 1), BOTTOM - 12, labels(run, group_index),
                                  color=MUTED, weight=700, anchor="middle"))
                continue
            y = scale(value)
            radius = min(4, BOTTOM - y)
            color = COLORS[run["key"]]
            parts.append(f'<g><title>{escape(run["name"] + " · " + group + ": " + labels(run, group_index))}</title>'
                         f'<path d="M{x:.1f},{BOTTOM} V{y + radius:.1f} Q{x:.1f},{y:.1f} {x + radius:.1f},{y:.1f} '
                         f'H{x + bar_width - radius:.1f} Q{x + bar_width:.1f},{y:.1f} {x + bar_width:.1f},{y + radius:.1f} '
                         f'V{BOTTOM} Z" fill="{color}" stroke="{INK}" stroke-width="2"/></g>')
            parts.append(text(round(x + bar_width / 2, 1), round(y - 8, 1), labels(run, group_index),
                              size=12, weight=700, anchor="middle"))
        parts.append(text(round(LEFT + (group_index + .5) * group_width, 1), 382, group,
                          size=13, weight=700, anchor="middle"))
    parts.append(text(24, 416, footer, size=10, color=MUTED))
    return "\n".join(parts + ["</svg>", ""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", action="store_true", help="también exporta PNG a 2× con Chrome")
    parser.add_argument("--laya", type=Path, default=RESULTS / "laya-gpu.json", help="corrida local que se va a comparar")
    parser.add_argument("--ajustada", type=Path, default=RESULTS / "laya-reentrenada.json", help="corrida de la Laya reentrenada, si existe")
    args = parser.parse_args()
    runs = load_runs(args.laya, args.ajustada)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    suite, fingerprint = runs[0]["suite"], runs[0]["fingerprint"]
    dates = ", ".join(sorted({run["created_at"][:10] for run in runs}))
    revision = runs[0]["checkpoint"].split("@")[-1][:8]
    footer = f"{suite} · huella {fingerprint} · {dates} · Laya {runs[0]['device']} r{revision}"
    charts = {
        "accuracy": chart(
            "Acierto por pregunta", "Porcentaje correcto: 19 categorías con referencia; 20 prioridades y bloqueos",
            ["Categoría", "Prioridad exacta", "Bloqueo"], runs,
            lambda r: [100 * r["category_correct"] / r["category_total"],
                       100 * r["priority_correct"] / r["priority_total"],
                       100 * r["blocking_correct"] / r["blocking_total"]],
            lambda r, i: f'{[100 * r["category_correct"] / r["category_total"], 100 * r["priority_correct"] / r["priority_total"], 100 * r["blocking_correct"] / r["blocking_total"]][i]:.0f} %',
            [0, 20, 40, 60, 80, 100], lambda v: f"{v:.0f} %", footer),
        "latency": chart(
            "Tiempo de respuesta", f"Milisegundos por ticket: Laya {runs[0]['device'].upper()}, APIs con red; sin calentamiento",
            ["p50", "Media", "p95"], runs,
            lambda r: [r["p50_latency_ms"], r["mean_latency_ms"], r["p95_latency_ms"]],
            lambda r, i: f'{[r["p50_latency_ms"], r["mean_latency_ms"], r["p95_latency_ms"]][i]:.0f} ms',
            [0, 600, 1200, 1800, 2400, 3000], lambda v: f"{v:.0f} ms", footer),
        "cost": chart(
            "Costo de API", "USD cobrados por 21 llamadas; Laya local $0 API (hardware aparte)",
            ["Corrida completa"], runs,
            lambda r: [r["cost_usd"] if r["cost_usd"] is not None else 0],
            lambda r, i: "$0" if r["cost_usd"] is None else f'${r["cost_usd"]:.6f}',
            [0, .002, .004, .006, .008], lambda v: f"${v:.3f}", footer),
    }
    for name, svg in charts.items():
        path = OUTPUT / f"{name}.svg"
        path.write_text(svg, encoding="utf-8")
        print(path.relative_to(ROOT))
        if args.png:
            chrome = shutil.which("google-chrome")
            if not chrome:
                raise SystemExit("No se encontró google-chrome; los SVG ya están generados")
            png = path.with_suffix(".png")
            subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=2", f"--window-size={WIDTH},{HEIGHT}",
                            f"--screenshot={png}", path.as_uri()], check=True, capture_output=True)
            print(png.relative_to(ROOT))


if __name__ == "__main__":
    main()
