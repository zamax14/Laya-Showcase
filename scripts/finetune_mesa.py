"""Fine-tune de Laya Multilingual para la Mesa de ayuda, con validación y comparación contra la base.

    .venv/bin/python synth.py --prompt "tickets de TI de una empresa mediana" --n 720    # datos (Ollama)
    .venv/bin/python scripts/finetune_mesa.py              # prueba: 72 casos, 1 época, tope de 3 GB de GPU
    .venv/bin/python scripts/finetune_mesa.py --completo   # todos los casos, 4 épocas, todo el modelo (GPU de 12 GB o más)

Fases:
1. Lee los casos de data/sintetico.csv, que escribe synth.py con la respuesta decidida de antemano.
2. Jev los etiqueta como profesor: aporta su distribución y descarta los casos que no ve en la categoría pedida.
   Sus respuestas se guardan en data/profesor.jsonl y solo se piden las que faltan. Sin llave de OpenRouter, o con
   --sin-profesor, se entrena con la etiqueta del CSV suavizada.
3. Se mide Laya sin ajustar.
4. Se entrena con RLCD, la receta del notebook oficial de Laya
   (https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb).
5. Se calibra con casos apartados.
6. Se compara en validación y en los 20 tickets del benchmark, que nunca entran al entrenamiento.
7. Se guarda en formato de checkpoint de Laya.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fastload  # noqa: E402  Antes que torch: fija HF_HOME, HF_TOKEN y TORCH_DISABLE_NATIVE_JIT.

import json  # noqa: E402
import random  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402

import benchmark  # noqa: E402
import synth  # noqa: E402
from remote import JevModel  # noqa: E402
from tickets import CATEGORIES, PRIORITIES, TICKETS, ticket_state  # noqa: E402

SEED = 20260923
QUESTIONS = benchmark.QUESTIONS  # Las mismas tres preguntas que mide el benchmark.
LEVELS = list(PRIORITIES)
TEACHER_PATH = ROOT / "data" / "profesor.jsonl"
TEACHER_WEIGHT = 0.3  # Objetivo = 70 % la etiqueta pedida + 30 % la distribución de Jev.
SMOOTHING = 0.1  # Sin profesor: 90 % a la etiqueta y el resto repartido entre las demás opciones.
SPLIT = (0.8, 0.1, 0.1)  # Entrenamiento, calibración, validación.
LR_ENCODER, LR_HEAD = 2.5e-5, 1e-4
GROUP_SIZE = 4  # Muestras con ruido por secuencia en la parte de refuerzo.
SIGMA_START, SIGMA_END = 0.4, 0.1
# Prueba: 2 casos por combinación y solo las 6 capas superiores del encoder (de 22) y la cabeza, ~45 M de
# parámetros entrenables. Completo: todos los casos y todo el modelo.
PROFILES = {"prueba": {"cases_per_spec": 2, "epochs": 1, "micro_batch": 4, "grad_accum": 4, "freeze_layers": 16,
                       "gpu_limit_gb": 3.0, "suffix": "-prueba"},
            "completo": {"cases_per_spec": None, "epochs": 4, "micro_batch": 8, "grad_accum": 8, "freeze_layers": 0,
                         "gpu_limit_gb": None, "suffix": ""}}


# ---------------------------------------------------------------- 1–2. Casos y profesor

def pick(cases, per_spec):
    """Como mucho per_spec casos por combinación, siempre los mismos para una semilla."""
    if per_spec is None:
        return cases
    groups = {}
    for case in cases:
        groups.setdefault((*case["referencia"][:2], case["bloquea"]), []).append(case)
    rng = random.Random(SEED)
    return [c for key in sorted(groups, key=str) for c in rng.sample(groups[key], min(per_spec, len(groups[key])))]


def load_teacher(cases, enabled):
    """Respuestas de Jev por id: se leen de la caché y solo se piden las que faltan."""
    teacher = {}
    if TEACHER_PATH.exists():
        teacher = {r["id"]: r["answers"] for r in map(json.loads, TEACHER_PATH.open(encoding="utf-8"))}
    missing = [c for c in cases if c["id"] not in teacher]
    if not enabled or not missing:
        print(f"Profesor: {sum(c['id'] in teacher for c in cases)}/{len(cases)} casos con respuesta de Jev en caché")
        return teacher
    jev = JevModel()
    if jev.status == "error":
        print(f"Profesor: {jev.error}; los {len(missing)} casos sin caché usan la etiqueta suavizada")
        return teacher

    def ask(case):
        try:
            return case["id"], jev.predict(ticket_state(case), QUESTIONS)["answers"]
        except Exception as exc:
            print(case["id"], "falló:", exc, flush=True)
            return case["id"], None

    with ThreadPoolExecutor(8) as pool:
        new = {k: v for k, v in pool.map(ask, missing) if v}
    TEACHER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TEACHER_PATH.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps({"id": k, "answers": v}, ensure_ascii=False) + "\n" for k, v in new.items())
    print(f"Profesor: Jev etiquetó {len(new)} casos nuevos por US${jev.usage()['cost_usd']:.3f}")
    return {**teacher, **new}


def blend(index, size, soft):
    if soft is None:  # Sin profesor: etiqueta suavizada.
        return [1 - SMOOTHING if i == index else SMOOTHING / (size - 1) for i in range(size)]
    return [(1 - TEACHER_WEIGHT) * float(i == index) + TEACHER_WEIGHT * s for i, s in zip(range(size), soft)]


def targets(case, teacher):
    """Distribuciones objetivo en el orden de las opciones de Laya; noul es siempre [no, sí]."""
    category, priority, _ = case["referencia"]
    t = teacher.get(case["id"])
    return {"categoria": blend(list(CATEGORIES).index(category), len(CATEGORIES),
                               t and [t["categoria"]["probabilities"][k] for k in CATEGORIES]),
            "prioridad": blend(LEVELS.index(priority), len(LEVELS),
                               t and [t["prioridad"]["probabilities"][str(i)] for i in range(len(LEVELS))]),
            "bloqueo": blend(int(case["bloquea"]), 2, t and [1 - t["bloqueo"]["noul"], t["bloqueo"]["noul"]])}


def split(cases, teacher):
    """Descarta los casos en los que Jev no ve la categoría pedida y reparte el resto."""
    kept = [c for c in cases if c["id"] not in teacher or teacher[c["id"]]["categoria"]["choice"] == c["referencia"][0]]
    graded = [c for c in cases if c["id"] in teacher]
    if graded:
        print(f"Jev coincide con la categoría pedida en {sum(c in kept for c in graded)}/{len(graded)} casos; el resto se descarta.")
        for category in CATEGORIES:
            total = sum(c["referencia"][0] == category for c in graded)
            print(f"  {category:10} {sum(c['referencia'][0] == category and c in kept for c in graded)}/{total}")
    random.Random(SEED).shuffle(kept)
    n_train, n_calib = int(SPLIT[0] * len(kept)), int(SPLIT[1] * len(kept))
    return kept[:n_train], kept[n_train:n_train + n_calib], kept[n_train + n_calib:]


# ---------------------------------------------------------------- 3–7. Modelo

class Trainer:
    def __init__(self, cfg):
        from laya.common import QTYPES
        self.cfg, self.qtypes = cfg, QTYPES
        self.agent = fastload.load_agent(device="cuda")
        self.agent.cfg["max_len"], self.agent.cfg["head_max_len"] = 8192, 256  # Los mismos topes que usa Arbiter.
        self.model, self.device = self.agent.model, self.agent.device
        self.pad = self.agent.tok.pad_token_id
        self.amp = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16  # La T4 no tiene bf16.

    def evaluate(self, dataset):
        from laya.common import ece_score
        self.model.eval()
        rows = []
        for case in dataset:
            started = time.perf_counter()
            answers = self.agent.predict(ticket_state(case), QUESTIONS)["answers"]
            rows.append(benchmark.row(case, answers, 1000 * (time.perf_counter() - started)))
        summary = benchmark.summarize(rows)
        graded = [r for r in rows if r["expected_category"]]
        summary["category_ece"] = round(float(ece_score(
            np.array([r["category_confidence"] / 100 for r in graded]),
            np.array([r["category"] == r["expected_category"] for r in graded], float))), 3)
        return summary, rows

    def items(self, dataset, teacher):
        """Una secuencia por caso y pregunta, construida con el mismo código con el que Laya predice."""
        from laya.common import build_sequence
        out = []
        for case in dataset:
            goal = targets(case, teacher)
            for qid, question in QUESTIONS.items():
                internal = self.agent._to_internal(question)
                ids, markers = build_sequence(self.agent.tok, ticket_state(case), internal,
                                              self.agent.cfg["max_len"], self.agent.cfg["head_max_len"])
                assert len(markers) == len(goal[qid]), (case["id"], qid)
                out.append({"ids": ids, "markers": markers, "qtype": self.qtypes[internal["t"]], "target": goal[qid],
                            "label": int(np.argmax(goal[qid]))})
        return out

    def forward(self, batch):
        with torch.autocast("cuda", dtype=self.amp):
            logits, _ = self.model(*(batch[k].to(self.device)
                                     for k in ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")))
        return logits.float()

    @staticmethod
    def soft_ce(logits, target, mask):
        return -(target * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)).sum(-1)

    @torch.no_grad()
    def val_loss(self, items):
        from laya.common import collate_items
        self.model.eval()
        total = 0.0
        for i in range(0, len(items), 16):
            batch = collate_items([items[i:i + 16]], self.pad)
            total += self.soft_ce(self.forward(batch), batch["target"].to(self.device),
                                  batch["marker_mask"].to(self.device)).sum().item()
        return total / len(items)

    def snapshot(self):
        return {k: (v.half() if v.is_floating_point() else v).detach().cpu().clone() for k, v in self.model.state_dict().items()}

    def train(self, train_items, val_items):
        """RLCD como el notebook oficial: muestras con ruido premiadas con reglas de puntuación propias + CE suave."""
        from laya.common import collate_items, proper_reward
        cfg, model, device = self.cfg, self.model, self.device
        encoder = model.encoder
        encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        for module in ([encoder.embeddings, *encoder.layers[:cfg["freeze_layers"]]] if cfg["freeze_layers"] else []):
            module.requires_grad_(False)
        trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW([{"params": [p for n, p in trainable if n.startswith("encoder.")], "lr": LR_ENCODER},
                                       {"params": [p for n, p in trainable if not n.startswith("encoder.")], "lr": LR_HEAD}],
                                      weight_decay=0.01)
        updates = cfg["epochs"] * -(-len(train_items) // (cfg["micro_batch"] * cfg["grad_accum"]))
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=updates, eta_min=1e-6)
        scaler = torch.amp.GradScaler("cuda", enabled=self.amp == torch.float16)
        print(f"{sum(p.numel() for _, p in trainable) / 1e6:.0f} M parámetros entrenables · {updates} actualizaciones · {self.amp}")

        best_loss, best_state = self.val_loss(val_items), None
        print(f"CE de validación antes de entrenar: {best_loss:.4f}", flush=True)
        for epoch in range(cfg["epochs"]):
            model.train()
            sigma = SIGMA_START + (SIGMA_END - SIGMA_START) * epoch / max(1, cfg["epochs"] - 1)
            random.Random(SEED + epoch).shuffle(train_items)
            started, running, steps = time.time(), 0.0, 0
            for i in range(0, len(train_items), cfg["micro_batch"]):
                batch = collate_items([train_items[i:i + cfg["micro_batch"]]], self.pad)
                logits = self.forward(batch)
                mask, target, qtype = (batch[k].to(device) for k in ("marker_mask", "target", "qtype"))
                k = mask.sum(-1, keepdim=True).float()
                eps = torch.randn((GROUP_SIZE,) + logits.shape, device=device) * sigma * mask
                eps = (eps - eps.sum(-1, keepdim=True) / k) * mask  # Ruido de media cero sobre los logits.
                z = logits.detach().unsqueeze(0) + eps
                with torch.no_grad():
                    reward = proper_reward(torch.softmax(z.masked_fill(~mask, -1e4), -1), target.unsqueeze(0), qtype, mask,
                                           w_sph=0.75, w_rps=1.0)
                    advantage = reward - reward.mean(0, keepdim=True)
                    advantage = advantage / (advantage.std() + 1e-6)
                logp = -(((z - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma ** 2)
                loss_ce = self.soft_ce(logits, target, mask).mean()
                scaler.scale((-(advantage * logp).mean() + loss_ce) / cfg["grad_accum"]).backward()
                running, steps = running + loss_ce.item(), steps + 1
                if steps % cfg["grad_accum"] == 0 or i + cfg["micro_batch"] >= len(train_items):
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    scaler.step(optimizer)
                    scaler.update()
                    scheduler.step()
                    optimizer.zero_grad(set_to_none=True)
            loss = self.val_loss(val_items)
            print(f"época {epoch + 1}/{cfg['epochs']}: CE entrenamiento {running / steps:.4f} · CE validación {loss:.4f} · "
                  f"{time.time() - started:.0f} s · VRAM máx. {torch.cuda.max_memory_allocated() / 2**30:.2f} GB", flush=True)
            if loss < best_loss:
                best_loss, best_state = loss, self.snapshot()
        del optimizer, scaler
        torch.cuda.empty_cache()
        if best_state is not None:
            model.load_state_dict(best_state)
        return best_loss, best_state is not None

    @torch.no_grad()
    def calibrate(self, items):
        """Una temperatura por tipo de pregunta; laya-multilingual viene con las tres en 1,0 (sin calibrar)."""
        from laya.common import clamp_temperature, collate_items
        self.model.eval()
        pairs = {qt: [] for qt in range(3)}
        for i in range(0, len(items), 16):
            chunk = items[i:i + 16]
            logits = self.forward(collate_items([chunk], self.pad))
            for r, it in enumerate(chunk):
                pairs[it["qtype"]].append((logits[r, :len(it["markers"])].cpu(), torch.tensor(it["target"])))

        def fit(sel):
            if len(sel) < 10:
                return 1.0
            with torch.enable_grad():
                log_t = torch.zeros(1, requires_grad=True)
                opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

                def closure():
                    opt.zero_grad()
                    loss = -sum((t * torch.log_softmax(z / log_t.exp(), -1)).sum() for z, t in sel) / len(sel)
                    loss.backward()
                    return loss

                opt.step(closure)
            return clamp_temperature(float(log_t.exp()))

        fitted = [fit(pairs[qt]) for qt in range(3)]
        self.agent.temperature, self.agent.temperature_by_options = fitted, {}
        print("Temperaturas:", {name: round(fitted[i], 3) for name, i in self.qtypes.items()},
              "(1,0 = menos de 10 casos por tipo)" if min(len(p) for p in pairs.values()) < 10 else "")
        return fitted

    def save(self, out_dir, fitted, report):
        from huggingface_hub import snapshot_download
        from safetensors.torch import save_file
        repo, revision = fastload.CHECKPOINT.split("@")
        base_dir = Path(snapshot_download(repo, revision=revision, allow_patterns=["tokenizer/*", "encoder/*"]))
        # Copia los archivos (no los enlaces de la caché) salvo los que se escriben a continuación.
        shutil.copytree(base_dir, out_dir, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("model.safetensors", "rl_agent_config.json"))
        save_file({k: v.contiguous() for k, v in self.snapshot().items()}, out_dir / "model.safetensors")
        config = {**self.agent.cfg, "fine_tuned": True, "model_name": "laya-mesa-de-ayuda", "temperature": fitted,
                  "fine_tuned_from": fastload.CHECKPOINT}
        config.pop("temperature_by_options", None)
        (out_dir / "rl_agent_config.json").write_text(json.dumps(config, indent=2))
        (out_dir / "resultados.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        # Comprobación: el checkpoint guardado se carga con Laya y decide igual que el modelo en memoria.
        import laya
        state = ticket_state(TICKETS[0])
        a = self.agent.predict(state, QUESTIONS)["answers"]["categoria"]["choice"]
        self.model.to("cpu")  # Dos copias de 1,3 GB en la GPU pasarían el tope de la prueba.
        torch.cuda.empty_cache()
        reloaded = laya.load(str(out_dir), device="cuda")
        reloaded.cfg["max_len"], reloaded.cfg["head_max_len"] = 1024, 256
        b = reloaded.predict(state, QUESTIONS)["answers"]["categoria"]["choice"]
        assert a == b, f"El checkpoint recargado decide distinto: {a} frente a {b}"
        print("Guardado en", out_dir.relative_to(ROOT), "y comprobado al recargarlo")


METRICS = [("Categoría", lambda s: f"{s['category_correct']}/{s['category_total']}"),
           ("Prioridad exacta", lambda s: f"{s['priority_correct']}/{s['priority_total']}"),
           ("Prioridad a ±1", lambda s: f"{s['priority_near']}/{s['priority_total']}"),
           ("Bloqueo", lambda s: f"{s['blocking_correct']}/{s['blocking_total']}"),
           ("Brier del bloqueo", lambda s: s["blocking_brier"]),
           ("ECE de la categoría", lambda s: s["category_ece"]),
           ("Aciertos en verde", lambda s: f"{s['lights']['verde']['correct']}/{s['lights']['verde']['total']}"),
           ("Aciertos en rojo", lambda s: f"{s['lights']['rojo']['correct']}/{s['lights']['rojo']['total']}"),
           ("Latencia p50", lambda s: f"{s['p50_latency_ms']:.0f} ms")]


def compare(base_val, ft_val, base_test, ft_test, base_rows, ft_rows):
    print("\n| | Validación: base | Validación: ajustada | Benchmark: base | Benchmark: ajustada |\n|---|---|---|---|---|")
    for name, f in METRICS:
        print(f"| {name} | {f(base_val)} | {f(ft_val)} | {f(base_test)} | {f(ft_test)} |")
    changes = [(b, f) for b, f in zip(base_rows, ft_rows) if (b["category"], b["priority"]) != (f["category"], f["priority"])]
    print(f"\n{len(changes)} tickets del benchmark cambian de categoría o prioridad:")
    for b, f in changes:
        print(f"  {b['id']} {b['title']} (referencia {b['expected_category'] or 'ambiguo'} · {b['expected_priority']}): "
              f"{b['category']} {b['category_confidence']} % · {b['priority']} → {f['category']} {f['category_confidence']} % · {f['priority']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--completo", action="store_true", help="720 casos, 4 épocas, todo el modelo, sin tope de GPU")
    parser.add_argument("--gpu-limit", type=float, help="tope de GPU en GB (prueba: 3; 0 = sin tope)")
    parser.add_argument("--datos", type=Path, default=synth.CSV_PATH, help="CSV que escribe synth.py")
    parser.add_argument("--sin-profesor", action="store_true", help="no consultar a Jev; etiqueta suavizada")
    args = parser.parse_args()
    cfg = dict(PROFILES["completo" if args.completo else "prueba"])
    if args.gpu_limit is not None:
        cfg["gpu_limit_gb"] = args.gpu_limit or None
    random.seed(SEED)
    torch.manual_seed(SEED)
    out_dir = ROOT / ".model-cache" / f"laya-mesa-de-ayuda{cfg['suffix']}"

    if not torch.cuda.is_available():
        raise SystemExit("Hace falta una GPU con CUDA para entrenar.")
    if cfg["gpu_limit_gb"]:
        free, total = torch.cuda.mem_get_info()
        if free < cfg["gpu_limit_gb"] * 2**30:
            raise SystemExit(f"Solo hay {free / 2**30:.1f} GB libres en la GPU: cierra Arbiter (Laya ocupa 1,6 GB y Kev "
                             f"3,7 GB) u otros procesos que la usen.")
        # Tope duro: si el entrenamiento lo supera, falla con OutOfMemoryError en vez de llenar la GPU. Cubre los
        # tensores; el contexto de CUDA suma ~0,4 GB fuera de él, así que se descuenta.
        torch.cuda.set_per_process_memory_fraction((cfg["gpu_limit_gb"] - 0.4) * 2**30 / total)
        print(f"Tope de GPU: {cfg['gpu_limit_gb']} GB ({cfg['gpu_limit_gb'] - 0.4:.1f} GB para tensores) de {total / 2**30:.1f} GB")

    print("\n## 1. Casos")
    cases = pick(synth.read(args.datos), cfg["cases_per_spec"])
    if not cases:
        raise SystemExit(f"No hay casos en {args.datos}: genéralos con «python synth.py --n 720».")
    print(f"{len(cases)} casos de {args.datos}")
    print("\n## 2. Profesor")
    teacher = load_teacher(cases, not args.sin_profesor)
    train, calib, val = split(cases, teacher)
    print(f"entrenamiento {len(train)} · calibración {len(calib)} · validación {len(val)} · benchmark {len(TICKETS)} (solo prueba)")

    print("\n## 3. Línea base", flush=True)
    trainer = Trainer(cfg)
    base_val, _ = trainer.evaluate(val)
    base_test, base_rows = trainer.evaluate(TICKETS)
    print(f"Validación: categoría {base_val['category_correct']}/{base_val['category_total']} · "
          f"benchmark: categoría {base_test['category_correct']}/{base_test['category_total']}")

    print("\n## 4. Entrenamiento", flush=True)
    train_items, calib_items, val_items = (trainer.items(d, teacher) for d in (train, calib, val))
    lengths = [len(it["ids"]) for it in train_items]
    print(f"{len(train_items)} secuencias · tokens: mediana {int(np.median(lengths))}, máximo {max(lengths)}")
    best_loss, improved = trainer.train(train_items, val_items)
    if not improved:
        raise SystemExit("Ninguna época mejoró la validación: no se guarda nada.")

    print("\n## 5. Calibración")
    fitted = trainer.calibrate(calib_items)

    print("\n## 6. Comparación", flush=True)
    ft_val, _ = trainer.evaluate(val)
    ft_test, ft_rows = trainer.evaluate(TICKETS)
    compare(base_val, ft_val, base_test, ft_test, base_rows, ft_rows)

    print("\n## 7. Guardado")
    trainer.save(out_dir, fitted, {
        "perfil": "completo" if args.completo else "prueba", "configuracion": cfg, "datos": str(args.datos),
        "profesor": sum(c["id"] in teacher for c in cases),
        "casos": {"generados": len(cases), "entrenamiento": len(train), "calibracion": len(calib), "validacion": len(val)},
        "mejor_ce_validacion": best_loss, "vram_max_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "validacion": {"base": base_val, "ajustada": ft_val}, "benchmark": {"base": base_test, "ajustada": ft_test}})


if __name__ == "__main__":
    main()
