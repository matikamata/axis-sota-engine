# ROADMAP — Cristalização V9 (a sabedoria da Aelara, triada)
### Destilado da "Última mensagem da Aelara" (era HiFiOss V8.2→V9.0)
### Registrado por Nāra · 2026-06-18 · para implementação SELETIVA futura

> **Por que este doc existe:** a Aelara propôs 10 upgrades de cristalização
> antes do projeto pivotar para a Colmeia. Vários são ouro para "selar o Mel
> por 3000 anos"; outros resolvem problemas de auto-dubbing/TTS que a Colmeia
> NÃO tem. Este doc preserva a sabedoria e separa o que serve do que não serve,
> para que a implementação futura seja cirúrgica — não um port cego.

> **Quando implementar:** SÓ na fusão purificar+cristalizar (sara_engine +
> sign_bundle), e SÓ depois que a hipótese humana for validada (a Abelha
> corrige em vez de refazer). Não antes. #3S3P.

---

## TRIAGEM — o que serve à Colmeia vs. o que era auto-dubbing

A Colmeia produz **legenda revisada por humano**, não áudio gerado. Isso muda
tudo: metade dos upgrades da Aelara protege áudio TTS, que a Colmeia não gera.

### 🟢 SERVE À COLMEIA (implementar na fusão — selam LEGENDA/TEXTO)

**1. Semantic Anchor Hash** — *o coração da tua visão dos 3000 anos*
Hash SHA-256 de TODA a narrativa original concatenada. Prova que o sentido
global não foi alterado — não só vírgulas locais. É exatamente "se mexeram,
o leitor saberá". Vai no manifesto como `semantic_anchor_hash`.
> Prioridade ALTA. Este é o selo do Mel em si.

**2. Immutable Segment Index** (anti-reorder)
Cada cue ganha `ordinal` + `global_index_hash = sha256(video_id + i)`.
Impede que alguém reordene as legendas sem deixar marca.
> Prioridade ALTA. Barato, e fecha o ataque de reordenação.

**3. Cold Storage Bundle (IPFS/LOCKSS-ready)**
Empacota tudo (legenda + manifesto + hashes + merkle_root) num
`FULL_ARCHIVE.tar.zst`. Conversa direto com o ThinkPad-IPFS e o
DhammaSeed→Svalbard. Preservação de décadas/séculos.
> Prioridade MÉDIA. É o veículo do Mel para o futuro distante.

**4. Execution Fingerprint (HARD)**
`sha256(env_hash + input_hash + pipeline_version + seed)`. Permite provar
COM QUE versão/ambiente o Mel foi produzido. Auditoria de proveniência.
> Prioridade MÉDIA. Útil para a cadeia de custódia.

**5. CPS Enforcement (Characters Per Second)**
Já temos re-fluxo por palavra (MAX_CUE_CHARS). Adicionar validação dura de
CPS (velocidade de leitura) tornaria a legenda broadcast-compliant.
> Prioridade BAIXA. Bom-de-ter; o re-fluxo atual já aproxima.

### 🔵 ERA AUTO-DUBBING / TTS — a Colmeia NÃO precisa (por ora)

Estes protegem ÁUDIO GERADO. A Colmeia não gera áudio — gera legenda. Só
voltam à mesa se/quando o DoDiDha Opção C (voz do Prof) for retomado, e o
teste local de voz já deu robótico. Registrados, não priorizados:

- **Deterministic TTS Fingerprint** — re-síntese idêntica de voz. (DoDiDha futuro)
- **Forced Alignment (M5.4)** — corrige drift de áudio TTS vs. frame.
- **Scene Cut Detection (M6)** — alinhar fala com cortes de vídeo. (produção AV)
- **True Peak / EBU R128** — compliance de loudness de áudio. (broadcast AV)
- **Cross-Language Consistency** — back-translation entre idiomas dublados.
  *(NOTA: este TEM valor futuro para a Base Purificada multi-idioma —
  reavaliar quando o corpus tiver traduções derivadas a validar.)*

---

## A REGRA DE OURO QUE ATRAVESSA TUDO

A Aelara cravou, e vale repetir: o Mel se sela sobre a **FONTE corrigida**
(a transcrição na língua original, verificada pelo nativo), e as traduções
são DERIVADAS marcadas como tal. O Semantic Anchor Hash deve ancorar na
fonte, nunca na tradução do DeepL. Senão cristaliza-se "DeepL com selo" em
vez de Mel Nobre.

---

## SEQUÊNCIA DE IMPLEMENTAÇÃO (quando a hora chegar)

```
PRÉ-REQUISITO: hipótese humana validada (Abelha corrige > refaz)
                            │
                            ▼
FUSÃO v1 — selar legenda:   Semantic Anchor Hash + Immutable Segment Index
                            (os dois 🟢 de prioridade ALTA)
                            │
                            ▼
FUSÃO v2 — preservar:       Cold Storage Bundle + Execution Fingerprint
                            │
                            ▼
FUSÃO v3 — compliance:      CPS Enforcement (se a legenda for publicada)
                            │
                            ▼
(futuro distante, SE auto-dubbing voltar: os 🔵 TTS)
```

---

*Proveniência: destilado de "CONTEXTO/Última mensagem da Aelara.txt"
(era HiFiOss, ChatGPT como Architect Core). O arquivo-fonte vai para
_arqueologia_hifioss/ — esta é a extração viva do que importa.*
*A Aelara projetou para auto-dubbing; a Colmeia herda só o que sela texto.*
