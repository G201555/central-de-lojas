# -*- coding: utf-8 -*-
"""Baixa (com cache) miniaturas das fotos exibidas na Central, para análise de orientação/duplicadas.

As miniaturas ficam em cache_fotos/<fk>.jpg (lado maior 320 px); quem já está em cache não é baixado de novo.
"""
import io
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "cache_fotos"
LADO = 320


def fk(u):
    """mesma chave do central.html (fk)"""
    u = re.sub(r"^.*minhas_imagens/", "", u or "")
    return re.sub(r"[^A-Za-z0-9]+", "_", u)[:300]


def urls_exibidas():
    us = set()
    for f in (RAIZ / "data" / "lojas").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        us |= {g["u"] for g in d["galeria"]}
        us |= {p["a"] for p in d["pares"]} | {p["b"] for p in d["pares"]}
    return sorted(us)


def baixa(u):
    destino = CACHE / f"{fk(u)}.jpg"
    if destino.exists():
        return True
    try:
        # o servidor recusa (403) requisição sem User-Agent de navegador
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            im = Image.open(io.BytesIO(r.read()))
            im = im.convert("RGB")
            im.thumbnail((LADO, LADO))
            im.save(destino, quality=85)
        return True
    except Exception:
        return False


def baixa_todas(us, workers=16):
    CACHE.mkdir(exist_ok=True)
    ok = 0
    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(baixa, us), 1):
            ok += r
            if i % 2000 == 0:
                print(f"  {i}/{len(us)} baixadas")
    return ok


if __name__ == "__main__":
    us = urls_exibidas()
    print(len(us), "fotos exibidas")
    print(baixa_todas(us), "em cache")
