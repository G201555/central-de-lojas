# -*- coding: utf-8 -*-
"""Gira as fotos deitadas nos JSON da Central (rodar depois do montar.py, antes do publicar.py).

O app de campo salva parte das fotos deitada e sem EXIF. Os modelos locais não acertam o giro com
segurança, então tools\\orientacao.py só aponta as suspeitas (CLIP), tools\\revisao.py monta folhas
com as mais suspeitas para revisão visual, e as deitadas confirmadas vão para tools\\rotacoes.json
({fk: graus}). Só essas são giradas.

Nenhuma foto é removida: fotos parecidas da mesma visita (ex.: "bolas limpas" e "bolas calibradas")
são execuções diferentes e ficam todas (decisão do usuário, 20/10/2026).

Grava em data\\lojas\\<cod>.json: galeria[].r e pares[].ra / pares[].rb (graus, sentido horário).
Uso: python tools\\fotos.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROTACOES = Path(__file__).resolve().parent / "rotacoes.json"  # revisadas: {fk: 90|180|270}


def fk(u):
    import re
    u = re.sub(r"^.*minhas_imagens/", "", u or "")
    return re.sub(r"[^A-Za-z0-9]+", "_", u)[:300]


def main():
    rot = json.loads(ROTACOES.read_text()) if ROTACOES.exists() else {}
    girados = 0
    for f in sorted((ROOT / "data" / "lojas").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for g in d["galeria"]:
            g.pop("r", None)
            if (r := rot.get(fk(g["u"]))):
                g["r"] = r
                girados += 1
        for p in d["pares"]:
            for lado, campo in (("a", "ra"), ("b", "rb")):
                p.pop(campo, None)
                if (r := rot.get(fk(p[lado]))):
                    p[campo] = r
                    girados += 1
        f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # capa de cada loja na lista da página inicial (resumo.lojas[].f) → resumo.lojas[].fr
    rp = ROOT / "data" / "resumo.json"
    resumo = json.loads(rp.read_text(encoding="utf-8"))
    for l in resumo["lojas"]:
        l.pop("fr", None)
        if l.get("f") and (r := rot.get(fk(l["f"]))):
            l["fr"] = r
    rp.write_text(json.dumps(resumo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: {girados} fotos com rotação aplicada")


if __name__ == "__main__":
    main()
