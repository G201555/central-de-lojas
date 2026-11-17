# -*- coding: utf-8 -*-
r"""Junta miniaturas maiores de alguns números de uma folha de revisão (para decidir casos em dúvida).
Uso: python tools\zoom.py <pasta> n1 n2 ...   → <pasta>\zoom.jpg"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fotos_cache import CACHE
pasta = Path(sys.argv[1]); ind = json.loads((pasta / "indice.json").read_text())["fotos"]
ims = [(n, Image.open(CACHE / f"{ind[n]}.jpg")) for n in sys.argv[2:]]
W = sum(i.width for _, i in ims) + 10 * len(ims); H = max(i.height for _, i in ims) + 22
c = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(c); f = ImageFont.load_default(size=18); x = 0
for n, i in ims:
    c.paste(i, (x, 22)); d.text((x + 4, 2), n, fill="red", font=f); x += i.width + 10
c.save(pasta / "zoom.jpg", quality=88)
