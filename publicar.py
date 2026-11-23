#!/usr/bin/env python3
"""Publica no Instagram do Pé no Freio os posts de imagem da fila (fila.json) quando chega a hora.

Roda no GitHub Actions duas vezes por hora (o GitHub atrasa ou pula rodadas agendadas; a que cair até 4 h antes de um
post espera o horário). Publica no máximo um post por execução.
MODO=teste: prepara o contêiner do próximo post pendente e confere se a Meta aceitou a imagem, SEM publicar.

Segredos (GitHub Actions): INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_USER_ID. O token nunca é impresso.
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


def preparar(item):
    arquivo = f"https://raw.githubusercontent.com/{REPO}/main/imagens/{item['imagem']}"
    if item.get("video"):  # meme em Reels: o mp4 fica em imagens/ junto do jpg
        base = dict(media_type="REELS", video_url=arquivo.rsplit("/", 1)[0] + "/" + item["video"],
                    caption=item["legenda"], share_to_feed="true")
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
    fila = json.load(open(FILA, encoding="utf-8"))
    agora = datetime.datetime.now(datetime.timezone.utc)
    pendentes = [i for i in fila if not i.get("publicado")]
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
    vencidos = [i for i in pendentes if datetime.datetime.fromisoformat(i["quando"]) <= agora]
    if not vencidos:
        print("Nada para publicar agora.")
        return
    alvo = None
    for item in vencidos:  # marca o que já está no ar; publica no máximo um
        achado = ja_publicado(item)
        if achado:
            print(f"{item['imagem']} já estava no ar ({achado.get('permalink')}); só marco na fila.")
            item["publicado"] = {"id": achado["id"], "link": achado.get("permalink"), "em": agora.isoformat(timespec="minutes")}
        elif agora - datetime.datetime.fromisoformat(item["quando"]) > ATRASO_MAXIMO:
            print(f"AVISO: {item['imagem']} passou mais de 12 h do horário; não publico sozinho.")
        elif alvo is None:
            alvo = item
    if alvo:
        item = alvo
        cid, st = preparar(item)
        if st != "FINISHED":
            sys.exit(f"Contêiner de {item['imagem']} ficou {st}.")
        r = chamar("POST", f"{UID}/media_publish", creation_id=cid)
        if "id" not in r:
            sys.exit(f"Falha ao publicar {item['imagem']}: {r}")
        info = chamar("GET", r["id"], fields="permalink")
        item["publicado"] = {"id": r["id"], "link": info.get("permalink"), "em": agora.isoformat(timespec="minutes")}
        print(f"Publicado {item['imagem']}: {info.get('permalink')}")
    json.dump(fila, open(FILA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(FILA, "a").write("\n")


if __name__ == "__main__":
    main()
