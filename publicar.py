#!/usr/bin/env python3
"""Publica no Instagram do Pé no Freio os posts da fila (imagem, Reels ou carrossel) (fila.json) quando chega a hora.

Roda no GitHub Actions duas vezes por hora (o GitHub atrasa ou pula rodadas agendadas; a que cair até 4 h antes de um
post espera o horário). Publica no máximo um post por execução.
MODO=teste: prepara o contêiner do próximo post pendente e confere se a Meta aceitou a imagem, SEM publicar.

Lembretes: item com "lembrete" (texto) não publica nada; manda o texto ao fundador pelo Telegram na hora marcada,
com o vídeo de "video" (em imagens/) e o "texto_app" numa mensagem separada, pronta para copiar. O robô também avisa
no Telegram quando publica ou falha e quando aparece página nova no sitemap do site (site-visto.json guarda as já vistas).

Segredos (GitHub Actions): INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_USER_ID; TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
(opcionais: sem eles, os avisos só vão para o log). Os tokens nunca são impressos.
"""
import datetime, json, os, sys, time, urllib.error, urllib.parse, urllib.request

VERSAO = "v27.0"
TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
UID = os.environ["INSTAGRAM_USER_ID"]
REPO = os.environ.get("GITHUB_REPOSITORY", "fabriciosribeiro/penofreio-midia")
MODO = os.environ.get("MODO", "publicar")
ATRASO_MAXIMO = datetime.timedelta(hours=12)  # passou disso, não publica sozinho: avisa
ESPERA_MAXIMA = datetime.timedelta(hours=5, minutes=45)  # o GitHub roda o agendamento a cada 4 a 8 h: a rodada que cair antes espera o horário
AQUI = os.path.dirname(os.path.abspath(__file__))
FILA = os.path.join(AQUI, "fila.json")
SITE_VISTO = os.path.join(AQUI, "site-visto.json")
SITEMAP = "https://penofreio.com.br/sitemap.xml"


def chamar(metodo, caminho, **params):
    params["access_token"] = TOKEN
    url = f"https://graph.facebook.com/{VERSAO}/{caminho}"
    dados = urllib.parse.urlencode(params)
    req = (urllib.request.Request(url, data=dados.encode(), method="POST") if metodo == "POST"
           else urllib.request.Request(url + "?" + dados))
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=60))
        resp.pop("paging", None)  # links de paginação levam o token
        return resp
    except urllib.error.HTTPError as e:
        erro = json.loads(e.read().decode() or "{}").get("error", {})
        return {"erro": e.code, "mensagem": erro.get("message"), "detalhe": erro.get("error_user_msg")}


def telegram(metodo, **params):
    tk, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tk and chat):
        print(f"(sem Telegram configurado) {params.get('text') or params.get('caption')}")
        return False
    req = urllib.request.Request(f"https://api.telegram.org/bot{tk}/{metodo}",
                                 data=urllib.parse.urlencode({"chat_id": chat, **params}).encode())
    try:
        return json.load(urllib.request.urlopen(req, timeout=60)).get("ok", False)
    except urllib.error.URLError as e:  # sem o token na mensagem
        print(f"Telegram falhou em {metodo}: {getattr(e, 'code', '')} {getattr(e, 'reason', '')}")
        return False


def avisar(texto):
    telegram("sendMessage", text=texto, disable_web_page_preview="true")


def enviar_lembrete(item):
    ok = telegram("sendMessage", text=item["lembrete"], disable_web_page_preview="true")
    if ok and item.get("video"):
        ok = telegram("sendVideo", video=f"https://raw.githubusercontent.com/{REPO}/main/imagens/{item['video']}",
                      caption="Vídeo para publicar pelo app (sem música).")
    if ok and item.get("texto_app"):
        ok = telegram("sendMessage", text=item["texto_app"])
    return ok


