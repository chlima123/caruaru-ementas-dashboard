#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa para fonte/ os .md da pasta *Ementas* do Drive (conta sherpa.de.ana@gmail.com).

Idempotente: só reescreve o arquivo quando o conteúdo mudou. Imprime o total
local; o cron compara esse total antes/depois para decidir se reconstrói.
"""
import importlib.util
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
FONTE = os.path.join(BASE, "fonte")
HELPER = "/Users/chlima/.hermes/profiles/sherpa/scripts/ementas_drive_put.py"


def main():
    spec = importlib.util.spec_from_file_location("edp", HELPER)
    edp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(edp)
    tok = edp.access_token()
    pasta = edp.list_folder(tok)
    pasta = pasta["files"] if isinstance(pasta, dict) else pasta
    os.makedirs(FONTE, exist_ok=True)
    novos = alterados = iguais = 0
    for f in pasta:
        nome = f.get("name") or ""
        if not nome.endswith(".md"):
            continue
        req = urllib.request.Request(
            "https://www.googleapis.com/drive/v3/files/%s?alt=media&supportsAllDrives=true" % f["id"],
            headers={"Authorization": "Bearer " + tok})
        bruto = urllib.request.urlopen(req, timeout=120).read()
        destino = os.path.join(FONTE, nome)
        if os.path.exists(destino):
            if open(destino, "rb").read() == bruto:
                iguais += 1
                continue
            alterados += 1
        else:
            novos += 1
        tmp = destino + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(bruto)
        os.replace(tmp, destino)
    total = len([x for x in os.listdir(FONTE) if x.endswith(".md")])
    print("drive: %d .md | novos: %d | alterados: %d | iguais: %d | local: %d"
          % (len([f for f in pasta if (f.get("name") or "").endswith(".md")]),
             novos, alterados, iguais, total))


if __name__ == "__main__":
    sys.exit(main())
