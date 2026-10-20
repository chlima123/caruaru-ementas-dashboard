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
import unicodedata
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


def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s or '')
                   if unicodedata.category(c) != 'Mn').lower()


# ------------------------------------------------------------------ legislação
DIPLOMA_PAT = (
    r"(?:Constitui[çc][ãa]o\s+(?:Federal(?:\s+de\s+1988)?|da\s+Rep[úu]blica|do\s+Estado\s+de\s+\w+(?:\s+\w+)?)"
    r"|CF(?:/\d{2,4})?(?![A-Za-zÀ-ÿ0-9])"
    r"|C[óo]digo\s+(?:de\s+Processo\s+Civil|de\s+Processo\s+Penal|de\s+Defesa\s+do\s+Consumidor|Civil|Penal|Tribut[áa]rio|Eleitoral)"
    r"|C\s?PC(?![A-Za-zÀ-ÿ])|CPC(?![A-Za-zÀ-ÿ])|CPP(?![A-Za-zÀ-ÿ])|CDC(?![A-Za-zÀ-ÿ])|CP(?![A-Za-zÀ-ÿ])|CC(?:/\d{4})?(?![A-Za-zÀ-ÿ])"
    r"|ECA(?![A-Za-zÀ-ÿ])|Estatuto\s+da\s+Crian[çc]a\s+e\s+do\s+Adolescente|LINDB(?![A-Za-zÀ-ÿ])"
    r"|Leis?\s+(?:Federal\s+)?n[ºo°]?\s*[\d.]+\s*/\s*\d{4}"
    r"|Lei\s+municipal\s+de\s+[^,.;]{2,60}?n[ºo°]?\s*[\d.]+\s*/\s*\d{4}"
    r"|Leis?\s+municipal(?:is)?\s+de\s+[^,.;]{2,40}"
    r"|EC\s+n[ºo°]?\s*[\d.]+\s*/\s*\d{4}"
    r"|Portaria\s+[^,.;]{0,24}?n[ºo°]?\s*[\d.]+\s*/\s*\d{4}"
    r"|Resolu[çc][õo]es?\s+[^,.;]{0,26}?n[ºo°]?\s*[\d.]+\s*/\s*\d{4}"
    r"|Conven[çc][ãa]o\s+sobre\s+os\s+Direitos\s+das\s+Pessoas\s+com\s+Defici[êe]ncia)"
)
DIPLOMA_RE = re.compile(DIPLOMA_PAT, re.I)
# códigos que o PRÓPRIO acervo identifica pelo número da lei (nada inventado aqui)
ALIAS_LEI = {"8069/1990": "ECA", "13105/2015": "CPC", "8078/1990": "CDC"}

def _limpa_parenteses(t):
    """'C PC (Lei nº 13.105/2015)' -> 'C PC': o número entre parênteses só repete o código."""
    return re.sub(r"(?i)\b(CPC|C\s?PC|CPP|CDC|ECA|CC|CF|CP)\s*\(\s*(?:Lei\s+n[ºo°]?\s*)?[\d.]+\s*/\s*\d{4}\s*\)", r"\1", t)

def _num_lei(n):
    return re.sub(r"\s", "", re.sub(r"(?i)^leis?\s+(?:federal\s+)?n[ºo°]*\s*", "", n))

