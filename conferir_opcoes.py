#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conferência das listas de citação na página publicada: opção órfã e contagens."""
import os
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://caruaru-ementas.vercel.app"
SENHA = open(os.path.expanduser("~/.hermes/secrets/caruaru_ementas_senha.txt"),
             encoding="utf-8").read().strip()

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("dialog", lambda d: d.accept(SENHA))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(2000)

    for campo, nome in (("#f-leg", "legislação"), ("#f-jur", "jurisprudência")):
        opts = pg.eval_on_selector_all(
            campo + " option", "e=>e.map(o=>({v:o.value,t:o.textContent}))")
        grupos = pg.eval_on_selector_all(campo + " optgroup", "e=>e.map(g=>g.label)")
        orfas = [o for o in opts if o["v"] and "[0]" in o["t"]]
        sem_num = [o for o in opts if o["v"] and not o["t"].strip()]
        print("%s: %d opções (%d citações + 'todas') em %d grupos" %
              (nome, len(opts), len(opts) - 1, len(grupos)))
        print("   órfãs ([0]):", len(orfas), orfas[:3])
        print("   vazias:", len(sem_num))
        print("   grupos:", grupos)

    print("pageerrors:", len(erros), erros[:3])
    b.close()
