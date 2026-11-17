# -*- coding: utf-8 -*-
"""Monta os JSON da Central de Lojas a partir de tools/raw.pkl.

Saída:
  data/resumo.json        KPIs do programa + lista de lojas (mapa/busca)
  data/lojas/<COD>.json   overview de cada loja

Regras:
  - visita = bi_d_coleta com check-in, sem ausência, fora usuários de teste (1, 2)
  - visitas de PESQUISA DE CAMPO zeradas (form 35/36 sem share > 0) contam como visita,
    mas não entram em share/estoque/execução
  - share Penalty = marcas 2 (PENALTY) + 8 (LINHA) + 9 (FDL) / total das marcas, somando
    vitrine + ponto extra + ponto natural; bola = categoria 2, calçados = categoria 4
  - quando a mesma pesquisa tem mais de uma resposta, vale a última (id da resposta)
"""
import json
import pickle
import re
import shutil
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"
PENALTY = {2, 8, 9}
MARCAS = {2: "Penalty", 8: "Penalty", 9: "Penalty", 3: "Adidas", 4: "Nike", 5: "Umbro",
          6: "Topper", 10: "Joma", 11: "Puma", 12: "Mizuno", 7: "Outras", 999: "Outras"}
TIPOS_PE_TESTE = {1, 2, 3}
MAX_PARES = 8
MAX_GALERIA = 12
# só entra o que foi coletado a partir desta data (pedido do usuário, 20/10/2026: "a partir deste ano")
DESDE = "2026-01-01"

# (form, pergunta) das fotos que entram na galeria
FOTO_FORMS = {
    (3, 19): "Execução de bola", (3, 24): "Bolas calibradas", (3, 18): "Bolas limpas",
    (14, 19): "Execução de calçados", (14, 27): "Atacador", (14, 31): "Enchimento",
    (2, 68): "Treinamento", (16, 39): "Compre e Ganhe", (28, 36): "Volta às Aulas",
    (27, 12): "Vitrine", (21, 58): "Display / boleiro", (15, 36): "Concorrência",
}


def https(u):
    u = (u or "").strip()
    return "https://" + u[7:] if u.startswith("http://") else u


def num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def limpa(s):
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    s = s.replace("&amp;", "&").strip()
    return "" if s.upper() in ("NULL", "NAN", "NONE", "-") else s


def titulo(s):
    s = limpa(s)
    minus = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(w.lower() if w.lower() in minus and i else w.capitalize()
                    for i, w in enumerate(s.split()))


def nome_curto(n):
    p = titulo(n).split()
    p = [w for w in p if w.lower() not in ("de", "da", "do", "das", "dos", "e")]
    return " ".join(p[:1] + p[-1:]) if len(p) > 1 else " ".join(p)


