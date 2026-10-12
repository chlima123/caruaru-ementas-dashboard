#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Constrói o dado do dashboard "Ementas — Câmara Regional de Caruaru".

Lê os .md publicados na pasta *Ementas* do Drive (baixados para fonte/ por
ementas_fonte_pull.py), monta os registros e, se o modelo estiver disponível,
pré-calcula os embeddings (paraphrase-multilingual-MiniLM-L12-v2, 384 dims).

Saída: dados.json  (lista de registros)
Uso:   /usr/bin/python3 build_dados.py [--sem-embeddings]
"""
import base64
import datetime
import json
import os
import re
import struct
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FONTE = os.path.join(BASE, "fonte")
SAIDA = os.path.join(BASE, "dados.json")
MODELO = "paraphrase-multilingual-MiniLM-L12-v2"

# classes a partir do token do nome do arquivo (AC_/AI_/AP_/HC_/CC_/...)
CLASSE_TOKEN = {"AC": "APELAÇÃO CÍVEL", "AI": "AGRAVO DE INSTRUMENTO", "AP": "APELAÇÃO",
                "HC": "HABEAS CORPUS", "CC": "CONFLITO DE COMPETÊNCIA",
                "ACC": "APELAÇÃO CÍVEL", "AGINT": "AGRAVO INTERNO", "COTA": "—"}
TIPOS = ("EMENTA", "PROMOÇÃO", "COTA", "DESPACHO", "PARECER", "MANIFESTAÇÃO", "OFÍCIO")

# acentuação dos termos que vêm do nome do arquivo (sem acento)
ACENTOS = {
    "saude": "saúde", "medicas": "médicas", "medicos": "médicos", "progressoes": "progressões",
    "prisao": "prisão", "convivencia": "convivência", "desapropriacao": "desapropriação",
    "execucao": "execução", "usucapiao": "usucapião", "filantropico": "filantrópico",
    "pensao": "pensão", "municipio": "município", "agua": "água", "liberacao": "liberação",
    "veiculo": "veículo", "urgencia": "urgência", "reclamacao": "reclamação",
    "deposito": "depósito", "alugueis": "aluguéis", "abstencao": "abstenção",
    "publica": "pública", "despesas": "despesas", "extraordinarias": "extraordinárias",
    "exoneracao": "exoneração", "inexistencia": "inexistência", "debito": "débito",
    "desercao": "deserção", "uniao": "união", "estavel": "estável",
    "contrarrazoes": "contrarrazões", "improbo": "ímprobo", "nomeacao": "nomeação",
    "concurso": "concurso", "terapeutico": "terapêutico", "tutela": "tutela",
    "infracional": "infracional", "reembolso": "reembolso", "autismo": "autismo",
}


def campo(txt, nome):
    m = re.search(r"^\|\s*" + re.escape(nome) + r"\s*\|\s*(.+?)\s*\|\s*$", txt, re.M)
    return m.group(1).strip() if m else ""


def secao(txt, titulo):
    """Conteúdo sob '## <titulo>' (aceita sufixo, ex.: '(reprodução integral)')."""
    m = re.search(r"^##\s+" + re.escape(titulo) + r"\b[^\n]*$(.*?)(?=^##\s|\Z)", txt, re.M | re.S)
    return m.group(1).strip() if m else ""


def limpa_ementa(txt):
    txt = re.sub(r"^\*\*EMENTA:?\*\*\s*", "", txt.strip(), flags=re.I)
    txt = re.sub(r"^>\s*⚠️.*?$", "", txt, flags=re.M | re.S)
    return txt.strip()


def limpa_corpo(txt):
    txt = re.sub(r"^>\s*⚠️.*?teor do documento\.\s*$", "", txt, flags=re.M | re.S)
    return txt.strip()


def acentua(palavra):
    chave = palavra.lower().strip(".,;:()")
    if chave in ACENTOS:
        nova = ACENTOS[chave]
        if palavra[:1].isupper():
            nova = nova[:1].upper() + nova[1:]
        return nova
    return palavra


def assunto_do_nome(nome):
    """'20260902_AC_0001849-86.2025...._Alimentos_Contrarrazoes_Cota.md' -> 'Alimentos · Contrarrazões · Cota'."""
    base = re.sub(r"\.md$", "", nome)
    partes = [p for p in base.split("_") if p]
    partes = [p for p in partes if not re.match(r"^[\d.\-]+$", p)]        # tira data e nº do processo
    partes = [p for p in partes if p.upper() not in CLASSE_TOKEN]          # tira o token de classe
    pedacos = []
    for seg in partes:
        seg = re.sub(r"([a-z])([A-Z])", r"\1 \2", seg)
        seg = re.sub(r"([A-Za-z])(\d)(\d*)", r"\1 \2\3", seg)
        palavras = [acentua(w) if w.upper() not in {"TEA", "ERBS", "BPC", "LOAS", "ACP", "MS",
                                                    "SM", "SASSEPE", "NATJUS", "CDA",
                                                    "PERPART", "UNIMED", "SUS"} else w.upper()
                    for w in seg.split()]
        pedacos.append(" ".join(palavras))
    return " · ".join(pedacos)


def datas(nome):
    m = re.match(r"(\d{4})(\d{2})(\d{2})_", nome)
    if not m:
        return "", ""
    iso = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    return iso, "%s/%s/%s" % (m.group(3), m.group(2), m.group(1))


def registros():
    out = []
    for nome in sorted(os.listdir(FONTE)):
        if not nome.endswith(".md"):
            continue
        txt = open(os.path.join(FONTE, nome), encoding="utf-8").read()
        h1 = re.search(r"^#\s+(.+)$", txt, re.M)
        titulo = h1.group(1).strip() if h1 else nome
        prefixo = titulo.split("—")[0].strip() if "—" in titulo else ""
        cabeca, _, _ = titulo.partition("—")

        ementa = limpa_ementa(secao(txt, "Ementa"))
        corpo = limpa_corpo(secao(txt, "Teor do documento") or secao(txt, "Manifestação"))

        classe = campo(txt, "Classe")
        if not classe or classe == "—":
            if "—" in titulo and "nº" in cabeca:
                pass
            tok = [p for p in nome.split("_") if p.upper() in CLASSE_TOKEN]
            classe = CLASSE_TOKEN.get(tok[0].upper(), "—") if tok else "—"
        classe = re.sub(r"\s+", " ", classe).upper().strip()

        tipo = campo(txt, "Tipo de documento")
        if not tipo:
            tipo = prefixo if prefixo.upper() in TIPOS else ""
        if not tipo:
            tipo = "Ementa" if ementa else ("Manifestação" if corpo else "—")
        tipo = tipo.strip()

        numero = campo(txt, "Processo")
        if not numero:
            mnum = re.search(r"nº\s*([\d.\-]+)", titulo)
            numero = mnum.group(1) if mnum else ""

        fixos = {"Processo", "Classe", "Órgão julgador", "Relator", "Procuradora de Justiça",
                 "Procurador de Justiça", "Tipo de documento", "Documento de origem"}
        partes = []
        for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", txt, re.M):
            k, v = m.group(1).strip(), m.group(2).strip()
            if k in fixos or k == "Campo" or set(k) <= {"-", " "}:
                continue
            partes.append({"k": k, "v": v})

        iso, br = datas(nome)
        rec = {"f": nome, "t": titulo, "p": numero, "cl": classe, "iso": iso, "dt": br,
               "tj": tipo, "oj": campo(txt, "Órgão julgador"), "rel": campo(txt, "Relator"),
               "pj": campo(txt, "Procuradora de Justiça") or campo(txt, "Procurador de Justiça"),
               "ass": assunto_do_nome(nome), "pt": partes, "e": ementa, "c": corpo}
        rec["s"] = " ".join([rec["t"], rec["p"], rec["ass"], rec["cl"], rec["oj"], rec["rel"],
                             rec["tj"], " ".join("%s %s" % (x["k"], x["v"]) for x in rec["pt"]),
                             rec["e"], rec["c"]])
        out.append(rec)
    return out


def trechos(txt, alvo=900, sobre=120, minimo=80):
    """Fatia o texto em trechos de ~900 caracteres, cortando em fim de frase."""
    txt = re.sub(r"\s+", " ", txt).strip()
    out, i = [], 0
    while i < len(txt):
        j = min(len(txt), i + alvo)
        if j < len(txt):
            k = txt.rfind(". ", i + 200, j)
            if k > 0:
                j = k + 1
        out.append((i, txt[i:j]))
        if j >= len(txt):
            break
        i = j - sobre
    uteis = [(p, t) for (p, t) in out if len(t) >= minimo]
    return uteis or ([(out[0][0], txt)] if out else [])


def main():
    recs = registros()
    com_texto = [r for r in recs if (r["e"] or r["c"])]
    if "--sem-embeddings" not in sys.argv:
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(MODELO)
            fatias = {id(r): trechos(r["s"]) for r in com_texto}
            planos = [(r, p, t) for r in com_texto for (p, t) in fatias[id(r)]]
            vetores = model.encode([t for (_, _, t) in planos], normalize_embeddings=True,
                                    batch_size=32, show_progress_bar=False)
            for (r, p, _), v in zip(planos, vetores):
                r.setdefault("vs", []).append(base64.b64encode(
                    struct.pack("%df" % len(v), *v)).decode())
                r.setdefault("vo", []).append(p)
            print("embeddings por trecho: %d trechos em %d documentos (%.1f por doc)"
                  % (len(planos), len(com_texto), len(planos) / max(1, len(com_texto))))
        except Exception as exc:
            print("AVISO: sem embeddings (%s: %s) — a busca semântica fica indisponível."
                  % (type(exc).__name__, exc))
    for r in recs:
        r.setdefault("vs", [])
        r.setdefault("vo", [])
    with open(SAIDA, "w", encoding="utf-8") as fh:
        json.dump(recs, fh, ensure_ascii=False)
    print("registros: %d | com ementa: %d | sem ementa: %d | trechos-vetor: %d | json: %.0f KB"
          % (len(recs), sum(1 for r in recs if r["e"]), sum(1 for r in recs if not r["e"]),
             sum(len(r["vs"]) for r in recs), os.path.getsize(SAIDA) / 1024))
    print("classes:", sorted({r["cl"] for r in recs}))
    print("tipos:", sorted({r["tj"] for r in recs}))
    print("período:", min(r["iso"] for r in recs if r["iso"]), "→", max(r["iso"] for r in recs if r["iso"]))


if __name__ == "__main__":
    main()