def norm_diploma(nome):
    n = re.sub(r"\s+", " ", (nome or "")).strip().strip(":").strip(" .-–")
    l = sem_acento(n)
    if l.startswith("constitui"):
        return "Constituição de Pernambuco" if "pernambuco" in l else "CF/1988"
    if re.match(r"^cf\s*/\s*8", l) or l == "cf":
        return "CF/1988"
    for chaves, rot in (
        (("codigo de processo civil",), "CPC"),
        (("codigo de processo penal",), "CPP"),
        (("codigo civil",), "CC"),
        (("codigo penal",), "CP"),
        (("codigo de defesa do consumidor",), "CDC"),
        (("estatuto da crianca",), "ECA"),
        (("lindb",), "LINDB"),
    ):
        if any(l.startswith(c) for c in chaves):
            return rot
    if l in ("cpc", "c pc"):
        return "CPC"
    if l == "cpp":
        return "CPP"
    if re.match(r"^cc(/\d{4})?$", l):
        return "CC"
    if l == "cp":
        return "CP"
    if l == "cdc":
        return "CDC"
    if l == "eca":
        return "ECA"
    if l.startswith("leis municipais de ") or l.startswith("lei municipal de "):
        cid = re.sub(r"(?i)^leis?\s+municipais?\s+de\s+", "", n).strip()
        return "Lei municipal de " + cid
    m = re.match(r"(?i)^leis?\s+(?:federal\s+)?n[ºo°]*\s*([\d.]+)\s*/\s*(\d{4})", n)
    if m:
        chave = re.sub(r"\D", "", m.group(1)) + "/" + m.group(2)
        return ALIAS_LEI.get(chave, "Lei nº %s/%s" % (m.group(1), m.group(2)))
    m = re.match(r"(?i)^ec\s+n[ºo°]*\s*([\d.]+)\s*/\s*(\d{4})", n)
    if m:
        return "EC nº %s/%s" % (m.group(1), m.group(2))
    m = re.match(r"(?i)^(portaria)\s+(.+?)\s*n[ºo°]*\s*([\d.]+)\s*/\s*(\d{4})", n)
    if m:
        return "Portaria %s nº %s/%s" % (re.sub(r"\s+", " ", m.group(2)).strip(), m.group(3), m.group(4))
    m = re.match(r"(?i)^resolu[çc][õo]es?\s+(.+?)\s*n[ºo°]*\s*([\d.]+)\s*/\s*(\d{4})", n)
    if m:
        corpo = re.sub(r"(?i)^normativas?\s+", "", m.group(1)).strip()
        return "Resolução%s nº %s/%s" % ((" Normativa " + corpo) if re.match(r"(?i)^normativa", m.group(1)) else (" " + corpo), m.group(2), m.group(3))
    return n.strip(" .-–")

ART_RE = re.compile(r"(?i)^arts?\.?\s*(.+)$")
NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:\s*[ºo°])?([-][A-Z])?(.*)$")
QUAL_RE = re.compile(r"(?i)^(?:§+|par[áa]grafo|inciso|al[íi]nea|caput|item)\b")

def artigos_do_bloco(bloco):
    """Números de artigo citados num bloco. Máquina de estados: depois de um '§' que traz
    número, um pedaço ligado por ' e ' é subitem do parágrafo (não artigo); ligado por
    vírgula, é artigo novo. Vale para 'arts. 98, § 1º, 189, II e III, 300' e para
    'art. 1.021, §§ 1º e 2º'."""
    out, em_parag = [], False
    partes = re.split(r"(\s*;\s*|\s*,\s*|\s+e\s+|\s*\.\s+)", bloco or "")
    for i in range(0, len(partes), 2):
        c = re.sub(r"(?i)^e\s+", "", partes[i].strip().strip(".-–— "))
        sep = partes[i - 1] if i > 0 else ""
        if not c:
            continue
        m = ART_RE.match(c)
        if m:
            c = m.group(1).strip()
        elif QUAL_RE.match(c) or re.fullmatch(r"[IVXLC]{1,5}", c):
            em_parag = bool(re.match(r"(?i)^§", c))
            continue
        mn = NUM_RE.match(c)
        if mn:
            if em_parag and sep.strip() == "e":
                em_parag = False
                continue
            out.append((mn.group(1), mn.group(2) or ""))
            em_parag = False
            continue
        em_parag = False
    return out

def valor_art(num):
    d = re.sub(r"\D", "", num)
    return int(d) if d else 0

def _expande_municipais(t):
    """'Leis Municipais de X nº A/AAAA, nº B/BBBB e nº C/CCCC' -> uma menção por lei."""
    def rep(m):
        nums = re.findall(r"n[ºo°]?\s*([\d.]+)/(\d{4})", m.group(0))
        return ". ".join("Lei municipal de %s nº %s/%s" % (m.group(1).strip(), a, b) for a, b in nums) or m.group(0)
    return re.sub(r"(?i)Leis?\s+municipal(?:is)?\s+de\s+([A-ZÀ-Ý][\wÀ-ÿ\s]{2,30}?)\s*(?=n[ºo°]\s*[\d.]+/\d{4})"
                  r"(?:n[ºo°]\s*[\d.]+/\d{4}(?:\s*,?\s*e?\s*n[ºo°]?\s*[\d.]+/\d{4})*)", rep, t)

