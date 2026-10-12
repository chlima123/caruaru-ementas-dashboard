# Ementas da Câmara Regional de Caruaru — dashboard com busca semântica

Dashboard **estático** (um único `index.html`) de busca semântica sobre os pareceres e manifestações
da 2ª Procuradoria de Justiça Cível junto às Turmas da **Câmara Regional de Caruaru** (MPPE).

- **No ar:** https://caruaru-ementas.vercel.app *(acesso restrito, com gate de senha)*
- **Fonte do acervo:** pasta *Ementas* no Google Drive, alimentada por um fluxo automático que lê os
  anexos PDF dos e-mails com o assunto `processar ementas`, gera a nota estruturada no Obsidian e
  publica a versão markdown no Drive.
- **Espelho privado do acervo:** `chlima123/caruaru-ementas` (repositório privado, só os `.md`).

Este repositório contém **apenas o código** que constrói e publica o dashboard. Nenhum texto de
parecer, nenhuma senha e nenhum link de pasta estão versionados aqui — ver a seção *Privacidade*.

## O que o dashboard faz

| Recurso | Como |
|---|---|
| **Busca semântica** | Descreva o caso em linguagem natural ("plano de saúde negou o remédio de crescimento"). Os vetores do acervo já vêm embutidos no HTML; o navegador calcula apenas o vetor da consulta (transformers.js) e ordena por similaridade de cosseno. **Nada é enviado a servidor nenhum.** |
| **Busca por texto exato** | Sem acento, com realce dos termos — para número de processo e citações literais. |
| **Filtros** | Classe processual, tipo de documento, mês e relator; aplicam-se às duas buscas. |
| **Leitor** | Dados do processo, partes e a ementa integral (ou o teor do documento, quando o anexo não tem ementa formal — COTAs, promoções, manifestações). Botões *Copiar ementa* e *Imprimir*. |
| **KPIs** | Documentos no acervo, com/sem ementa, classes, relatores e período. |

## Arquitetura

```
Drive "Ementas" (.md)          ← cron do perfil sherpa: e-mail "processar ementas" → vault → Drive
        │  pull_fonte.py            (baixa só o que mudou; idempotente por conteúdo)
        ▼
   fonte/*.md
        │  build_dados.py           (parser + embeddings POR TRECHO, max-pool)
        ▼
   dados.json  ──────────────►  montar.py  (injeta no template.html, põe o gate, valida com node --check)
                                     ▼
                                index.html  ──►  deploy.py  (API da Vercel + prova por sha1)
                                     ▲
                                verificar.py  (Chrome real: gate, texto, filtros, semântica)
```

| Arquivo | Papel |
|---|---|
| `pull_fonte.py` | Baixa da pasta do Drive os `.md` novos/alterados (usa o token OAuth da conta que tem acesso). |
| `build_dados.py` | Parseia cada nota (`Dados do processo` + `Ementa`/`Teor do documento`), monta os registros e calcula os **embeddings por trecho** (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dims, normais em L2, guardados em base64). |
| `template.html` | O dashboard em si (HTML + CSS + JS). Placeholders `__DATA__`, `__DRIVE__` e `__GATE__`. |
| `montar.py` | Injeta dados/config/senha, valida os blocos `<script>` com `node --check` e exige que o gate entre **antes de `</body>`**. |
| `deploy.py` | Cria/resolve o projeto na API da Vercel, zera `ssoProtection`/`passwordProtection` (projeto novo nasce pedindo login Vercel) e **confere o sha1 do que ficou no ar**. |
| `verificar.py` | Verificação no Chrome real (Playwright): gate aceita/bloqueia, KPIs, lista, texto exato, filtros e duas consultas semânticas que devem devolver resultados **diferentes** (prova que o `await` do pipeline existe e não caiu no fallback de token). |
| `config.json` *(local)* | Link da pasta no Drive e ids. Fora do repositório. |
| `dados.json`, `index.html`, `fonte/` *(gerados)* | Contêm o texto dos pareceres. Fora do repositório. |

## Busca semântica: por que por trecho, e não por documento

