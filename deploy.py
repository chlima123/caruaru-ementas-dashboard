#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica o dashboard caruaru-ementas no Vercel (cria o projeto se faltar) e
PROVA o que está no ar pelo sha1 do arquivo servido.

Uso: /usr/bin/python3 deploy.py [--sem-verificar]
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.vercel.com"
BASE = os.path.dirname(os.path.abspath(__file__))
NOME = "caruaru-ementas"
ENV = os.path.expanduser("~/.hermes/.env")


def token():
    t = os.environ.get("VERCEL_API_TOKEN", "")
    if t:
        return t
    for ln in open(ENV, encoding="utf-8", errors="replace"):
        if ln.startswith("VERCEL_API_TOKEN="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("VERCEL_API_TOKEN ausente em ~/.hermes/.env")


def api(tok, method, path, body=None, raw=None, headers=None):
    h = {"Authorization": "Bearer " + tok}
    data = None
    if raw is not None:
        data = raw
        h.update(headers or {})
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt.strip() else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt}


def main():
    tok = token()
    st, d = api(tok, "GET", "/v9/projects/" + NOME)
    if st == 404:
        st, d = api(tok, "POST", "/v10/projects", {"name": NOME, "framework": None})
        print("projeto criado:", NOME, st)
    if st not in (200, 201):
        raise SystemExit("projeto %s indisponivel: %s %s" % (NOME, st, str(d)[:300]))
    pid, org = d["id"], d.get("accountId") or d.get("orgId")
    os.makedirs(os.path.join(BASE, ".vercel"), exist_ok=True)
    json.dump({"projectId": pid, "orgId": org, "projectName": NOME},
              open(os.path.join(BASE, ".vercel", "project.json"), "w"), indent=2)
    # projeto novo nasce com ssoProtection (pede login Vercel) — zera para valer o gate HTML
    st2, d2 = api(tok, "PATCH", "/v9/projects/" + NOME,
                  {"ssoProtection": None, "passwordProtection": None})
    print("protecao nativa: sso=%s | password=%s" % (d2.get("ssoProtection"), d2.get("passwordProtection")))

    dados = open(os.path.join(BASE, "index.html"), "rb").read()
    sha = hashlib.sha1(dados).hexdigest()
    st, r = api(tok, "POST", "/v2/files", raw=dados,
                headers={"Content-Type": "text/plain", "x-vercel-digest": sha})
    if st not in (200, 201):
        raise SystemExit("upload falhou: %s %s" % (st, str(r)[:300]))
    st, dep = api(tok, "POST", "/v13/deployments",
                  {"name": NOME, "project": pid, "target": "production",
                   "files": [{"file": "index.html", "sha": sha, "size": len(dados)}]})
    if st not in (200, 201):
        raise SystemExit("deploy falhou: %s %s" % (st, str(dep)[:300]))
    print("deploy %s | %s | %s" % (dep.get("id"), dep.get("readyState"), dep.get("url")))
    print("sha1 local: %s (%d B)" % (sha, len(dados)))

    if "--sem-verificar" in sys.argv:
        return
    for alias in (NOME + ".vercel.app", NOME + "-sherpachsl.vercel.app"):
        for _ in range(14):
            time.sleep(5)
            try:
                req = urllib.request.Request("https://%s/?cb=%d" % (alias, int(time.time())),
                                             headers={"Cache-Control": "no-cache"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    corpo = r.read()
                got = hashlib.sha1(corpo).hexdigest()
            except Exception as e:
                got = "ERR " + str(e)[:60]
            if got == sha:
                h = corpo.decode("utf-8", "replace")
                pos_gate, pos_body = h.find("var pass = prompt"), h.find("</body>")
                print("VERIFICADO %s: sha1 OK | gate antes de </body>: %s" % (alias, 0 < pos_gate < pos_body))
                print("URL: https://%s" % alias)
                return
        print("alias %s ainda nao propagou (%s)" % (alias, str(got)[:60]))
    sys.exit(1)


if __name__ == "__main__":
    main()