def artigos_cit(txt):
    """[(label, num)] — uma entrada por artigo: 'art. 1.694 · CC'."""
    t = re.sub(r"[\u00a0]", " ", txt or "")
    t = re.sub(r"^[\s\-–—●•*]+", "", t)
    t = _limpa_parenteses(_expande_municipais(t))
    marcas = [(m.start(), m.end(), m.group(0)) for m in DIPLOMA_RE.finditer(t)]
    segs = []
    if not marcas:
        segs.append([None, t, None])
    else:
        if marcas[0][0] > 0:
            segs.append([None, t[:marcas[0][0]], None])
        for i, (a, b, nome) in enumerate(marcas):
            fim = marcas[i + 1][0] if i + 1 < len(marcas) else len(t)
            segs.append([nome, t[b:fim], None])
    # segmento sem artigo cujo cabeçalho foi "roubado" do anterior ("..., do CPC") devolve o nome ao anterior
    for s in segs:
        s[2] = artigos_do_bloco(s[1])
    for i, s in enumerate(segs):
        if s[0] and not s[2] and i > 0 and segs[i - 1][0] is None and segs[i - 1][2]:
            segs[i - 1][0], s[0] = s[0], None
    out = []
    for nome, corpo, arts in segs:
        if nome is None:
            m = re.search(r"(?i)[,;:.]?\s*(?:d[oa]s?|n[oa])\s+(" + DIPLOMA_PAT + r")\s*$", corpo)
            if m:
                nome, corpo = m.group(1), corpo[:m.start()]
        if nome is None and not arts:
            continue
        dip = norm_diploma(nome) if nome else ("diploma não indicado" if arts else None)
        if not dip:
            continue
        arts = artigos_do_bloco(corpo) if nome is not None else arts
        if not arts:
            if not (out and out[-1][0].rsplit(' · ', 1)[-1].split(' (sem artigo')[0] == dip):
                out.append([f"{dip} (sem artigo indicado)", 0])
            continue
        for num, suf in arts:
            n_txt = num + "º" if (suf == "" and "." not in num and valor_art(num) <= 9) else num + suf
            out.append([f"art. {n_txt} · {dip}", valor_art(num)])
    vistos, uniq = set(), []
    for lab, num in out:
        if lab not in vistos:
            vistos.add(lab)
            uniq.append([lab, num])
    return uniq


# ------------------------------------------------------------------ jurisprudência
TRIBUNAIS = (r"(?:STF|STJ|TST|TSE|TNU|STM|TRF\s?-?\s?\d|TRT\s?-?\s?\d{1,2}|"
             r"TJ-?PE|TJ-?DFT|TJ-?MG|TJ-?GO|TJ-?SP|TJ-?RJ|TJ-?BA|TJ-?CE|TJ-?RN|TJ[A-Z]{2})")
TIPOS_CASO = (r"(?:EAREsp|AREsp|EREsp|REsp|AgInt|AgRg|EDcl|ADI|ADPF|ADC|ADO|ARE|RE|"
              r"RMS|MS|RHC|HC|SL|CC|Pet|MI)")
# controle concentrado do STF: os números são curtos (ADC 41, ADC 58, ADI 1, ADPF 54) e o
# padrão de número acima (3+ caracteres) os descartava — a citação existia na ementa e não
# entrava na lista de [jurisprudência]
CONTROLE = r"(?:ADI|ADC|ADPF|ADO)"
CIT_INI = re.compile(
    r"(?:(?<=[.;:•\-–])\s*|(?<=,)\s+|\s+e\s+|^)"
    r"(?=(?:" + TRIBUNAIS + r"|S[úu]mulas?|Tema|" + TIPOS_CASO +
    r"|Incidente|Apela[çc][ãa]o|Agravo|Embargos|Pedido\s+de|Proc\.))", re.I)
UF_TJ = {"17": "TJPE", "13": "TJMG", "07": "TJDFT", "09": "TJGO", "26": "TJSP",
         "19": "TJRJ", "21": "TJRS", "05": "TJBA", "06": "TJCE"}
TEMA_CASO = {}
# sigla + nome por extenso (o leitor confere a sigla sem sair da lista)
AI_LAB, AC_LAB, IAC_LAB = ("AI (Agravo de Instrumento)", "AC (Apelação Cível)",
                           "IAC (Incidente de Assunção de Competência)")