def conferir_site():
    """Avisa pelo Telegram cada página nova no sitemap do site (artigo publicado)."""
    import re
    try:
        req = urllib.request.Request(SITEMAP, headers={"User-Agent": "Mozilla/5.0 (penofreio-robo)"})
        xml = urllib.request.urlopen(req, timeout=30).read().decode()
    except urllib.error.URLError as e:
        print(f"Sitemap indisponível: {e}")
        return
    agora = set(re.findall(r"<loc>([^<]+)</loc>", xml))
    visto = set(json.load(open(SITE_VISTO, encoding="utf-8"))) if os.path.exists(SITE_VISTO) else set()
    novas = sorted(agora - visto)
    if not novas:
        return
    if visto:  # na primeira vez só grava a lista
        for url in novas:
            avisar(f"Pé no Freio: página nova no site. {url}")
    json.dump(sorted(visto | agora), open(SITE_VISTO, "w", encoding="utf-8"), indent=1)
    open(SITE_VISTO, "a").write("\n")


def enviar_lembretes(fila, agora):
    """Lembretes vencidos (até 12 h de atraso) vão pelo Telegram, uma vez cada."""
    for lem in fila:
        if not lem.get("lembrete") or lem.get("enviado"):
            continue
        quando = datetime.datetime.fromisoformat(lem["quando"])
        if quando <= agora < quando + ATRASO_MAXIMO and enviar_lembrete(lem):
            lem["enviado"] = agora.isoformat(timespec="minutes")
            print(f"Lembrete enviado: {lem['lembrete'][:60]}")


def esperar(cid, vezes):
    st = {}
    for _ in range(vezes):
        st = chamar("GET", cid, fields="status_code")
        if st.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
            break
        time.sleep(5)
    return st.get("status_code")


def preparar_carrossel(item):
    """Carrossel: um contêiner por imagem (com texto alternativo) e o contêiner pai com a legenda."""
    pasta = f"https://raw.githubusercontent.com/{REPO}/main/imagens/"
    alts = item.get("alts") or []
    filhos = []
    for k, img in enumerate(item["carrossel"]):
        extras = {"alt_text": alts[k]} if k < len(alts) and alts[k] else {}
        r = chamar("POST", f"{UID}/media", image_url=pasta + img, is_carousel_item="true", **extras)
        if "id" not in r and extras:
            r = chamar("POST", f"{UID}/media", image_url=pasta + img, is_carousel_item="true")
        if "id" not in r:
            sys.exit(f"Falha na tela {img} do carrossel: {r}")
        if esperar(r["id"], 24) != "FINISHED":
            sys.exit(f"A Meta não aceitou a tela {img}.")
        filhos.append(r["id"])
    extras = {"is_ai_generated": "true"} if item.get("ia") else {}
    r = chamar("POST", f"{UID}/media", media_type="CAROUSEL", children=",".join(filhos), caption=item["legenda"], **extras)
    if "id" not in r and extras:
        r = chamar("POST", f"{UID}/media", media_type="CAROUSEL", children=",".join(filhos), caption=item["legenda"])
    if "id" not in r:
        sys.exit(f"Falha ao criar o carrossel {item['imagem']}: {r}")
    return r["id"], esperar(r["id"], 24)


def preparar(item):
    if item.get("carrossel"):
        return preparar_carrossel(item)
    arquivo = f"https://raw.githubusercontent.com/{REPO}/main/imagens/{item['imagem']}"
    if item.get("video"):  # meme em Reels: o mp4 fica em imagens/ junto do jpg
        base = dict(media_type="REELS", video_url=arquivo.rsplit("/", 1)[0] + "/" + item["video"],
                    caption=item["legenda"], share_to_feed="true")
        if item.get("capa"):  # capa própria do Reels (jpg em imagens/)
            base["cover_url"] = arquivo.rsplit("/", 1)[0] + "/" + item["capa"]
    else:
        base = dict(image_url=arquivo, caption=item["legenda"])
    extras = {}
    if item.get("alt") and not item.get("video"):
        extras["alt_text"] = item["alt"]
    if item.get("ia"):
        extras["is_ai_generated"] = "true"
    r = chamar("POST", f"{UID}/media", **base, **extras)
    if "id" not in r and extras:  # campo opcional recusado: tenta sem ele
        print(f"Contêiner recusou os campos extras ({r.get('mensagem')}); tentando sem eles.")
        r = chamar("POST", f"{UID}/media", **base)
    if "id" not in r:
        sys.exit(f"Falha ao criar o contêiner de {item['imagem']}: {r}")
    for _ in range(72 if item.get("video") else 24):  # vídeo: a Meta processa por até ~6 min
        st = chamar("GET", r["id"], fields="status_code")
        if st.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
            break
        time.sleep(5)
    return r["id"], st.get("status_code")


