#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monta o index.html do dashboard (template + dados.json + gate de senha).

Uso: /usr/bin/python3 montar.py [--sem-gate]
O gate vai SEMPRE antes de </body> (injetado depois, o parser termina de ler o
documento depois do script e o dashboard fica legível sem senha).
"""
import datetime
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SEGREDO = os.path.expanduser("~/.hermes/secrets/caruaru_ementas_senha.txt")
CONFIG = os.path.join(BASE, "config.json")


def senha():
    """Senha do gate, nesta ordem: --senha X, env EMENTAS_SENHA, ~/.hermes/secrets/<nome>.txt.
    NUNCA literal no repositório (é a mesma família de senha dos outros dashboards MPPE)."""
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--senha" and i + 1 < len(argv):
            return argv[i + 1].strip()
    v = os.environ.get("EMENTAS_SENHA", "").strip()
    if v:
        return v
    if os.path.exists(SEGREDO):
        return open(SEGREDO, encoding="utf-8").read().strip()
    return ""


def config():
    """Endereço da pasta no Drive (button 'Abrir a pasta no Drive') e afins — local, fora do repo."""
    d = {}
    if os.path.exists(CONFIG):
        d = json.load(open(CONFIG, encoding="utf-8"))
    d.setdefault("drive_url", os.environ.get("EMENTAS_DRIVE_URL", "").strip())
    return d


GATE = """<script>
(function(){
  var pass = prompt("Ementas — Câmara Regional de Caruaru\\nAcesso restrito. Informe a senha:");
  if (pass !== "%s") {
    document.documentElement.innerHTML = '<head><meta charset="utf-8"><title>Acesso restrito</title></head>' +
      '<body style="font-family:Georgia,serif;background:#0E2A33;color:#eef3f4;margin:0;display:flex;' +
      'align-items:center;justify-content:center;height:100vh;text-align:center">' +
      '<div><h2 style="font-weight:600">Acesso restrito</h2>' +
      '<p style="color:#9fb0b5;font-size:14px">Conteúdo interno — dados de processos judiciais.</p></div></body>';
  }
})();
</script>"""


def main():
    tpl = open(os.path.join(BASE, "template.html"), encoding="utf-8").read()
    dados = json.load(open(os.path.join(BASE, "dados.json"), encoding="utf-8"))
    cfg = config()
    sem_gate = "--sem-gate" in sys.argv
    chave = senha()
    if not sem_gate and not chave:
        raise SystemExit("ERRO: senha do gate ausente (--senha, EMENTAS_SENHA ou %s) — "
                         "não publico dashboard sem gate por acidente." % SEGREDO)
    html = tpl.replace("__DATA__", json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    html = html.replace("__DRIVE__", json.dumps(cfg["drive_url"]))
    if sem_gate:
        html = html.replace("__GATE__", "")
    else:
        html = html.replace("__GATE__", GATE % chave)
    assert not re.findall(r"__[A-Z]{3,}__", html), "sobrou placeholder"
    if not sem_gate:
        assert 0 < html.find("var pass = prompt") < html.find("</body>"), "gate fora de lugar"
    dest = os.path.join(BASE, "index.html")
    if os.path.exists(dest):
        os.makedirs(os.path.join(BASE, "backup"), exist_ok=True)
        os.replace(dest, os.path.join(BASE, "backup", "index.%s.html" % datetime.datetime.now().strftime("%H%M%S")))
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(html)
    # checagem de sintaxe dos blocos <script> inline
    blocos = re.findall(r"<script>(.*?)</script>", html, re.S)
    for n, b in enumerate(blocos):
        p = os.path.join(BASE, "bloco%d.js" % n)
        open(p, "w", encoding="utf-8").write(b)
        r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
        if r.returncode:
            print("ERRO de sintaxe no bloco %d:\n%s" % (n, r.stderr[:600]))
            sys.exit(1)
        os.remove(p)
    print("index.html: %.0f KB | registros: %d | blocos <script> validados: %d | gate: %s | drive: %s"
          % (os.path.getsize(dest) / 1024, len(dados), len(blocos),
             "não" if sem_gate else "sim", "sim" if cfg["drive_url"] else "não"))


if __name__ == "__main__":
    main()