def norm_trib(t):
    t = re.sub(r"[\s.]", "", t).upper()
    return {"TJ-PE": "TJPE", "TJDFT": "TJDFT"}.get(t, t)

def _trib_do_texto(p, anterior=None):
    m = re.search(TRIBUNAIS, p, re.I)
    if m:
        return norm_trib(m.group(0))
    l = sem_acento(p)
    if re.search(r"sumula vinculante|\brepercussao geral\b|\badi\b|\badpf\b|\badc\b|\bado\b|\bmi\b", l):
        return "STF"
    if re.search(r"/stf\b|\bstf\b", l):
        return "STF"
    if re.search(r"/stj\b|\bstj\b|repetitivos?\b|\baresp\b|\bresp\b|\beresp\b|\bearesp\b|"
                 r"\bagint\b|\bagrg\b|\bedcl\b|\brms\b|\bsl\b|\bpet\b", l):
        return "STJ"
    if re.search(r"\bre\b|\bare\b", l):
        return "STF"
    m = re.search(r"\.8\.(\d{2})\.", p)
    if m:
        return UF_TJ.get(m.group(1), "TJ-" + m.group(1))
    return anterior

def _id_decisao(p):
    """(rank, tipo, numero, uf, tema) da citação."""
    l = sem_acento(p)
    tema = re.search(r"tema\s+(?:repetitivo\s+)?n?[ºo°]?\s*([\d.]+)", l)
    sumu = re.search(r"s[úu]mulas?\s*(vinculante\s*)?n?[ºo°]?\s*([\d.]+)", l)
    caso = re.search(r"\b(" + TIPOS_CASO + r")\b\s*(?:n[ºo°]?\s*)?([\d][\d.\-]{2,}(?:-\d+)?)"
                     r"(?:\s*/\s*([A-Za-z]{2}|[0-9]{1,4})\b)?", p, re.I)
    # rótulo único por tipo: a sigla com o nome por extenso — o mesmo tipo aparece no texto
    # como "AI" e como "Agravo de Instrumento", e as duas formas têm de virar UMA entrada
    TJ_TIPOS = ((r"apela[çc][ãa]o(?:\s*/\s*remessa\s+necess[áa]ria)?\s*c[íi]vel", AC_LAB),
                (r"agravo\s+de\s+instrumento", AI_LAB),
                (r"incidente\s+de\s+assun[çc][ãa]o\s+de\s+compet[êe]ncia", IAC_LAB),
                (r"pedido\s+de\s+efeito\s+suspensivo(?:\s+[àa]\s+apela[çc][ãa]o)?", "Pedido de Efeito Suspensivo"),
                (r"hc\s+c[íi]vel", "HC Cível"), (r"proc\.", "Proc."),
                (r"iac\b", IAC_LAB), (r"\bai\b", AI_LAB), (r"\bac\b", AC_LAB))
    mtj = None
    for pad, rot in TJ_TIPOS:
        mm = re.search(pad + r"\s*:?\s*n?[ºo°]?\s*([\d][\d.\-]{3,}(?:/[0-9]{1,4})?)", l)
        if mm:
            mtj = (rot, mm.group(1))
            break
    if tema:
        return (0, "Tema", tema.group(1), None, "Tema " + tema.group(1))
    if sumu:
        nums = [sumu.group(2)] + re.findall(r"\be\s+n?[ºo°]?\s*([\d.]+)", l[sumu.end():])
        return (1, "Súmula Vinculante" if sumu.group(1) else "Súmula", nums[0], None,
                ("Súmula Vinculante " if sumu.group(1) else "Súmula ") + nums[0], nums)
    if mtj:
        return (2, mtj[0], mtj[1], None, f"{mtj[0]} {mtj[1]}")
    if caso:
        base = {"earesp": "AREsp", "aresp": "AREsp", "eresp": "EREsp", "resp": "REsp",
                "are": "ARE", "re": "RE", "agint": "AREsp", "agrg": "AREsp", "edcl": "AREsp",
                "rms": "RMS", "ms": "MS", "hc": "HC", "rhc": "RHC", "sl": "SL", "cc": "CC",
                "pet": "Pet", "mi": "MI", "adi": "ADI", "adpf": "ADPF",
                "adc": "ADC"}.get(caso.group(1).lower())
        num, extra = caso.group(2), caso.group(3)
        uf = extra.upper() if (extra and not extra.isdigit()) else None
        if extra and extra.isdigit():
            num = num + "/" + extra
        # AgInt no AREsp X -> mantém o recurso-base, mas sem perder o tipo quando ele é o próprio
        tipo_orig = caso.group(1)
        if tipo_orig in ("agint", "agrg", "edcl") and base == "AREsp":
            base = "AREsp"
        rot = base + " " + num + (("/" + uf) if uf else "")
        return (2, base, num, uf, rot)
    mcon = re.search(r"\b(" + CONTROLE + r")\b\s*(?:n[ºo°]?\s*)?(\d{1,4})(?:-(\d+))?\b"
                     r"(?:\s*/\s*([A-Za-z]{2})\b)?", p, re.I)
    if mcon:
        base = mcon.group(1).upper()
        num = mcon.group(2) + (("-" + mcon.group(3)) if mcon.group(3) else "")
        uf = (mcon.group(4) or "").upper() or None
        return (2, base, num, uf, base + " " + num + (("/" + uf) if uf else ""))
    return None

