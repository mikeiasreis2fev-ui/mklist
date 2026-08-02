from flask import Flask, jsonify, Response, redirect, request
import os
import requests
from bs4 import BeautifulSoup
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs, quote

app = Flask(__name__)

# Configurações de Identidade Real
REAL_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
BASE_URL = 'https://app.pobreflix2.site'

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "API Ycine Master - Versão 25 Identificação de Grupos"})

# ROTA DE REPRODUÇÃO - SISTEMA DE PROXY COM CORREÇÃO DE URL
@app.route('/stream')
def get_stream():
    url_base_canal = request.args.get('url')
    if not url_base_canal: return "URL ausente", 400

    try:
        parsed = urlparse(url_base_canal)
        path_parts = parsed.path.strip('/').split('/')
        qs = parse_qs(parsed.query)

        server_id = qs.get('server', [''])[0] or request.args.get('server', '')
        channel_id = path_parts[-1] if path_parts else ''

        if not (server_id and channel_id.isdigit()):
            return f"Erro: Servidor({server_id}) ou ID({channel_id}) inválido", 400

        target_m3u8 = f"https://speed.megafilmeshd9.com/midia/{server_id}/{channel_id}.m3u8"

        headers = {
            'User-Agent': REAL_UA,
            'Referer': url_base_canal,
            'Origin': BASE_URL
        }

        r = requests.get(target_m3u8, headers=headers, timeout=10)

        if r.status_code != 200:
            return f"Erro no sinal original: {r.status_code}", 404

        playlist_lines = r.text.splitlines()
        new_playlist = []
        video_base_url = target_m3u8.rsplit('/', 1)[0] + "/"

        for line in playlist_lines:
            if line and not line.startswith('#'):
                if not line.startswith('http'):
                    new_playlist.append(video_base_url + line)
                else:
                    new_playlist.append(line)
            else:
                new_playlist.append(line)

        return Response('\n'.join(new_playlist), mimetype='application/vnd.apple.mpegurl')

    except Exception as e:
        return f"Erro fatal: {str(e)}", 500

def fetch_page(session, url, serv_label, serv_id, host, category_name="Geral"):
    canais_da_pagina = []
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200: return []

        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('a', class_='iptv-cat-item')

        for a in items:
            href = a['href']
            h4 = a.find('h4')
            nome = h4.get_text(strip=True) if h4 else ""
            logo = ""
            img = a.find('img')
            if img: logo = img.get('src') or img.get('data-src') or ""

            if not nome or any(menu in nome.lower() for menu in ['sair', 'minha conta', 'editar']):
                continue

            canal_id = href.split('?')[0].rstrip('/').split('/')[-1]
            internal_url = f"{BASE_URL}/canais/{canal_id}?thema=1&server={serv_id}"
            link_proxy = f"https://{host}/stream?url={quote(internal_url)}&server={serv_id}"

            canais_da_pagina.append({
                "nome": nome, # Removido o (S1) do nome pois já estará no grupo
                "url": link_proxy,
                "logo": logo,
                "category": category_name, # O nome do grupo agora vem pronto (Ex: S1 - Globo)
                "chave": f"{serv_id}-{canal_id}"
            })
    except:
        pass
    return canais_da_pagina

def get_real_categories(session, server_id):
    found_categories = []
    try:
        url = f"{BASE_URL}/canais/categorias/?thema=1&server={server_id}"
        r = session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            if '/canais/categorias/' in a['href']:
                name = a.get_text(strip=True)
                href = a['href']
                full_url = href if href.startswith('http') else f"{BASE_URL}{href}"
                if name: found_categories.append({"name": name, "url": full_url})
    except:
        pass
    return found_categories

@app.route('/canais')
def get_canais():
    try:
        current_host = request.host
        session = requests.Session()
        session.headers.update({'User-Agent': REAL_UA})

        servidores = [
            {"id": "speed-1", "label": "S1", "max_p": 59},
            {"id": "speed-2", "label": "S2", "max_p": 67},
            {"id": "speed-3", "label": "S3", "max_p": 44}
        ]

        all_tasks = []
        with ThreadPoolExecutor(max_workers=15) as executor:
            for serv in servidores:
                # Páginas gerais com prefixo do servidor no grupo
                for page in range(1, serv['max_p'] + 1):
                    url = f"{BASE_URL}/canais/?thema=1&server={serv['id']}&pagina={page}"
                    # Identificando a categoria com o servidor
                    cat_label = f"{serv['label']} - Geral"
                    all_tasks.append(executor.submit(fetch_page, session, url, serv['label'], serv['id'], current_host, cat_label))

                # Categorias com prefixo do servidor no grupo
                cats = get_real_categories(session, serv['id'])
                for cat in cats:
                    base_cat = cat['url'].split('?')[0]
                    url_cat = f"{base_cat}?thema=1&server={serv['id']}&pagina=1"
                    # Identificando a categoria com o servidor (Ex: S1 - Premiere)
                    cat_label = f"{serv['label']} - {cat['name']}"
                    all_tasks.append(executor.submit(fetch_page, session, url_cat, serv['label'], serv['id'], current_host, cat_label))

        results = []
        for task in all_tasks:
            try:
                res = task.result()
                if res: results.extend(res)
            except: continue

        # Ordena para que os servidores fiquem agrupados (S1 primeiro, depois S2...)
        results.sort(key=lambda x: (x['category'], x['nome']))

        links_vistos = set()
        m3u_content = "#EXTM3U\n"
        count = 0
        for canal in results:
            if canal['chave'] not in links_vistos:
                links_vistos.add(canal['chave'])
                logo_attr = f' tvg-logo="{canal["logo"]}"' if canal["logo"] else ""
                # O category aqui já contém o prefixo "S1 - ", "S2 - ", etc.
                m3u_content += f'#EXTINF:-1{logo_attr} group-title="{canal["category"]}",{canal["nome"]}\n{canal["url"]}\n'
                count += 1

        m3u_content += f"\n# TOTAL CAPTURADO: {count}\n"
        return Response(m3u_content, mimetype='text/plain')
    except Exception as e:
        return f"Erro fatal: {str(e)}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
