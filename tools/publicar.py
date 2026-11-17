# -*- coding: utf-8 -*-
"""Publica a Central de Lojas no Firebase (projeto penalty-central-lojas).

1. Copia central.html para public/index.html (o site publicado pede login e lê do Firestore;
   a pasta data/ NÃO vai para o hosting).
2. Grava data/resumo.json em resumo/geral e cada data/lojas/<cod>.json em lojas/<cod>,
   entrando como um usuário que está na lista admin de firestore.rules.

Não faz o deploy do site: depois rode  firebase deploy --only hosting

Uso:  python tools\\publicar.py [email]
      python tools\\publicar.py --so-site     (só gera o public/index.html)
A senha é pedida no terminal e não aparece na tela nem fica em arquivo.
"""
import getpass
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_KEY = 'SUA_API_KEY'
PROJETO = 'penalty-central-lojas'
RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / 'data'
SITE = RAIZ / 'public' / 'index.html'
BASE = f'projects/{PROJETO}/databases/(default)/documents'
LIMITE_DOC = 1_000_000  # o Firestore recusa documento acima de 1 MiB
LOTE = 400              # commit aceita até 500 gravações


def post(url, corpo, token=None):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json'})
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        sys.exit(f'ERRO {e.code} em {url.split("?")[0]}: {e.read().decode("utf-8", "replace")[:400]}')


def get(url, token):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))


def lojas_publicadas(token):
    """códigos das lojas que já estão no Firestore"""
    cods, pagina = set(), ''
    while True:
        r = get(f'https://firestore.googleapis.com/v1/{BASE}/lojas?pageSize=1000&mask.fieldPaths=__name__'
                f'{"&pageToken=" + pagina if pagina else ""}', token)
        cods |= {d['name'].rsplit('/', 1)[1] for d in r.get('documents', [])}
        pagina = r.get('nextPageToken')
        if not pagina:
            return cods


def gravacao(caminho, texto):
    if len(texto.encode('utf-8')) > LIMITE_DOC:
        sys.exit(f'ERRO: {caminho} com {len(texto.encode("utf-8"))} bytes, acima do limite do Firestore')
    return {'update': {'name': f'{BASE}/{caminho}', 'fields': {'json': {'stringValue': texto}}}}


def main():
    SITE.parent.mkdir(exist_ok=True)
    shutil.copyfile(RAIZ / 'central.html', SITE)
    print(f'OK: {SITE.relative_to(RAIZ)} gerado.')
    if '--so-site' in sys.argv:
        return

    resumo = (DADOS / 'resumo.json').read_text(encoding='utf-8')
    lojas = sorted((DADOS / 'lojas').glob('*.json'), key=lambda p: int(p.stem))
    if not lojas:
        sys.exit('ERRO: data/lojas vazio. Rode antes  python tools\\extrair.py  e  python tools\\montar.py')
    writes = [gravacao('resumo/geral', resumo)]
    writes += [gravacao(f'lojas/{p.stem}', p.read_text(encoding='utf-8')) for p in lojas]
    # lista da tela "Revisar fotos" (tools\lista_revisao.py); as partes já enviadas não mudam
    writes += [gravacao(f'revisao/{p.stem}', p.read_text(encoding='utf-8'))
               for p in sorted((DADOS / 'revisao').glob('*.json'))]

    email = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else input('E-mail: ').strip()
    senha = getpass.getpass('Senha (não aparece): ')
    login = post(f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}',
                 {'email': email, 'password': senha, 'returnSecureToken': True})
    print('Login OK como', login['email'])

    # lojas que saíram da base (ex.: sem visita no período) são apagadas, para o link antigo não abrir
    sobra = lojas_publicadas(login['idToken']) - {p.stem for p in lojas}
    writes += [{'delete': f'{BASE}/lojas/{c}'} for c in sorted(sobra, key=int)]

    url = f'https://firestore.googleapis.com/v1/{BASE}:commit'
    for i in range(0, len(writes), LOTE):
        post(url, {'writes': writes[i:i + LOTE]}, token=login['idToken'])
        print(f'  {min(i + LOTE, len(writes))}/{len(writes)} documentos')
    r = json.loads(resumo)
    if sobra:
        print(f'  {len(sobra)} lojas fora da base apagadas')
    print(f'OK: {len(lojas)} lojas publicadas (visitas até {r["ultima_visita"]}, gerado em {r["atualizado"]}).')


if __name__ == '__main__':
    main()