def _expande_cit_jur(t):
    marcas = [m.start() for m in CIT_INI.finditer(t)]
    if not marcas:
        return [t]
    if marcas[0] > 0:
        marcas = [0] + marcas
    return [t[a:b].strip(" .;,-–") for a, b in zip(marcas, marcas[1:] + [len(t)])]

def decisoes_cit(txt):
    """[(label, rank)] — uma entrada por decisão, com tribunal emissor e citação normalizada."""
    t = re.sub(r"[\u00a0]", " ", txt or "")
    t = re.sub(r"^[\s\-–—●•*]+", "", t)
    t = re.sub(r"\s*;\s*", ". ", t)
    pecas = [p for p in _expande_cit_jur(t) if p.strip()]
    # 1ª passada: pares Tema <-> caso líder, para rotular igual em todo o acervo
    for p in pecas:
        ident = _id_decisao(p)
        if not ident or ident[0] != 0:
            continue
        trib = _trib_do_texto(p)
        m = re.search(r"\b(" + TIPOS_CASO + r")\b\s*(?:n[ºo°]?\s*)?([\d][\d.\-]{2,}(?:-\d+)?)"
                      r"(?:\s*/\s*([A-Za-z]{2}|[0-9]{1,4})\b)?", p, re.I)
        if m and trib:
            base = {"earesp": "AREsp", "aresp": "AREsp", "eresp": "EREsp", "resp": "REsp", "are": "ARE",
                    "re": "RE", "adi": "ADI", "adpf": "ADPF", "agint": "AREsp", "agrg": "AREsp",
                    "edcl": "AREsp", "rms": "RMS", "ms": "MS", "hc": "HC", "sl": "SL"}.get(m.group(1).lower(), m.group(1).upper())
            g3 = m.group(3)
            caso = base + " " + m.group(2) + (("/" + (g3.upper() if not g3.isdigit() else g3)) if g3 else "")
            TEMA_CASO.setdefault((trib, ident[4]), caso)
    # 2ª passada: emite
    out, anterior = [], None
    for p in pecas:
        trib = _trib_do_texto(p, anterior)
        if trib:
            anterior = trib
        ident = _id_decisao(p)
        if not ident or not trib:
            continue
        rank, tipo, num, uf, rot = ident[:5]
        if rank == 0:
            caso = TEMA_CASO.get((trib, rot))
            rot = rot + (f" ({caso})" if caso else "")
        out.append([f"{trib} · {rot}", rank])
        if len(ident) > 5:                      # "Súmulas 358 e 621": uma entrada por súmula
            for extra in ident[5][1:]:
                out.append([f"{trib} · Súmula {extra}", 1])
    vistos, uniq = set(), []
    for lab, rank in out:
        if lab not in vistos:
            vistos.add(lab)
            uniq.append([lab, rank])
    return uniq


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
    # citações por artigo e por decisão — 1ª passada só para casar Tema <-> caso líder em TODO
    # o acervo (senão um registro rotularia o Tema antes de outro revelar o REsp de origem)
    for rec in out:
        if rec["j"]:
            decisoes_cit(rec["j"])
    for rec in out:
        rec["la"] = artigos_cit(rec["l"])
        rec["ja"] = decisoes_cit(rec["j"]) if rec["j"] else []
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
