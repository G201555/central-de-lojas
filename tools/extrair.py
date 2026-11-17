# -*- coding: utf-8 -*-
"""Extrai do bi_cliente tudo que a Central de Lojas usa e grava em tools/raw.pkl.

Uso: python tools\\extrair.py
Depois: python tools\\montar.py
"""
import pickle
from pathlib import Path

import pandas as pd
import pyodbc

ROOT = Path(__file__).resolve().parent
CONN = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=tcp:SEU_SERVIDOR_SQL,1433;DATABASE=bi_cliente;"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes")

# Formulários exibidos na Central (contato loja/form 19 fica de fora: dados pessoais)
FORMS = (2, 3, 14, 15, 16, 21, 23, 27, 28, 31, 32, 34)

SQL = {
    "lojas": """
        SELECT COD_LOJA, NOM_FANTASIA, NOM_RAZAO_SOCIAL, DES_BANDEIRA, DES_REDE, DES_CANAL,
               END_LOGRADOURO, END_NUMERO, END_BAIRRO, END_CEP, DES_CIDADE, DES_UF,
               LATITUDE, LONGITUDE, STATUS_LOJA
        FROM bi_d_loja WHERE date_to = '2200-01-01'""",
    # visita válida = check-in feito, sem ausência, fora usuários de teste
    "visitas": """
        SELECT c.cod_pesquisa, c.data, c.cod_loja, c.cod_pessoa, p.NOM_PESSOA,
               c.permanencia_em_loja, c.hora_checkin
        FROM bi_d_coleta c
        LEFT JOIN bi_d_pessoa p ON p.COD_PESSOA = c.cod_pessoa AND p.date_to = '2200-01-01'
        WHERE c.date_to = '2200-01-01' AND c.realizado = 1 AND c.ausencia = 0
          AND c.realizado_checkin = 1 AND c.cod_pessoa NOT IN (1, 2)""",
    # regra PESQUISA DE CAMPO (out/2026): form 35/36 sem nenhum share > 0 => visita zerada
    "zeradas": """
        SELECT DISTINCT f.COD_PESQUISA FROM bi_f_formulario f
        WHERE f.COD_FORMULARIO IN (35, 36)
          AND NOT EXISTS (SELECT 1 FROM bi_f_share s
                          WHERE s.COD_PESQUISA = f.COD_PESQUISA AND s.QTD_SHARE_MARCA > 0)""",
    "forms": f"""
        SELECT f.COD_PESQUISA, f.COD_LOJA, f.DATA, f.COD_FORMULARIO, f.COD_PERGUNTA,
               f.COD_PESQUISA_FORMULARIO_RESPOSTAS AS ID_RESP,
               a.DES_ALTERNATIVA, r.DES_RESPOSTA, f.DES_RESPOSTA_QTD, f.QTD
        FROM bi_f_formulario f
        LEFT JOIN bi_d_formulario_alternativas a ON a.bi_id_formulario_alternativas = f.bi_id_formulario_alternativas
        LEFT JOIN bi_d_formulario_respostas r ON r.bi_id_formulario_respostas = f.bi_id_formulario_respostas
        WHERE f.COD_FORMULARIO IN {FORMS} AND f.COD_PESSOA NOT IN (1, 2)""",
    "share": """
        SELECT COD_PESQUISA, COD_LOJA, DATA, COD_LOCALIZACAO, COD_CATEGORIA,
               QTD_SHARE_CATEGORIA, COD_MARCA, QTD_SHARE_MARCA
        FROM bi_f_share WHERE COD_PESSOA NOT IN (1, 2) AND COD_CATEGORIA IN (2, 4)""",
    "produto": """
        SELECT COD_PESQUISA, COD_LOJA, DATA, COD_CATEGORIA, FL_PRESENTE, FL_RUPTURA, ESTOQUE
        FROM bi_f_produto WHERE COD_PESSOA NOT IN (1, 2) AND COD_CATEGORIA IN (2, 4)""",
    "ponto_extra": """
        SELECT pe.COD_PESQUISA, pe.COD_LOJA, pe.DATA, pe.COD_TIPO_PONTO_EXTRA, t.DES_TIPO_PONTO_EXTRA,
               pe.FL_EXISTE, pe.FL_RETORNO, ISNULL(f.FOTO, '') AS FOTO
        FROM bi_f_ponto_extra pe
        JOIN bi_d_tipo_ponto_extra t ON t.bi_id_tipo_ponto_extra = pe.bi_id_tipo_ponto_extra
        LEFT JOIN bi_d_ponto_extra_fotos f ON f.bi_id_ponto_extra_fotos = pe.bi_id_ponto_extra_fotos
        WHERE pe.COD_PESSOA NOT IN (1, 2)""",
    "fotos": """
        SELECT fe.COD_PESQUISA, fe.COD_LOJA, fe.DATA, fe.COD_PESQUISA_FOTO_EXECUCAO AS ID_EXEC,
               d.DES_TIPO_EXECUCAO, d.COD_TIPO_FOTO_EXECUCAO, d.FOTO
        FROM bi_f_foto_execucao fe
        JOIN bi_d_foto_execucao d ON d.bi_id_foto_execucao = fe.bi_id_foto_execucao
        WHERE fe.COD_PESSOA NOT IN (1, 2) AND d.FOTO IS NOT NULL""",
}


def main():
    raw = {}
    for nome, sql in SQL.items():
        # conexão nova por consulta (ver nota de tabelas temporárias do bi_cliente)
        with pyodbc.connect(CONN) as c:
            raw[nome] = pd.read_sql(sql, c)
        print(f"{nome:12s} {len(raw[nome]):>8,d} linhas")
    with open(ROOT / "raw.pkl", "wb") as fh:
        pickle.dump(raw, fh)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    main()
