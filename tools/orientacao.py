# -*- coding: utf-8 -*-
"""Detecta fotos deitadas/de ponta-cabeça (o app de campo salva sem EXIF de rotação).

Método: features de uma MobileNetV3 (ImageNet) + regressão logística treinada de forma
auto-supervisionada — fotos da própria base (quase todas em pé) giradas 0/90/180/270 viram
exemplos rotulados. Na predição, a classe diz quanto girar (CSS, sentido horário) para endireitar.

Uso:
  python tools\\orientacao.py treinar        (usa tools\\treino_orient.json → tools\\orient_clf.pt)
  python tools\\orientacao.py prever         (todas as fotos exibidas em cache → tools\\orient.json)

As bibliotecas ficam em C:\\dev\\.ml (caminho curto: o Windows desta máquina não aceita caminho longo).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\dev\.ml")
import timm  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fotos_cache import CACHE, baixa_todas, fk, urls_exibidas  # noqa: E402

ROOT = Path(__file__).resolve().parent
CLF = ROOT / "orient_clf.pt"
SAIDA = ROOT / "orient.json"  # probabilidades [0, 90, 180, 270] do classificador CLIP; p[0] baixo = suspeita de foto deitada
CLASSES = [0, 90, 180, 270]  # rotação CSS (horário) que endireita a foto
# PIL.rotate é anti-horário: girar a foto em pé por g graus => precisa de CSS g para voltar
GIROS_PIL = {0: 0, 90: 90, 180: 180, 270: -90}
torch.set_num_threads(max(1, torch.get_num_threads()))

_modelo = None


def modelo():
    global _modelo
    if _modelo is None:
        m = timm.create_model("mobilenetv3_large_100", pretrained=True, num_classes=0, global_pool="").eval()
        cfg = timm.data.resolve_data_config({}, model=m)
        _modelo = (m, timm.data.create_transform(**cfg))
    return _modelo


@torch.no_grad()
def features(imgs):
    m, tf = modelo()
    out = []
    for i in range(0, len(imgs), 64):
        # mapa espacial 3x3 (a média global perde "o que está em cima", que é o que importa aqui)
        fm = m.forward_features(torch.stack([tf(im) for im in imgs[i:i + 64]]))
        out.append(torch.nn.functional.adaptive_avg_pool2d(fm, 3).flatten(1))
    return torch.cat(out)


def abre(u):
    return Image.open(CACHE / f"{fk(u)}.jpg").convert("RGB")


def treinar():
    us = [u for u in json.load(open(ROOT / "treino_orient.json")) if (CACHE / f"{fk(u)}.jpg").exists()]
    cache = ROOT / "orient_feats.pt"  # features das 4 rotações, para retreinar sem recalcular
    if cache.exists():
        X, y, g = torch.load(cache)
    else:
        X, y, g = [], [], []
        for i in range(0, len(us), 200):
            lote = [abre(u) for u in us[i:i + 200]]
            for k, c in enumerate(CLASSES):
                X.append(features([im.rotate(GIROS_PIL[c], expand=True) for im in lote]))
                y += [k] * len(lote)
                g += list(range(i, i + len(lote)))
            print(f"  features {min(i + 200, len(us))}/{len(us)}")
        X, y, g = torch.cat(X), torch.tensor(y), torch.tensor(g)
        torch.save((X, y, g), cache)
    media, desvio = X.mean(0), X.std(0) + 1e-6
    Z = (X - media) / desvio
    teste = g % 5 == 0  # 20% das fotos (com as 4 rotações) ficam fora do treino
    lin = torch.nn.Linear(Z.shape[1], 4)
    opt = torch.optim.Adam(lin.parameters(), lr=1e-3, weight_decay=1e-4)
    for ep in range(60):
        perm = torch.randperm(int((~teste).sum()))
        Zt, yt = Z[~teste][perm], y[~teste][perm]
        for b in range(0, len(Zt), 256):
            opt.zero_grad()
            torch.nn.functional.cross_entropy(lin(Zt[b:b + 256]), yt[b:b + 256]).backward()
            opt.step()
    with torch.no_grad():
        acc = lambda m: (lin(Z[m]).argmax(1) == y[m]).float().mean().item()
        print(f"acurácia treino {acc(~teste):.3f} | fotos fora do treino {acc(teste):.3f}")
    torch.save({"w": lin.state_dict(), "media": media, "desvio": desvio}, CLF)


@torch.no_grad()
def probs(imgs):
    d = torch.load(CLF)
    lin = torch.nn.Linear(d["media"].shape[0], 4)
    lin.load_state_dict(d["w"])
    return lin((features(imgs) - d["media"]) / d["desvio"]).softmax(-1)


FINO = ROOT / "orient_fino.pt"
LADO_IN = 192


def _tf(treino):
    import torchvision.transforms as T
    norm = T.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
    if treino:
        return T.Compose([T.RandomResizedCrop(LADO_IN, scale=(0.5, 1.0), ratio=(0.75, 1.33)),
                          T.ColorJitter(0.2, 0.2, 0.2), T.ToTensor(), norm])
    return T.Compose([T.Resize((LADO_IN, LADO_IN)), T.ToTensor(), norm])


def treinar_fino(epocas=4):
    """ajuste fino da MobileNetV3 inteira na tarefa de prever a rotação"""
    us = [u for u in json.load(open(ROOT / "treino_orient.json")) if (CACHE / f"{fk(u)}.jpg").exists()]
    teste = us[::12]
    treino = [u for u in us if u not in set(teste)]
    m = timm.create_model("mobilenetv3_large_100", pretrained=True, num_classes=4)
    opt = torch.optim.AdamW(m.parameters(), lr=3e-4, weight_decay=1e-4)
    tf_t, tf_v = _tf(True), _tf(False)
    import random
    for ep in range(epocas):
        m.train()
        random.shuffle(treino)
        for b in range(0, len(treino), 32):
            lote, alvo = [], []
            for u in treino[b:b + 32]:
                k = random.randrange(4)
                lote.append(tf_t(abre(u).rotate(GIROS_PIL[CLASSES[k]], expand=True)))
                alvo.append(k)
            opt.zero_grad()
            torch.nn.functional.cross_entropy(m(torch.stack(lote)), torch.tensor(alvo), label_smoothing=0.1).backward()
            opt.step()
            if b % 1600 == 0:
                print(f"  época {ep + 1} {b}/{len(treino)}", flush=True)
        m.eval()
        ok = n = 0
        with torch.no_grad():
            for b in range(0, len(teste), 64):
                ims = [abre(u) for u in teste[b:b + 64]]
                for k, c in enumerate(CLASSES):
                    pred = m(torch.stack([tf_v(im.rotate(GIROS_PIL[c], expand=True)) for im in ims])).argmax(1)
                    ok += int((pred == k).sum()); n += len(ims)
        print(f"época {ep + 1}: acurácia em fotos fora do treino {ok / n:.3f}", flush=True)
        torch.save(m.state_dict(), FINO)


_fino = None


@torch.no_grad()
def probs_fino(imgs):
    global _fino
    if _fino is None:
        _fino = timm.create_model("mobilenetv3_large_100", pretrained=False, num_classes=4)
        _fino.load_state_dict(torch.load(FINO)); _fino.eval()
    tf = _tf(False)
    return torch.cat([_fino(torch.stack([tf(im) for im in imgs[i:i + 64]])).softmax(-1) for i in range(0, len(imgs), 64)])


CLIP = ROOT / "orient_clip.pt"
_clip = None


def clip_modelo():
    global _clip
    if _clip is None:
        import open_clip
        m, _, prep = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        _clip = (m.eval(), prep)
    return _clip


@torch.no_grad()
def clip_feat(imgs):
    m, prep = clip_modelo()
    out = [m.encode_image(torch.stack([prep(im) for im in imgs[i:i + 64]])) for i in range(0, len(imgs), 64)]
    return torch.nn.functional.normalize(torch.cat(out), dim=-1)


def treinar_clip(n=2400):
    """regressão logística sobre embeddings CLIP das fotos giradas 0/90/180/270"""
    us = [u for u in json.load(open(ROOT / "treino_orient.json")) if (CACHE / f"{fk(u)}.jpg").exists()][:n]
    cache = ROOT / "orient_clip_feats.pt"
    if cache.exists():
        X, y, g = torch.load(cache)
    else:
        X, y, g = [], [], []
        for i in range(0, len(us), 120):
            lote = [abre(u) for u in us[i:i + 120]]
            for k, c in enumerate(CLASSES):
                X.append(clip_feat([im.rotate(GIROS_PIL[c], expand=True) for im in lote]))
                y += [k] * len(lote); g += list(range(i, i + len(lote)))
            print(f"  clip {min(i + 120, len(us))}/{len(us)}", flush=True)
        X, y, g = torch.cat(X), torch.tensor(y), torch.tensor(g)
        torch.save((X, y, g), cache)
    teste = g % 5 == 0
    melhor = None
    for wd in (1e-5, 1e-4, 1e-3):
        lin = torch.nn.Linear(X.shape[1], 4)
        opt = torch.optim.Adam(lin.parameters(), lr=3e-3, weight_decay=wd)
        for ep in range(200):
            opt.zero_grad()
            torch.nn.functional.cross_entropy(lin(X[~teste] * 20), y[~teste]).backward()
            opt.step()
        with torch.no_grad():
            acc = (lin(X[teste] * 20).argmax(1) == y[teste]).float().mean().item()
        print(f"weight_decay {wd}: acurácia fora do treino {acc:.3f}", flush=True)
        if melhor is None or acc > melhor[0]:
            melhor = (acc, lin.state_dict())
    torch.save(melhor[1], CLIP)


@torch.no_grad()
def probs_clip(imgs):
    lin = torch.nn.Linear(512, 4)
    lin.load_state_dict(torch.load(CLIP))
    return lin(clip_feat(imgs) * 20).softmax(-1)


def prever():
    us = urls_exibidas()
    baixa_todas(us, 24)
    saida = json.loads(SAIDA.read_text()) if SAIDA.exists() else {}
    falta = [u for u in us if fk(u) not in saida and (CACHE / f"{fk(u)}.jpg").exists()]
    print(f"{len(us)} fotos exibidas, {len(falta)} a analisar")
    for i in range(0, len(falta), 256):
        lote = falta[i:i + 256]
        P = probs_clip([abre(u) for u in lote])
        for u, p in zip(lote, P.tolist()):
            saida[fk(u)] = [round(x, 3) for x in p]
        SAIDA.write_text(json.dumps(saida))
        print(f"  {min(i + 256, len(falta))}/{len(falta)}")


if __name__ == "__main__":
    {"treinar": treinar, "fino": treinar_fino, "clip": treinar_clip, "prever": prever}[sys.argv[1]]()
