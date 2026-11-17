# -*- coding: utf-8 -*-
"""Detecta fotos deitadas com o modelo de visão do Claude e grava tools\\rotacoes.json.

O app de campo salva parte das fotos deitada e sem EXIF; os modelos locais não acertaram (ver
tools\\orientacao.py). Aqui cada miniatura (cache_fotos, lado maior 320 px) vai para o Claude, que
responde quantos graus no sentido horário a foto precisa girar para ficar em pé.

Credencial: variável de ambiente ANTHROPIC_API_KEY (nunca no código nem em arquivo do projeto).

Uso:
  python tools\\orientacao_claude.py piloto [modelo]   fotos já rotuladas à mão → acerto e custo por foto
  python tools\\orientacao_claude.py lote [modelo]     envia as fotos ainda não analisadas (Batch API, 50% do preço)
  python tools\\orientacao_claude.py resultado         busca o lote e grava tools\\rotacoes.json
Depois: python tools\\fotos.py  e  python tools\\publicar.py
"""
import base64
import json
import os
import sys
from pathlib import Path

if not os.environ.get("ANTHROPIC_API_KEY") and sys.platform == "win32":
    # chave gravada com setx: vale para terminais novos; aqui é lida direto do registro do usuário
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
            os.environ["ANTHROPIC_API_KEY"] = winreg.QueryValueEx(reg, "ANTHROPIC_API_KEY")[0]
    except OSError:
        pass

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fotos_cache import CACHE, fk, urls_exibidas  # noqa: E402

TOOLS = Path(__file__).resolve().parent
ROTACOES = TOOLS / "rotacoes.json"       # {fk: 90|180|270} — só as que precisam girar
ANALISADAS = TOOLS / "analisadas.json"   # {fk: graus} — tudo que o Claude já respondeu (inclusive 0)
LOTES = TOOLS / "lotes_orientacao.json"  # ids dos lotes enviados
MODELO = "claude-opus-5-5"

PROMPT = (
    "Esta é uma foto tirada por um promotor dentro de uma loja de artigos esportivos (paredes de "
    "bolas, chuteiras, prateleiras, displays, vitrines, selfies de treinamento). Muitas fotos foram "
    "salvas deitadas ou de ponta-cabeça. Diga quantos graus a imagem precisa girar no sentido "
    "HORÁRIO para ficar em pé como a cena é na realidade: chão embaixo, teto e luminárias em cima, "
    "textos e logos legíveis, pessoas de pé, trilhos e prateleiras de exposição na horizontal, "
    "bolas e calçados apoiados ou pendurados pela gravidade. Responda 0 se já está em pé. Se a "
    "cena for ambígua (close de um produto, foto sem referência de cima/baixo), responda 0."
)
SCHEMA = {
    "type": "object",
    "properties": {"rotacao": {"type": "string", "enum": ["0", "90", "180", "270"]}},
    "required": ["rotacao"],
    "additionalProperties": False,
}


def params(k, modelo):
    dados = base64.standard_b64encode((CACHE / f"{k}.jpg").read_bytes()).decode("utf-8")
    return MessageCreateParamsNonStreaming(
        model=modelo,
        max_tokens=2048,  # o raciocínio conta dentro de max_tokens
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": dados}},
            {"type": "text", "text": PROMPT},
        ]}],
    )


def graus(msg):
    if msg.stop_reason != "end_turn":
        return None
    texto = next((b.text for b in msg.content if b.type == "text"), "")
    return int(json.loads(texto)["rotacao"])


def ler(p, padrao):
    return json.loads(p.read_text()) if p.exists() else padrao


def piloto(modelo):
    """fotos rotuladas à mão em tools\\rotulos_piloto.json: [[fk, deitada(bool|null)], ...]"""
    rotulos = json.loads((TOOLS / "rotulos_piloto.json").read_text())
    client = anthropic.Anthropic()
    ent = sai = 0
    acerto = total = fp = fn = 0
    saida = []
    for k, deitada in rotulos:
        msg = client.messages.create(**params(k, modelo))
        g = graus(msg)
        ent += msg.usage.input_tokens
        sai += msg.usage.output_tokens
        saida.append([k, deitada, g])
        if deitada is not None and g is not None:
            total += 1
            pred = g != 0
            acerto += pred == deitada
            fp += pred and not deitada
            fn += deitada and not pred
    precos = {"claude-opus-5-5": (4, 20), "claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2, 10)}
    pi, po = precos.get(modelo, (0, 0))
    custo_foto_lote = (ent * pi + sai * po) / 1e6 / len(rotulos) / 2
    print(f"{modelo}: acerto {acerto}/{total} | giraria foto certa: {fp} | deixaria deitada: {fn}")
    print(f"  tokens médios por foto: entrada {ent / len(rotulos):.0f}, saída {sai / len(rotulos):.0f}")
    print(f"  custo estimado no lote: US$ {custo_foto_lote:.5f}/foto → US$ {custo_foto_lote * 60846:.0f} para 60.846 fotos")
    (TOOLS / f"piloto_{modelo}.json").write_text(json.dumps(saida))


def lote(modelo):
    feitas = ler(ANALISADAS, {})
    ks = [fk(u) for u in urls_exibidas()]
    ks = [k for k in dict.fromkeys(ks) if k not in feitas and (CACHE / f"{k}.jpg").exists()]
    if not ks:
        print("nada novo para analisar")
        return
    client = anthropic.Anthropic()
    lotes = ler(LOTES, [])
    for i in range(0, len(ks), 20000):  # bem abaixo do limite de 256 MB por lote
        parte = ks[i:i + 20000]
        b = client.messages.batches.create(requests=[
            Request(custom_id=f"f{n}", params=params(k, modelo)) for n, k in enumerate(parte, i)])
        lotes.append({"id": b.id, "fks": {f"f{n}": k for n, k in enumerate(parte, i)}})
        LOTES.write_text(json.dumps(lotes))
        print(f"lote {b.id}: {len(parte)} fotos")


def resultado():
    client = anthropic.Anthropic()
    feitas, rot = ler(ANALISADAS, {}), ler(ROTACOES, {})
    pendentes = []
    for L in ler(LOTES, []):
        b = client.messages.batches.retrieve(L["id"])
        if b.processing_status != "ended":
            pendentes.append(L)
            print(f"lote {L['id']}: {b.processing_status} ({b.request_counts.succeeded} prontas)")
            continue
        for r in client.messages.batches.results(L["id"]):
            k = L["fks"][r.custom_id]
            if r.result.type == "succeeded" and (g := graus(r.result.message)) is not None:
                feitas[k] = g
                if g:
                    rot[k] = g
                else:
                    rot.pop(k, None)
        print(f"lote {L['id']}: concluído")
    ANALISADAS.write_text(json.dumps(feitas))
    ROTACOES.write_text(json.dumps(rot))
    LOTES.write_text(json.dumps(pendentes))
    print(f"{len(feitas)} fotos analisadas, {len(rot)} precisam girar")


if __name__ == "__main__":
    cmd = sys.argv[1]
    mod = sys.argv[2] if len(sys.argv) > 2 else MODELO
    {"piloto": lambda: piloto(mod), "lote": lambda: lote(mod), "resultado": resultado}[cmd]()
