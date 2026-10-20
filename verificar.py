#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificação do dashboard no Chrome real: gate, texto, filtros, semântica."""
import os
import sys
from playwright.sync_api import sync_playwright


def senha():
    v = os.environ.get("EMENTAS_SENHA", "").strip()
    if v:
        return v
    p = os.path.expanduser("~/.hermes/secrets/caruaru_ementas_senha.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    raise SystemExit("senha do gate ausente: defina EMENTAS_SENHA ou cria %s" % p)


URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899/index.html"
SENHA = senha()
erros = []

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1500, "height": 950})
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("dialog", lambda d: d.accept(SENHA))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(1800)

    print("KPIs:", pg.eval_on_selector_all("#kpis .kpi b", "e=>e.map(x=>x.textContent)"))
    print("itens na lista:", pg.eval_on_selector_all(".hit", "e=>e.length"))
    print("leitor abriu no 1o registro:", bool(pg.query_selector("#reader .rhead h2")),
          "|", (pg.text_content("#reader .rhead h2") or "")[:70])

    pg.click("#modeText")
    pg.fill("#search", "autismo")
    pg.wait_for_timeout(700)
    print("texto 'autismo' →", pg.eval_on_selector_all(".hit h3", "e=>e.slice(0,3).map(x=>x.textContent)"))
    print("  contador:", pg.text_content("#rescount"))

    pg.fill("#search", "")                       # o filtro de classe é medido SOZINHO, sem o texto
    pg.wait_for_timeout(300)
    pg.select_option("#f-cl", "HABEAS CORPUS")
    pg.wait_for_timeout(600)
    print("filtro classe=HABEAS CORPUS →", pg.text_content("#rescount"), "|",
          pg.eval_on_selector_all(".hit h3", "e=>e.map(x=>x.textContent)"))

    pg.fill("#search", "")
    pg.select_option("#f-cl", "")
    pg.select_option("#f-mes", "2026-10")
    pg.wait_for_timeout(500)
    print("filtro mês=10/2026 →", pg.text_content("#rescount"))
    pg.select_option("#f-mes", "")
    pg.wait_for_timeout(400)

    # ---- listas suspensas de citação: [legislação] e [jurisprudência] ----
    def hits(n=3):
        return pg.eval_on_selector_all(".hit h3", "e=>e.slice(0,%d).map(x=>x.textContent)" % n)

    def primeiro_cit():
        v = pg.query_selector(".hit .snip")
        return (v.text_content() if v else "")[:150]

    def escolhe(id_campo, agulha):
        val = pg.eval_on_selector(id_campo,
            "(el, a) => { const o = [...el.options].find((o) => o.value && new RegExp(a, 'i').test(o.value)); return o ? o.value : ''; }",
            agulha)
        if val:
            pg.select_option(id_campo, val)
            pg.wait_for_timeout(600)
        return val

    print("opções nas listas:", pg.eval_on_selector_all("#f-leg option", "e=>e.length"),
          "legislação /", pg.eval_on_selector_all("#f-jur option", "e=>e.length"), "jurisprudência",
          "| grupos:", pg.eval_on_selector_all("#f-leg optgroup", "e=>e.length"), "/",
          pg.eval_on_selector_all("#f-jur optgroup", "e=>e.length"))
    print("grupos leg:", pg.eval_on_selector_all("#f-leg optgroup", "e=>e.slice(0,4).map(x=>x.label)"))
    print("grupos jur:", pg.eval_on_selector_all("#f-jur optgroup", "e=>e.slice(0,4).map(x=>x.label)"))
    pg.fill("#search", "")
    print("escolha leg 'art. 1.694 · CC' →", escolhe("#f-leg", r"^art\. 1\.694 · CC$"), "|",
          pg.text_content("#rescount"), "|", hits())
    print("   trecho:", primeiro_cit())
    escolhe("#f-leg", r"^art\. 8º · Lei nº 13\.146/2015$")
    print("[legislação] art. 8º da Lei 13.146 →", pg.text_content("#rescount"), "|", hits())
    pg.select_option("#f-leg", "")            # limpa p/ medir a jurisprudência sozinha
    pg.wait_for_timeout(300)
    escolhe("#f-jur", r"Tema 106")
    print("[jurisprudência] STJ · Tema 106 (legislação limpa) →", pg.text_content("#rescount"), "|", hits())
    print("   trecho:", primeiro_cit())
    escolhe("#f-leg", r"^art\. 1\.694 · CC$")
    print("E (art. 1.694 CC + Tema 106) →", pg.text_content("#rescount"), "|", hits())
    print("   caixa do leitor:", (pg.text_content("#reader .citbox") or "")[:120].replace("\n", " "))
    escolhe("#f-leg", r"^art\. 196 · CF/1988$")
    escolhe("#f-jur", r"^STJ · Tema 106")
    print("E (art. 196 CF + Tema 106) →", pg.text_content("#rescount"), "|", hits())
    print("   marcações de realce no trecho:", pg.eval_on_selector_all(".hit .snip mark", "e=>e.slice(0,4).map(x=>x.textContent)"))
    print("faixas de chips removidas:", pg.eval_on_selector_all(".chips", "e=>e.length") == 0,
          "| listas:", pg.eval_on_selector_all("#f-leg option", "e=>e.length"), "/",
          pg.eval_on_selector_all("#f-jur option", "e=>e.length"),
          "| grupos: leg", pg.eval_on_selector_all("#f-leg optgroup", "e=>e.length"),
          "jur", pg.eval_on_selector_all("#f-jur optgroup", "e=>e.length"))
    print("jur por tribunal:", pg.eval_on_selector_all("#f-jur optgroup", "e=>e.map(g=>g.label)"))
    pg.select_option("#f-leg", "")
    pg.select_option("#f-jur", "")
    pg.wait_for_timeout(400)

    # ---- busca semântica ----
    pg.click("#modeSem")
    pg.fill("#search", "medicamento de crescimento negado pelo plano de saúde")
    status = None
    for _ in range(48):
        pg.wait_for_timeout(5000)
        st = pg.text_content("#semStatus") or ""
        if "ativa" in st or "falhou" in st or "indisponível" in st:
            status = st
            break
    print("status semântico:", status)
    q1 = pg.eval_on_selector_all(".hit h3", "e=>e.slice(0,5).map(x=>x.textContent)")
    print("consulta 1 (crescimento/plano):", q1)
    pg.fill("#search", "pai preso por não pagar pensão alimentícia")
    pg.wait_for_timeout(7000)
    q2 = pg.eval_on_selector_all(".hit h3", "e=>e.slice(0,5).map(x=>x.textContent)")
    print("consulta 2 (prisão/pensão):", q2)
    print("resultados DIFEREM entre consultas:", q1 != q2)
    print("status final:", pg.text_content("#semStatus"))

    pg.screenshot(path="/Users/chlima/.hermes/cache/scratch/ementas-dashboard.png")
    print("pageerrors:", erros[:4], "| total:", len(erros))
    b.close()