def minutos(hhmm):
    m = re.match(r"^(\d+):(\d{2})$", str(hhmm or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def coord(v):
    try:
        f = float(str(v).replace(",", "."))
        return round(f, 5) if f != 0 else None
    except ValueError:
        return None


def main():
    raw = pickle.load(open(ROOT / "tools" / "raw.pkl", "rb"))
    for nome, col in (("visitas", "data"), ("forms", "DATA"), ("share", "DATA"), ("produto", "DATA"),
                      ("ponto_extra", "DATA"), ("fotos", "DATA")):
        df = raw[nome]
        raw[nome] = df[df[col].astype(str).str[:10] >= DESDE]
    zeradas = set(raw["zeradas"].COD_PESQUISA)

    vis = raw["visitas"].copy()
    vis["data"] = vis["data"].astype(str).str[:10]
    vis = vis.sort_values(["data", "hora_checkin", "cod_pesquisa"])
    vis["min"] = vis.permanencia_em_loja.map(minutos)
    # permanências absurdas (> 10h) não entram na soma de horas
    vis.loc[vis["min"] > 600, "min"] = None

    # ---------- formulários ----------
    f = raw["forms"].copy()
    f = f[~f.COD_PESQUISA.isin(zeradas)]
    f["DATA"] = f["DATA"].astype(str).str[:10]
    f["txt"] = f.DES_ALTERNATIVA.fillna(f.DES_RESPOSTA).map(limpa)
    f = f.sort_values("ID_RESP")

    def resp(fo, pe):
        """última resposta por pesquisa"""
        g = f[(f.COD_FORMULARIO == fo) & (f.COD_PERGUNTA == pe)]
        return g.groupby("COD_PESQUISA").txt.last()

    def resp_multi(fo, pe):
        g = f[(f.COD_FORMULARIO == fo) & (f.COD_PERGUNTA == pe)]
        return g.groupby("COD_PESQUISA").txt.agg(lambda s: sorted(set(x for x in s if x)))

    acao = pd.DataFrame({
        "treinou": resp(2, 3) == "SIM",
        "pessoas": resp(2, 4).map(num),
        "assunto": resp_multi(2, 5),
        "tipo_trein": resp(2, 40),
        "bola_exec": resp(3, 16) == "SIM",
        "calibradas": resp(3, 23).map(num),
        "limpas": resp(3, 70).map(num),
        "calc_exec": resp(14, 33) == "SIM",
        "atacador": resp(14, 26).map(num),
        "enchimento": resp(14, 30).map(num),
        "cg_ativo": resp(16, 37) == "SIM",
        "brindes": resp(16, 38).map(num),
        "va_brindes": resp(28, 38).map(num),
        "conc": resp(15, 34) == "SIM",
        "conc_tipo": resp_multi(15, 35),
    })
    for c in ("pessoas", "calibradas", "limpas", "atacador", "enchimento", "brindes", "va_brindes"):
        acao[c] = acao[c].fillna(0).clip(upper=500)  # digitação absurda não infla o total
    for c in ("treinou", "bola_exec", "calc_exec", "cg_ativo", "conc"):
        acao[c] = acao[c].fillna(False).astype(bool)
    acao.loc[~acao.treinou, "pessoas"] = 0
    acao["brindes"] = acao.brindes + acao.va_brindes

    # perfil da loja: última resposta válida por loja
    def perfil(fo, pe, ignora=("LOJA JA FOI CONFERIDA",)):
        g = f[(f.COD_FORMULARIO == fo) & (f.COD_PERGUNTA == pe) & ~f.txt.isin(ignora) & (f.txt != "")]
        g = g.sort_values(["DATA", "ID_RESP"])
        return g.groupby("COD_LOJA").txt.last()

    shopping, shop_nome = perfil(31, 80), perfil(31, 81)
    tamanho, segmento = perfil(32, 82), perfil(23, 63)
    vend = perfil(34, 91)
    vitrine = perfil(27, 75)

    # fotos de formulário (galeria)
    ff = f[[k in FOTO_FORMS for k in zip(f.COD_FORMULARIO, f.COD_PERGUNTA)]].copy()
    ff = ff[ff.DES_RESPOSTA.astype(str).str.startswith("http")]
    ff["rotulo"] = [FOTO_FORMS[k] for k in zip(ff.COD_FORMULARIO, ff.COD_PERGUNTA)]
    ff["url"] = ff.DES_RESPOSTA.map(https)

    # ---------- share ----------
    sh = raw["share"]
    sh = sh[~sh.COD_PESQUISA.isin(zeradas) & (sh.COD_MARCA != 1)].copy()
    sh["pen"] = sh.COD_MARCA.isin(PENALTY) * sh.QTD_SHARE_MARCA
    agg = sh.groupby(["COD_PESQUISA", "COD_CATEGORIA"]).agg(pen=("pen", "sum"), tot=("QTD_SHARE_MARCA", "sum"))
    agg = agg[agg.tot > 0]
    agg["pct"] = agg.pen / agg.tot
    share_vis = agg.pct.unstack()  # colunas 2 (bola), 4 (calçados)
    sh["marca"] = sh.COD_MARCA.map(MARCAS).fillna("Outras")
    marcas_vis = sh.groupby(["COD_PESQUISA", "COD_CATEGORIA", "marca"]).QTD_SHARE_MARCA.sum()

    # ---------- estoque ----------
    pr = raw["produto"]
    pr = pr[~pr.COD_PESQUISA.isin(zeradas)]
    est = pr.groupby(["COD_PESQUISA", "COD_CATEGORIA"]).ESTOQUE.sum().unstack()

    # ---------- ponto extra ----------
    pe = raw["ponto_extra"]
    pe = pe[~pe.COD_PESQUISA.isin(zeradas) & (pe.FL_EXISTE == 1) & ~pe.COD_TIPO_PONTO_EXTRA.isin(TIPOS_PE_TESTE)].copy()
    pe["tipo"] = pe.DES_TIPO_PONTO_EXTRA.map(titulo)
    pe_vis = pe.groupby("COD_PESQUISA").tipo.agg(lambda s: sorted(set(s)))
    pe["url"] = pe.FOTO.map(https)
    pe["DATA"] = pe.DATA.astype(str).str[:10]

    # ---------- fotos antes/depois ----------
    fo = raw["fotos"].copy()
    fo = fo[fo.FOTO.astype(str).str.startswith("http")]
    fo["DATA"] = fo.DATA.astype(str).str[:10]
    fo["url"] = fo.FOTO.map(https)
    fo["tipo"] = fo.DES_TIPO_EXECUCAO.map(lambda s: {
        "EXECUÇÃO VITRINE": "Vitrine", "EXECUÇÃO BOLA": "Bola",
        "EXECUÇÃO CALÇADO": "Calçados", "EXECUÇÃO CALÇADOS": "Calçados"}.get(s, "Execução"))
    pares = []
    for (idx, loja, data, tipo), g in fo.groupby(["ID_EXEC", "COD_LOJA", "DATA", "tipo"]):
        a = g[g.COD_TIPO_FOTO_EXECUCAO == 1].url.tolist()
        d = g[g.COD_TIPO_FOTO_EXECUCAO == 2].url.tolist()
        if a and d:
            pares.append({"loja": loja, "data": data, "tipo": tipo, "antes": a[0], "depois": d[0], "id": idx})
    pares = pd.DataFrame(pares)

    # ---------- por loja ----------
    lojas = raw["lojas"].drop_duplicates("COD_LOJA", keep="last").set_index("COD_LOJA")
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "lojas").mkdir(parents=True)

    lista, mensal = [], {}
    tot = dict(visitas=0, minutos=0, pessoas=0, treinamentos=0, calibradas=0, limpas=0,
               atacador=0, enchimento=0, brindes=0, pe=0, fotos=0)

    for cod, gv in vis.groupby("cod_loja"):
        if cod not in lojas.index:
            continue
        L = lojas.loc[cod]
        timeline, serie = [], []
        T = dict(visitas=0, minutos=0, pessoas=0, treinamentos=0, calibradas=0, limpas=0,
                 atacador=0, enchimento=0, brindes=0, cg_visitas=0, conc=0)
        for _, v in gv.iterrows():
            p = v.cod_pesquisa
            a = acao.loc[p] if p in acao.index else None
            pts = pe_vis.get(p, [])
            sb = share_vis.at[p, 2] if p in share_vis.index and 2 in share_vis else None
            sc = share_vis.at[p, 4] if p in share_vis.index and 4 in share_vis else None
            sb = None if pd.isna(sb) else round(float(sb), 4)
            sc = None if pd.isna(sc) else round(float(sc), 4)
            eb = est.at[p, 2] if p in est.index and 2 in est else None
            ec = est.at[p, 4] if p in est.index and 4 in est else None
            item = {"d": v.data, "c": nome_curto(v.NOM_PESSOA), "m": None if pd.isna(v["min"]) else int(v["min"])}
            if p in zeradas:
                item["pc"] = 1  # pesquisa de campo
            if a is not None:
                if a.treinou:
                    item["tr"] = int(a.pessoas)
                    if a.assunto:
                        item["ta"] = a.assunto
                for k, c in (("cb", "calibradas"), ("lb", "limpas"), ("at", "atacador"), ("en", "enchimento"), ("br", "brindes")):
                    if a[c]:
                        item[k] = int(a[c])
                if a.bola_exec:
                    item["eb"] = 1
                if a.calc_exec:
                    item["ec"] = 1
                if a.conc:
                    item["co"] = a.conc_tipo or ["Ação"]
                T["pessoas"] += a.pessoas
                T["treinamentos"] += int(a.treinou)
                T["calibradas"] += a.calibradas
                T["limpas"] += a.limpas
                T["atacador"] += a.atacador
                T["enchimento"] += a.enchimento
                T["brindes"] += a.brindes
                T["cg_visitas"] += int(a.cg_ativo)
                T["conc"] += int(a.conc)
            if pts:
                item["pe"] = pts
            if sb is not None:
                item["sb"] = sb
            if sc is not None:
                item["sc"] = sc
            if eb is not None and not pd.isna(eb):
                item["qb"] = int(eb)
            if ec is not None and not pd.isna(ec):
                item["qc"] = int(ec)
            timeline.append(item)
            T["visitas"] += 1
            T["minutos"] += item["m"] or 0

            mes = v.data[:7]
            M = mensal.setdefault(mes, dict(visitas=0, pessoas=0, sb=[], sc=[], pe=0, lojas=set()))
            M["visitas"] += 1
            M["lojas"].add(int(cod))
            M["pessoas"] += int(item.get("tr", 0))
            M["pe"] += len(pts)
            if sb is not None:
                M["sb"].append(sb)
            if sc is not None:
                M["sc"].append(sc)

        # antes × depois: primeira e última visita com medição
        def extremos(chave):
            vals = [(t["d"], t[chave]) for t in timeline if chave in t]
            return (vals[0], vals[-1]) if vals else (None, None)

        def marcas_de(chave, cat):
            ps = [p for p, t in zip(gv.cod_pesquisa, timeline) if chave in t]
            out = []
            for p in (ps[:1] + ps[-1:]) if ps else []:
                m = marcas_vis.loc[p, cat] if (p, cat) in marcas_vis.index else pd.Series(dtype=float)
                tot_ = m.sum()
                out.append({k: round(float(x / tot_), 4) for k, x in m.items() if x > 0} if tot_ else {})
            return out

        n_pe = [(t["d"], len(t.get("pe", []))) for t in timeline if "pc" not in t]
        antes_depois = {
            "sb": extremos("sb"), "sc": extremos("sc"),
            "qb": extremos("qb"), "qc": extremos("qc"),
            "pe": (n_pe[0], n_pe[-1]) if n_pe else (None, None),
            "mb": marcas_de("sb", 2), "mc": marcas_de("sc", 4),
        }

        pe_loja = pe[pe.COD_LOJA == cod].sort_values("DATA")
        pe_atual = timeline and next((t.get("pe", []) for t in reversed(timeline) if "pc" not in t), [])
        conquistados = sorted(set(pe_loja.tipo))

        pl = pares[pares.loja == cod].sort_values(["data", "id"], ascending=False).head(MAX_PARES) if len(pares) else []
        gal = pd.concat([
            ff[ff.COD_LOJA == cod][["DATA", "rotulo", "url"]],
            pe_loja[pe_loja.url.str.startswith("http")].assign(rotulo=lambda x: "Ponto extra · " + x.tipo)[["DATA", "rotulo", "url"]],
        ]).drop_duplicates("url").sort_values("DATA", ascending=False)
        n_fotos = len(gal) + 2 * len(pares[pares.loja == cod]) if len(pares) else len(gal)

        # logradouro às vezes vem com o endereço inteiro ("Rua X S/n, Cidade - Região, CEP, Brasil")
        rua = titulo(limpa(L.END_LOGRADOURO).split(",")[0])
        numero = limpa(L.END_NUMERO)
        end = ", ".join(x for x in (rua, numero) if x and x.upper() not in ("S/N", "0"))
        nome = re.sub(r"^\d+\s*-\s*", "", titulo(L.NOM_FANTASIA))
        loja = {
            "cod": int(cod), "nome": nome, "razao": titulo(L.NOM_RAZAO_SOCIAL),
            "bandeira": titulo(L.DES_BANDEIRA), "rede": titulo(L.DES_REDE), "canal": titulo(L.DES_CANAL),
            "endereco": end, "bairro": titulo(L.END_BAIRRO), "cidade": titulo(L.DES_CIDADE), "uf": limpa(L.DES_UF),
            "cep": limpa(L.END_CEP), "lat": coord(L.LATITUDE), "lng": coord(L.LONGITUDE),
            "segmento": titulo(segmento.get(cod, "")), "tamanho": titulo(tamanho.get(cod, "")),
            "shopping": (titulo(shop_nome.get(cod, "")) or "Sim") if shopping.get(cod) == "SIM" else ("Rua" if shopping.get(cod) == "NÃO" else ""),
            "vendedores": int(num(vend.get(cod))) if cod in vend.index else None,
            "vitrine": {"SIM": "Sim", "NÃO": "Não"}.get(vitrine.get(cod, ""), ""),
            "totais": {k: int(round(v)) for k, v in T.items()},
            "antes_depois": antes_depois,
            "pe_atual": pe_atual or [], "pe_conquistados": conquistados,
            "pares": [{"d": r.data, "t": r.tipo, "a": r.antes, "b": r.depois} for r in pl.itertuples()] if len(pl) else [],
            "galeria": [{"d": r.DATA, "t": r.rotulo, "u": r.url} for r in gal.head(MAX_GALERIA).itertuples()],
            "n_fotos": int(n_fotos),
            "timeline": timeline[::-1],
        }
        (OUT / "lojas" / f"{int(cod)}.json").write_text(json.dumps(loja, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        ult = timeline[-1]
        sb_u = antes_depois["sb"][1][1] if antes_depois["sb"][1] else None
        sc_u = antes_depois["sc"][1][1] if antes_depois["sc"][1] else None
        lista.append({
            "cod": int(cod), "nome": loja["nome"], "bandeira": loja["bandeira"], "rede": loja["rede"],
            "cidade": loja["cidade"], "uf": loja["uf"], "lat": loja["lat"], "lng": loja["lng"],
            "v": T["visitas"], "pv": timeline[0]["d"], "uv": ult["d"],
            "sb": sb_u, "sc": sc_u, "pe": len(loja["pe_atual"]), "tr": int(T["pessoas"]),
            # primeira medição do período, para a seta de tendência na lista
            "sb0": antes_depois["sb"][0][1] if antes_depois["sb"][0] else None,
            "sc0": antes_depois["sc"][0][1] if antes_depois["sc"][0] else None,
            # capa da loja na lista: o "depois" da execução mais recente (ou a foto mais recente)
            "f": loja["pares"][0]["b"] if loja["pares"] else (loja["galeria"][0]["u"] if loja["galeria"] else None),
            "bairro": loja["bairro"],
        })
        for k in ("visitas", "minutos", "pessoas", "treinamentos", "calibradas", "limpas", "atacador", "enchimento", "brindes"):
            tot[k] += T[k]
        tot["pe"] += len(conquistados)
        tot["fotos"] += loja["n_fotos"]

    media = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    meses = [{"m": m, "visitas": d["visitas"], "lojas": len(d["lojas"]), "pessoas": d["pessoas"],
              "sb": media(d["sb"]), "sc": media(d["sc"]), "pe": d["pe"]}
             for m, d in sorted(mensal.items())]
    resumo = {
        "atualizado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ultima_visita": vis.data.max(), "primeira_visita": vis.data.min(),
        "totais": {**{k: int(round(v)) for k, v in tot.items()}, "lojas": len(lista),
                   "ufs": len({l["uf"] for l in lista if l["uf"]}),
                   "cidades": len({(l["uf"], l["cidade"]) for l in lista})},
        "meses": meses,
        "lojas": lista,
    }
    (OUT / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tam = sum(p.stat().st_size for p in (OUT / "lojas").glob("*.json"))
    print(f"{len(lista)} lojas | resumo {(OUT / 'resumo.json').stat().st_size / 1024:.0f} KB | lojas {tam / 1e6:.1f} MB")
    print(json.dumps(resumo["totais"], ensure_ascii=False))


if __name__ == "__main__":
    main()
