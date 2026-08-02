from flask import Flask, jsonify, Response, redirect, request
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs, quote

app = Flask(__name__)

# Configurações de Identidade Real
REAL_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
BASE_URL = 'https://app.pobreflix2.site'
HOST_PLACEHOLDER = "MINHA_API_HOST_AQUI"

# CACHE DE LISTA (M3U)
cache_data = {
    "m3u": f"#EXTM3U\n# API EM INICIALIZAÇÃO... AGUARDE 30 SEGUNDOS E ATUALIZE.",
    "timestamp": 0,
    "status": "inicializando",
    "count": 0
}

# CACHE DE REPRODUÇÃO
stream_cache = {}
STREAM_CACHE_TIMEOUT = 15 # Segundos

# SESSÃO TURBO COM POOL DE CONEXÕES
session_speed = requests.Session()
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100)
session_speed.mount("https://", adapter)
session_speed.headers.update({'User-Agent': REAL_UA, 'Connection': 'keep-alive'})

@app.route('/')
def home():
    return jsonify({
        "status": cache_data["status"],
        "channels_found": cache_data["count"],
        "message": "API Ycine Master - Versão 46 HBO+ Edition",
        "last_update": time.ctime(cache_data["timestamp"]) if cache_data["timestamp"] > 0 else "Em progresso..."
    })

@app.route('/stream/<server_id>/<channel_id>.m3u8')
def get_stream(server_id, channel_id):
    cache_key = f"{server_id}_{channel_id}"
    now = time.time()

    if cache_key in stream_cache:
        data, ts = stream_cache[cache_key]
        if now - ts < STREAM_CACHE_TIMEOUT:
            return Response(data, mimetype='application/x-mpegURL', headers={'Access-Control-Allow-Origin': '*'})

    try:
        url_referencia = f"{BASE_URL}/canais/{channel_id}?thema=1&server={server_id}"
        target_m3u8 = f"https://speed.megafilmeshd9.com/midia/{server_id}/{channel_id}.m3u8"

        r = session_speed.get(target_m3u8, headers={'Referer': url_referencia, 'Origin': BASE_URL}, timeout=6)
        if r.status_code != 200: return f"Erro: {r.status_code}", 404

        video_base_url = target_m3u8.rsplit('/', 1)[0] + "/"
        new_playlist = [(video_base_url + line if (line and not line.startswith(('#', 'http'))) else line) for line in r.text.splitlines()]
        final_content = '\n'.join(new_playlist)

        stream_cache[cache_key] = (final_content, now)

        response = Response(final_content, mimetype='application/x-mpegURL')
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    except Exception as e:
        return str(e), 500

def fetch_page(url, serv_label, serv_id, category_name):
    canais = []
    try:
        r = session_speed.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('a', class_='iptv-cat-item')
        infantil = ["ADULT SWIM", "CARTOON", "KIDS", "GLOOB", "NICK", "RATIM", "TOONCAST", "ZOOMOO", "PREDIO AZUL", "RETRÔ"]

        for a in items:
            h4 = a.find('h4')
            nome = h4.get_text(strip=True) if h4 else ""
            if not nome or any(m in nome.lower() for m in ['sair', 'minha conta']): continue
            canal_id = a['href'].split('?')[0].rstrip('/').split('/')[-1]
            link = f"https://{HOST_PLACEHOLDER}/stream/{serv_id}/{canal_id}.m3u8"

            cat = category_name
            nome_up = nome.upper()
            if any(k in nome_up for k in infantil):
                cat = f"{serv_label} - Infantil"
            # LÓGICA HBO+ (Apenas HBO ou MAX, excluindo variantes não desejadas)
            elif ("HBO" in nome_up or "MAX" in nome_up) and not any(ex in nome_up for ex in ["TV MAX", "XY MAX"]):
                cat = f"{serv_label} - HBO+"

            canais.append({"nome": nome, "url": link, "logo": (a.find('img').get('src') or ""), "category": cat, "chave": f"{serv_id}-{canal_id}"})
    except: pass
    return canais

def get_real_categories(server_id):
    found = []
    try:
        r = session_speed.get(f"{BASE_URL}/canais/categorias/?thema=1&server={server_id}", timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            if '/canais/categorias/' in a['href']:
                name = a.get_text(strip=True)
                if name: found.append({"name": name, "url": a['href'] if a['href'].startswith('http') else f"{BASE_URL}{a['href']}"})
    except: pass
    return found

def generate_m3u(all_results):
    all_results.sort(key=lambda x: (x['category'].replace('Geral', 'ZZZ'), x['nome']))
    vistos = set()
    m3u = "#EXTM3U\n"
    count = 0
    for c in all_results:
        if c['chave'] not in vistos:
            vistos.add(c['chave'])
            m3u += f'#EXTINF:-1 tvg-logo="{c["logo"]}" group-title="{c["category"]}",{c["nome"]}\n{c["url"]}\n'
            count += 1
    return m3u, count

def background_update():
    global cache_data
    print("[LOG] Robô de canais iniciado...")
    while True:
        try:
            servidores = [{"id": "speed-1", "label": "S1", "max_p": 59}, {"id": "speed-2", "label": "S2", "max_p": 67}, {"id": "speed-3", "label": "S3", "max_p": 44}]
            total_results = []

            with ThreadPoolExecutor(max_workers=20) as executor:
                # ETAPA 1: Categorias
                cat_tasks = []
                for s in servidores:
                    for c in get_real_categories(s['id']):
                        cat_tasks.append(executor.submit(fetch_page, c['url'].split('?')[0]+"?thema=1&server="+s['id']+"&pagina=1", s['label'], s['id'], f"{s['label']} - {c['name']}"))

                for t in cat_tasks:
                    res = t.result()
                    if res: total_results.extend(res)

                if total_results:
                    m3u, count = generate_m3u(total_results)
                    cache_data.update({"m3u": m3u, "timestamp": time.time(), "status": "online (parcial)", "count": count})

                # ETAPA 2: Geral
                geral_tasks = []
                for s in servidores:
                    for p in range(1, s['max_p'] + 1):
                        geral_tasks.append(executor.submit(fetch_page, f"{BASE_URL}/canais/?thema=1&server={s['id']}&pagina={p}", s['label'], s['id'], f"{s['label']} - Geral"))

                for t in geral_tasks:
                    res = t.result()
                    if res: total_results.extend(res)

            if total_results:
                m3u, count = generate_m3u(total_results)
                cache_data.update({"m3u": m3u, "timestamp": time.time(), "status": "online", "count": count})
        except Exception as e:
            print(f"[ERROR] Falha no robô: {e}")
        time.sleep(3600)

# INICIALIZAÇÃO AUTOMÁTICA
threading.Thread(target=background_update, daemon=True).start()

@app.route('/canais')
def get_canais():
    current_host = request.host
    m3u_final = cache_data["m3u"].replace(HOST_PLACEHOLDER, current_host)
    return Response(m3u_final, mimetype='text/plain')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
