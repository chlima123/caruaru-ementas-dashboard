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


# ---------------------------------------------------------------- campos de citação
# Duas buscas dedicadas: [legislação] (artigo e diploma) e [jurisprudência] (decisão,
# súmula, tema). O campo não é padronizado nas ementas — o rótulo varia ("Dispositivos
# relevantes citados", "Dispositivos legais", "Legislação relevante citada", "Jurisprudência
# relevante citada", "Jurisprudências citadas"...) e às vezes vem combinado numa linha só
# ("Legislação e jurisprudência relevantes: ..."), com as citações de jurisprudência sem
# rótulo próprio. Verificado contra as 66 ementas do acervo em 17/10/2026.
CIT_LEG = (r"(?:Dispositivos?(?:\s+(?:relevantes\s+citados|relevantes|citados|legais|normativos))?"
           r"|Legisla[çc][ãa]o(?:\s+relevantes?)?(?:\s+citad[ao]s?)?)")
CIT_JUR = r"(?:Jurisprud[êe]nci\s*as?(?:\s+(?:relevantes?|citadas?)(?:\s+citadas?)?)?)"
CIT_COMB = (r"(?:Legisla[çc][ãa]o\s+e\s+jurisprud[êe]ncia(?:\s+relevantes?(?:\s+citad[ao]s?)?)?"
            r"|Dispositivos?\s+e\s+jurisprud[êe]ncia(?:\s+relevantes?)?)")
CIT_ROT = r"(?:%s|%s|%s)" % (CIT_LEG, CIT_JUR, CIT_COMB)
# marcadores que só aparecem em citação de jurisprudência
CIT_TRIBS = (r"STF|STJ|TST|TSE|TNU|TRF\d?|TRT\d*|TJPE|TJ-PE|TJ[A-Z]{2}|"
             r"S[úu]mula(?:\s+Vinculante)?|Tema(?:\s+\d|\s+Repetitivo|\s+da)|"
             r"ADI|ADC|ADPF|REsp|AREsp|AgInt|AgRg|EDcl|EREsp|EAREsp|RMS|IAC|"
             r"Incidente\s+de\s+Assun[çc][ãa]o|Repercuss[ãa]o\s+Geral")
# onde o bloco de citações termina e recomeça o texto do documento
CIT_FIM = re.compile(r"(?i)\b(?:MA\s*NIFESTA[ÇC][ÃA]O|MANIFESTA[ÇC][ÃA]O|TRATA-SE|Trata-se\s+de|"
                     r"PARECER|2[ªa]?\s*PROCURADORIA\s+DE\s+JUSTI[ÇC]A|MINIST[ÉE]RIO\s+P[ÚU]BLICO)\b")


def _corta_cit(s):
    m = CIT_FIM.search(s)
    if m:
        s = s[:m.start()]
    return re.split(r"(?m)^\s*(?:#{1,6}\s|\*\*[IVX]+\.|[IVX]+\.\s|_+|-{3,}\s*$)", s)[0]


def _limpa_cit(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"(?i)[\s\-–—●•*]*\b(?:Jurisprud[êe]ncias?|Legisla[çc][ãa]o|Dispositivos?)\s*"
               r"(?:relevantes?|citad[ao]s?|legais|normativos)*(?:\s+citad[ao]s?)*\s*:?\s*$", "", s).strip()
    s = re.sub(r"^[\s:;.,\-–—●•*]+", "", s)
    s = re.sub(r"[\s:;.,\-–—●•*]+$", "", s)
    if s.lower().rstrip(".") in ("", "—", "-", "n/a", "nao ha", "não há", "sem jurisprudência citada"):
        return ""
    if re.match(r"(?i)^sem\s+jurisprud", s):
        return ""
    return s


def citacoes(txt):
    """(legislação, jurisprudência) do campo de citações da ementa — "" quando não há."""
    # 1) rótulo ocupando a linha inteira (título): o conteúdo é o que vem depois
    m = re.search(r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?\*{0,2}[ \t]*" + CIT_ROT + r"[ \t]*\*{0,2}[ \t]*:?[ \t]*$", txt)
    if m:
        sec = _corta_cit(txt[m.end():]).strip()
    else:
        # 2) rótulo inline: começa no rótulo e vai até o fim lógico do bloco
        m = re.search(r"(?i)\b" + CIT_ROT + r"\b[ \t]*\*{0,2}[ \t]*:", txt)
        sec = _corta_cit(txt[m.start():]).strip() if m else ""
    if not sec:
        return "", ""
    # rótulo combinado não separa os campos: sai antes de procurar os rótulos individuais
    sec = re.sub(r"(?i)^\s*\**\s*" + CIT_COMB + r"\s*\*{0,2}\s*:?\s*", "", sec, count=1)
    mj = re.search(r"(?i)(?<![\w])\**\s*(" + CIT_JUR + r")\s*\*{0,2}\s*:\s*", sec)
    ml = re.search(r"(?i)(?<![\w])\**\s*(" + CIT_LEG + r")\s*\*{0,2}\s*:\s*", sec)
    leg = jur = ""
    if ml:
        ini = ml.end()
        leg = sec[ini:mj.start()] if (mj and mj.start() > ini) else (sec[ini:] if not mj else "")
    if mj:
        jur = sec[mj.end():]
    if not leg and not jur:
        # bloco sem rótulo nenhum: corta no primeiro marcador de jurisprudência
        mt = re.search(r"(?i)(?:(?<=[\s.;(])|^)(?=(?:" + CIT_TRIBS + r")\b)", sec)
        leg, jur = (sec[:mt.start()], sec[mt.start():]) if mt else (sec, "")
    elif not jur:
        mt = re.search(r"(?i)(?:(?<=[\s.;(])|^)(?=(?:" + CIT_TRIBS + r")\b)", leg)
        if mt:
            leg, jur = leg[:mt.start()], leg[mt.start():]
    return _limpa_cit(leg), _limpa_cit(jur)


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
        cit_leg, cit_jur = citacoes(txt)
        rec = {"f": nome, "t": titulo, "p": numero, "cl": classe, "iso": iso, "dt": br,
               "tj": tipo, "oj": campo(txt, "Órgão julgador"), "rel": campo(txt, "Relator"),
               "pj": campo(txt, "Procuradora de Justiça") or campo(txt, "Procurador de Justiça"),
               "ass": assunto_do_nome(nome), "pt": partes, "e": ementa, "c": corpo,
               "l": cit_leg, "j": cit_jur}
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