Embutir o documento inteiro (mean-pooling) **dilui** textos longos: o vetor fica central e casa com
qualquer consulta. Verificado neste acervo — a consulta "medicamento de crescimento negado pelo plano
de saúde" devolvia em **1º lugar** um caso de **água/esgoto**, com os dois casos certos fora do top-5
(e o mesmo ranking no modelo local em fp32, ou seja: não era a quantização do ONNX).

A correção foi fatiar o texto de busca em trechos de ~900 caracteres cortados em fim de frase e
pontuar o documento pelo **máximo** dos trechos (*max-pool*). Com isso o top-1 passou a ser o caso
correto, o de água caiu para 3º e voltou ao 1º quando a consulta era de fato sobre água (0,44 contra
0,33). O trecho de maior similaridade também vira a **amostra exibida na lista de resultados** —
mostra o pedaço que realmente casou com a consulta.

O ranking final é híbrido: `similaridade do melhor trecho + 0,30 × pontuação lexical normalizada`, para
não perder o acerto exato de número de processo e nome.

## Requisitos

- Python 3.9+ com `sentence-transformers`, `numpy` (build) e `playwright` (verificação)
- Node.js (só para o `node --check` do `montar.py`)
- Conta na Vercel: token em `~/.hermes/.env` como `VERCEL_API_TOKEN`
- Acesso de leitura à pasta do Drive: o `pull_fonte.py` usa um helper OAuth já autenticado
  (ajustável pela variável `EMENTAS_HELPER`)

## Como rodar

```bash
export PYTHONPATH="$HOME/Library/Python/3.9/lib/python/site-packages"

python3 pull_fonte.py     # Drive -> fonte/
python3 build_dados.py    # fonte/ -> dados.json (+ embeddings)
python3 montar.py         # dados.json + template.html -> index.html (com gate)
python3 deploy.py         # publica na Vercel e confere o sha1 do que está no ar

# verificação no Chrome real (local, com um servidor de arquivos)
python3 -m http.server 8899 &
python3 verificar.py http://127.0.0.1:8899/index.html
python3 verificar.py https://caruaru-ementas.vercel.app
```

O `index.html` publicado tem ~940 KB (o acervo inteiro + os vetores). O `build_dados.py` leva ~1 min
(baixa ~458 MB do modelo na primeira vez e fica em cache em `~/.cache/huggingface`).

## Privacidade — o que **não** está aqui

1. **O acervo.** `fonte/`, `dados.json` e `index.html` carregam os pareceres com nomes de partes,
   inclusive criança e adolescente. Estão no `.gitignore`.
2. **A senha do gate.** Vem de `--senha X`, da variável `EMENTAS_SENHA` ou de
   `~/.hermes/secrets/caruaru_ementas_senha.txt` — nunca literal no código. O `montar.py` **recusa
   montar** sem senha (a menos de `--sem-gate` explícito), para não publicar acervo aberto por acidente.
3. **O link da pasta no Drive.** Vem do `config.json` local; no template é o placeholder `__DRIVE__`.
   Sem ele, o botão *Abrir a pasta no Drive* nem aparece.

Vale saber: **o gate é client-side** (`prompt()` + comparação no HTML). Ele afasta visita casual e
buscadores (há `noindex,nofollow` no `<head>`), mas quem abrir o view-source lê o acervo. É o mesmo
padrão dos outros dashboards internos.

## Atualização automática

Cron `4411c58a13d8` (perfil default, diário às 09:00, sem agente) roda
`~/.hermes/scripts/caruaru_ementas_dashboard.sh`: puxa o Drive, e **só se o acervo mudou** (contagem ou
hash dos `.md`) reconstrói, republica e confere o sha1. Sem mudança, o stdout fica vazio (silencioso).

## Relacionado

- Skill `caruaru_ementas` (perfil sherpa) — gera as notas do vault, publica no Drive e espelha o
  acervo no repositório privado.
- Skill `vercel-static-dashboard-deploy` — receita de deploy pela API + verificação por sha1, gate de
  senha e painel de busca semântica.
- Nota no Obsidian: `015_HERMES/vercel/2026-10-11_Dashboard_Ementas_Caruaru.md`.
