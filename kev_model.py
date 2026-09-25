"""Kev local: Pondera arranca su servidor en un entorno Python separado."""
import atexit
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from remote import normalize, post


ROOT = Path(__file__).resolve().parent
CHECKPOINT = "jaredpalmer/kev-0.8b@54f4f8777356cd5bbbb6c6919c657f26e6f2f6d8"


class KevModel:
    name = "Kev-0.8B"
    checkpoint = CHECKPOINT

    def __init__(self, port=8009):
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.python = ROOT / ".venv-kev" / "bin" / "python"
        self.process = None
        self.status, self.error, self.device = "idle", None, None
        self.lock = threading.Lock()
        atexit.register(self.close)

    def load(self):
        with self.lock:
            if self.status == "ready" and self.process and self.process.poll() is None:
                return
            self.status, self.error = "loading", None
            try:
                if not self.python.is_file():
                    raise RuntimeError("Instala Kev con ./scripts/setup-kev.sh")
                env = {**os.environ, "HF_HOME": str(ROOT / ".model-cache" / "huggingface")}
                log_path = ROOT / ".kev.log"
                for cpu in (False, True):
                    attempt_env = {**env, **({"CUDA_VISIBLE_DEVICES": ""} if cpu else {})}
                    with log_path.open("ab") as log:
                        log_start = log.tell()
                        self.process = subprocess.Popen(
                            [str(self.python), "-m", "kev.serve", "--run", CHECKPOINT,
                             "--port", str(self.port)], cwd=ROOT, env=attempt_env,
                            stdout=log, stderr=subprocess.STDOUT)
                    deadline = time.monotonic() + 300
                    while time.monotonic() < deadline:
                        if self.process.poll() is not None:
                            break
                        try:
                            with urlopen(self.url + "/v1/models", timeout=1) as response:
                                self.device = json.load(response)["models"][0]["device"]
                                self.status = "ready"
                                return
                        except OSError:
                            time.sleep(.5)
                    else:
                        raise TimeoutError("Kev tardó más de cinco minutos en iniciar; revisa .kev.log")
                    if cpu or b"torch.OutOfMemoryError" not in log_path.read_bytes()[log_start:]:
                        raise RuntimeError("Kev terminó al iniciar; revisa .kev.log")
                raise RuntimeError("Kev no pudo iniciar en GPU ni CPU; revisa .kev.log")
            except Exception as exc:
                self.status, self.error = "error", str(exc)
                self.close()
                raise

    def predict(self, state, questions):
        self.load()
        result = post(self.url + "/v1/systemone", {"state": state, "model": "kev-latest", "questions": questions})
        return {**result, "answers": normalize(result.get("answers") or {}, questions)}

    def release(self):
        """Apaga el servidor para dejar la GPU libre; la próxima predicción lo vuelve a arrancar."""
        with self.lock:
            self.close()
            if self.status == "ready":
                self.status = "idle"

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
