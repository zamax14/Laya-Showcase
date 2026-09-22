<div align="center">

# Laya Showcase

**Tres demos en el navegador para ver decidir a [Laya](https://huggingface.co/convaiinnovations/laya),
un modelo de decisión open source que corre en tu CPU o en tu GPU.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-6c4ee3?logo=python&logoColor=white)](#empezar)
[![Modelo: Laya](https://img.shields.io/badge/modelo-Laya%20multilingual-ffc53d?logo=huggingface&logoColor=black)](https://huggingface.co/convaiinnovations/laya)
[![GPU opcional](https://img.shields.io/badge/GPU-opcional%20·%2018×-76b900?logo=nvidia&logoColor=white)](#con-gpu)
[![Frontend sin build](https://img.shields.io/badge/frontend-sin%20build-4fa8f0)](#cómo-está-hecho)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-2fbf94)](LICENSE)

<img src="docs/mesa-de-ayuda.gif" alt="Laya asigna tickets de TI uno a uno: categoría, prioridad, experto y semáforo de confianza" width="880">

</div>

## ¿Qué es Laya?

Laya es un modelo de decisión **no autorregresivo**: no escribe texto, responde preguntas tipadas.
Le das un estado (un ticket, un correo, un JSON) y preguntas de tres tipos:

| Tipo | Qué responde | Ejemplo en estas demos |
|---|---|---|
| `choice` | una opción entre varias, con probabilidad para cada una | ¿Qué categoría tiene este ticket? |
| `score` | un nivel en una escala ordenada | ¿Qué prioridad tiene? |
| `noul` | sí o no, con su probabilidad | ¿Encaja esta cocina con «comida picante»? |

Todo sale de una sola pasada del modelo, con probabilidades calibradas y sin texto que parsear ni
alucinar. Es de [ConvAI Innovations](https://huggingface.co/convaiinnovations/laya), con licencia
Apache-2.0, y sus autores la comparan con TypeSafe Jev en su ficha de Hugging Face. Aquí se usa el
checkpoint **multilingüe** (mmBERT-base, 322 M de parámetros), en CPU o GPU y en español.

```python
questions = {
    "categoria": {"type": "choice", "instructions": "Which IT category does the problem in the `ticket` belong to?",
                  "criteria": {"redes": "network: wifi, VPN, internet...", "accesos": "access: passwords, locked account..."}},
    "prioridad": {"type": "score", "instructions": "How urgent and impactful is the `ticket`?",
                  "criteria": ["low: ...", "medium: ...", "high: ...", "critical: ..."]},
}
agent.predict({"ticket": "No conecta la VPN desde casa. Trabajo en remoto y..."}, questions)
# {"answers": {"categoria": {"choice": "redes", "confidence": 0.945, "probabilities": {...}},
#              "prioridad": {"score": 1.67, "probabilities": {...}, ...}}}
```

## Las demos

### Mesa de ayuda

20 tickets de TI esperan en la cola. **Asignar con Laya** los toma uno a uno y enseña cada paso:
categoría, prioridad, el experto responsable y un **semáforo** que dice cuánta atención humana
necesita la asignación.

| Semáforo | Confianza | Qué significa | Aciertos medidos |
|---|---|---|---|
| 🟢 Verde | más de 80 % | Asignado sin revisión | 6 de 7 |
| 🟡 Amarillo | de 60 a 80 % | Un humano confirma | 4 de 5 |
| 🔴 Rojo | menos de 60 % | Un humano decide | 2 de 8 |

El semáforo es la gracia de la demo: Laya acierta la categoría en 12 de 19 tickets, pero su
confianza separa bien lo fiable de lo dudoso. «Ayuda urgente, no me funciona nada» sale en rojo,
como debe.

<img src="docs/tickets.png" alt="Mesa de ayuda con el tablero agrupado por experto y un ticket en revisión" width="880">

### Atlas

Escribe qué te apetece comer («comida picante», «fácil para vegetarianos») y Laya puntúa la
cocina de los 176 países del mapa, que se colorea mientras llegan los resultados. Cada país tiene
una ficha de cocina en español, y al tocarlo ves exactamente el texto que leyó Laya.

<img src="docs/atlas.png" alt="Atlas coloreado para «comida picante», con Indonesia seleccionada" width="880">

### City

Laya conduce un taxi por una ciudad con calles de un sentido, semáforos y STOP. En cada turno
reparte probabilidad entre siete acciones y la ciudad corrige lo que viole las reglas, y lo dice.
**Sortear** cambia de sitio el taxi, al pasajero y el destino.

<img src="docs/city.png" alt="City: el taxi de camino a recoger a Alex, con las probabilidades de cada acción" width="880">

## Empezar

```bash
git clone git@github.com:zamax14/Laya-Showcase.git
cd Laya-Showcase
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Se abre `http://127.0.0.1:8000`. La primera vez descarga el checkpoint de Hugging Face (~650 MB);
después funciona sin internet. `--port 8001` cambia el puerto y `--no-browser` no abre el navegador.

### Con GPU

Con una GPU NVIDIA, instala torch con CUDA en lugar del de CPU:

```bash
.venv/bin/pip install -r requirements-gpu.txt
.venv/bin/python server.py                # usa la GPU si torch la ve
.venv/bin/python server.py --device cpu   # para comparar
```

La terminal dice dónde cargó Laya («Laya lista en CUDA en 2,9 s») y la barra superior de la página
lo indica. Medido en una RTX 4050 de portátil frente a su propia CPU, con el mismo código:

| | CPU | GPU | Mejora |
|---|---|---|---|
| Atlas: un barrido de 176 países | 15,9 s | 1,9 s | **8,4×** |
| City: una decisión | 429 ms | 24 ms | **18×** |
| Mesa de ayuda: 20 tickets | 3,9 s | 0,7 s | **5,9×** |
| Carga del modelo | 4,3 s | 2,9 s | 1,5× |

En GPU Laya calcula en bf16, y aun así las decisiones son las mismas. Los 20 tickets reciben la
misma categoría, prioridad y semáforo, con 1,4 puntos de confianza de diferencia como mucho. El
Atlas da el mismo top 10 en cinco consultas y City toma las mismas 19 decisiones. Usa 1,5 GB de
memoria de vídeo. La Mesa de ayuda no se nota más rápida porque la página reproduce cada ticket a
ritmo de lectura; donde se nota es en el Atlas.

## Cómo está hecho

```mermaid
flowchart LR
    B["Navegador<br/>HTML + CSS + JS"] -- "JSON y streaming SSE" --> S["server.py<br/>http.server"]
    S --> T["tickets.py"]
    S --> A["atlas.py"]
    S --> C["city.py"]
    T & A & C --> M["fastload.py<br/>una sola instancia de Laya"]
```

- **Sin dependencias extra.** Aparte de `laya`, solo la biblioteca estándar de Python. El frontend
  no tiene paso de compilación, y la tipografía va incluida.
- **Resultados en streaming.** El Atlas y la Mesa de ayuda reciben cada resultado por SSE en cuanto
  sale. Una consulta nueva cancela la anterior en el servidor.
- **Un modelo para todo.** Las tres demos comparten una instancia de Laya con las inferencias en
  serie. Antes de cada inferencia se comprueba que el estado cabe en el contexto, porque Laya lo
  truncaría en silencio.

## Lo que aprendimos

Cada decisión de diseño salió de medir con el modelo real:

- **De 23 s a 5,7 s de carga.** Laya crea el encoder con pesos aleatorios (13,9 s en CPU) justo
  antes de sobrescribirlos con el checkpoint. `no_init_weights()` se salta ese paso, con logits
  idénticos bit a bit.
- **Laya dice «sí» a lo que menciona el tema.** Con fichas etiquetadas («Picante: bajo» en todas),
  121 de 176 países salían a 1,00 para «comida picante». Ahora el texto solo nombra un rasgo cuando
  el país lo tiene.
- **Algunos países dicen «sí» a todo.** El Atlas resta a cada país su «sí» medio en 8 consultas de
  calibración. El acierto medio en el top 10 pasa de 3,3 a 8,3 sobre 10.
- **No toda confianza sirve.** La de la categoría de un ticket predice bien si acierta; la de la
  prioridad no (daba 93 % al ticket más vago). El semáforo usa solo la primera.
- **Las decisiones dependientes se derivan.** Preguntar el experto aparte daba «Hardware» asignado
  a ciberseguridad; ahora el experto es el responsable de la categoría.
- **Las instrucciones en inglés clasifican mejor**, aunque el ticket esté en español: la prioridad
  acierta 11/20 frente a 7/20.
- **Torch solo CPU por defecto.** El entorno pasa de 5,6 GB a 1,2 GB, a la misma velocidad en CPU.
- **GPU sin compilar nada.** torch 2.14 manda una operación del encoder a Triton, que necesita
  `Python.h` para compilar. Con su interruptor oficial `TORCH_DISABLE_NATIVE_JIT=1` usa la operación
  normal de torch, así que no hace falta instalar `python3-dev`. Torch lo lee al importarse, por eso
  `fastload.py` lo activa antes.

Donde no llega, también se cuenta. El Atlas confunde el vino de uva con el vino de palma, y
«a la parrilla» queda enterrado en el texto libre.

## Estructura

```
├── server.py        servidor y API
├── fastload.py      carga rápida y compartida de Laya, en CPU o GPU
├── tickets.py       Mesa de ayuda: tickets, preguntas y semáforo
├── atlas.py         Atlas: fichas, calibración por país y barridos cancelables
├── city.py          City: mapa, reglas, protección y sorteo
├── assets/          mapa, fichas de cocina y calibración
├── web/             páginas, estilos y tipografía
├── tests/           pruebas sin descargar el modelo
└── docs/            capturas de este README
```

## Pruebas

Sin descargar el modelo:

```bash
python3 -m unittest discover -s tests -t .
node --test tests/test_web.mjs
```

Cubren el semáforo y el reparto de tickets, las fichas y la calibración del Atlas, las reglas de
City (también con conductores que eligen mal y viajes sorteados), la API con un modelo falso
(streaming, cancelación, errores del modelo) y la proyección y los colores del mapa.

## Créditos

- **[Laya](https://huggingface.co/convaiinnovations/laya)** de ConvAI Innovations, Apache-2.0. Los
  pesos no se incluyen: se descargan de Hugging Face.
- **Mapa** de [Natural Earth](https://www.naturalearthdata.com/), dominio público.
- **Tipografía** [Nunito](https://github.com/googlefonts/nunito), SIL Open Font License 1.1.
- **Fichas de cocina y tickets** redactados con Claude: simplifican y son ficticios. Detalle en
  [assets/README.md](assets/README.md).
- **Código** bajo licencia [MIT](LICENSE).