def ja_publicado(item):
    recentes = chamar("GET", f"{UID}/media", fields="id,caption,permalink", limit="15").get("data", [])
    for m in recentes:
        if (m.get("caption") or "").strip() == item["legenda"].strip():
            return m
    return None


def main():
    if MODO == "publicar":
        conferir_site()
    fila = json.load(open(FILA, encoding="utf-8"))
    agora = datetime.datetime.now(datetime.timezone.utc)
    pendentes = [i for i in fila if not i.get("publicado") and not i.get("lembrete")]
    enviar_lembretes(fila, agora)  # antes de esperar o horário de algum post
    if MODO == "teste":
        if not pendentes:
            sys.exit("Nada pendente na fila.")
        cid, st = preparar(pendentes[0])
        print(f"Teste: {pendentes[0]['imagem']} → contêiner {st} (não publicado; expira em 24 h).")
        sys.exit(0 if st == "FINISHED" else 1)

    proximos = [i for i in pendentes if agora < datetime.datetime.fromisoformat(i["quando"]) <= agora + ESPERA_MAXIMA]
    if MODO == "publicar" and proximos and not [i for i in pendentes if datetime.datetime.fromisoformat(i["quando"]) <= agora]:
        espera = (datetime.datetime.fromisoformat(proximos[0]["quando"]) - agora).total_seconds() + 20
        print(f"{proximos[0]['imagem']} sai em {int(espera // 60)} min: esperando o horário.", flush=True)
        time.sleep(espera)
        agora = datetime.datetime.now(datetime.timezone.utc)
    enviar_lembretes(fila, agora)
    vencidos = [i for i in pendentes if datetime.datetime.fromisoformat(i["quando"]) <= agora]
    if not vencidos:
        print("Nada para publicar agora.")
        gravar(fila)
        return
    alvo = None
    for item in vencidos:  # marca o que já está no ar; publica no máximo um
        achado = ja_publicado(item)
        if achado:
            print(f"{item['imagem']} já estava no ar ({achado.get('permalink')}); só marco na fila.")
            item["publicado"] = {"id": achado["id"], "link": achado.get("permalink"), "em": agora.isoformat(timespec="minutes")}
        elif agora - datetime.datetime.fromisoformat(item["quando"]) > ATRASO_MAXIMO:
            print(f"AVISO: {item['imagem']} passou mais de 12 h do horário; não publico sozinho.")
            if not item.get("avisado"):
                avisar(f"Pé no Freio: {item['imagem']} passou mais de 12 h do horário e não saiu. Fala com o Claude.")
                item["avisado"] = True
        elif alvo is None:
            alvo = item
    if alvo:
        item = alvo
        try:
            cid, st = preparar(item)
            if st != "FINISHED":
                sys.exit(f"Contêiner de {item['imagem']} ficou {st}.")
            r = chamar("POST", f"{UID}/media_publish", creation_id=cid)
            if "id" not in r:
                sys.exit(f"Falha ao publicar {item['imagem']}: {r}")
        except SystemExit as e:
            avisar(f"Pé no Freio: o robô NÃO publicou {item['imagem']}. Motivo: {e}. Fala com o Claude.")
            gravar(fila)
            raise
        info = chamar("GET", r["id"], fields="permalink")
        item["publicado"] = {"id": r["id"], "link": info.get("permalink"), "em": agora.isoformat(timespec="minutes")}
        print(f"Publicado {item['imagem']}: {info.get('permalink')}")
        avisar(f"Pé no Freio: saiu {item['imagem']}. {info.get('permalink') or ''}")
    gravar(fila)


def gravar(fila):
    json.dump(fila, open(FILA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(FILA, "a").write("\n")


if __name__ == "__main__":
    main()
