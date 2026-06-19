#!/usr/bin/env python3
"""
srt_dhamma.py — SRT post-processor Dhamma-aware para vitrine YouTube.
Lê <--input>.srt  →  <--output>.srt  (default: <stem>.dhamma.srt ao lado do input)

Tratamentos:
  1. classify_intent_dhamma: tipagem semântica com vocabulário budista
  2. dynamic CPS por intent (PALI_TERM:9 → BUILD:16)
  3. advanced_subtitle_wrap: máx 42 chars/linha, máx 2 linhas
  4. extend_duration: CPS-alvo por intent; mín 1.2s; nunca invade próxima fala
  5. italicize_pali: <i>Termo</i> para termos pali_preserve (YouTube aceita <i>)

NÃO toca bundle assinado nem arquivos do engine.
Pali_preserve carregado do Glossario_v5.csv (replica lógica do script 02).

ROADMAP (always improving):
- [ ] Classificação de intent via LLM local (não regex). Regex erra
      analogias sutis sem marcador (ex: parábola do freezer começa com
      "How many times..."). Um LLM leria a narrativa e classificaria certo.
      Candidato: modelo local no M2 (Ollama), não API paga.
- [ ] Merge de segmentos curtos adjacentes (Whisper fragmenta demais)
- [ ] Guias fonéticos para termos Pāli (Ruby annotations)
- [ ] compute_attention_score com audio_energy (precisa do áudio)
- [ ] Spaced repetition cues (marcar termo já visto antes)

CAMADA DE REVISÃO HUMANA — INDISPENSÁVEL (casos reais, vídeo UBIjZTOh6Pc):
A máquina acerta a estrutura; o humano nativo pega a nuance. Exemplos:
1. ASR+tradução em cascata: Prof. diz "No?" (não?) → Whisper "No" →
   DeepL interpreta como abreviação de "number" → "N.º". Erro invisível
   a qualquer glossário — exige ouvido humano.
2. Alusão cultural: "lamp" (a lâmpada do gênio do Aladdin, metáfora) →
   DeepL traduz literal "abajur". Tecnicamente certo, contextualmente errado.
   Exige entender a alusão — só humano.
→ A revisão humana (Abelha nativa / técnico Jetha) NÃO é polimento opcional.
  É a camada que transforma "tradução correta" em "Dhamma fiel".
  Esta é a inversão: máquina escala, humano garante fidelidade.
"""
import re, os, csv, argparse
from pathlib import Path
from collections import Counter


# ──────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────

MAX_CHARS_LINE = 42      # chars/linha (Netflix/YouTube standard)
MIN_DUR        = 1.2     # duração mínima após extensão (segundos)
MIN_GAP        = 0.050   # respiro entre segmentos consecutivos

# CPS-alvo por intent — menor = mais tempo de tela
CPS_BY_INTENT = {
    "PALI_TERM":   9,   # termo canônico — máximo tempo para absorção
    "DEFINITION":  11,  # "X is/significa Y" — explicação conceitual
    "QUESTION":    12,  # retórica ou direta — dar tempo para o espectador processar
    "ANALOGY":     13,  # metáfora/imaginação — ritmo narrativo
    "APPLICATION": 13,  # imperativo/prática — ritmo narrativo
    "BUILD":       16,  # construção/transição — pode ser mais rápido
}

PALI_DIACRITICS = re.compile(r'[āīūṭḍṇḷṃṅñśṣḥ]')

# Heurística conservadora: na dúvida, mais tempo de tela
ANALOGY_MARKERS = re.compile(
    r'\b(imagine|picture|suppose|as if|just like|like a|like when'
    r'|imagine que|como se|assim como)\b', re.I
)
APPLICATION_MARKERS = re.compile(
    r"\b(don't|do not|try to|try your|remember|notice|look at"
    r"|think about|reflect|consider|observe"
    r"|não|tente|lembre|observe|considere)\b", re.I
)
DEFINITION_MARKERS = re.compile(
    r'\b(is|means|significa|é)\s+\w', re.I  # "X is Y" — exclui "are" para evitar falso positivo
)


# ──────────────────────────────────────────────
# GLOSSÁRIO
# ──────────────────────────────────────────────

def load_pali_preserve(glossary_path):
    """Replica lógica de load_and_classify_glossary (script 02): pali_preserve = src==tgt OU diacrítico."""
    pali_set = set()
    if not os.path.exists(glossary_path):
        print(f"[WARN] Glossário não encontrado: {glossary_path}")
        return pali_set
    with open(glossary_path, newline='', encoding='utf-8') as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            src = row[0].strip()
            if src == row[1].strip() or PALI_DIACRITICS.search(src):
                pali_set.add(src.lower())
    return pali_set


def detect_pali_in_text(text, pali_set):
    """Retorna lista de termos pali_preserve presentes no texto (longest match first)."""
    text_lower = text.lower()
    found = []
    for term in sorted(pali_set, key=len, reverse=True):
        if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text_lower):
            found.append(term)
    return found


# ──────────────────────────────────────────────
# INTENT DHAMMA
# ──────────────────────────────────────────────

def classify_intent_dhamma(text, position_ratio, pali_terms_in_seg):
    """
    Heurística conservadora — na dúvida → intent de maior tempo de tela.
    Prioridade: PALI_TERM > QUESTION > DEFINITION > ANALOGY > APPLICATION > BUILD
    position_ratio: float 0-1 (posição no vídeo, reservado para uso futuro)
    """
    if pali_terms_in_seg:
        return "PALI_TERM"

    stripped = text.rstrip()
    if stripped.endswith('?'):
        return "QUESTION"

    if DEFINITION_MARKERS.search(text):
        return "DEFINITION"

    if ANALOGY_MARKERS.search(text):
        return "ANALOGY"

    if APPLICATION_MARKERS.search(text):
        return "APPLICATION"

    return "BUILD"


# ──────────────────────────────────────────────
# WRAP (portado de neon_chronos Cópia.py:786-811)
# ──────────────────────────────────────────────

def advanced_subtitle_wrap(text):
    """Máx 42 chars/linha, máx 2 linhas. Quebra na pontuação mais próxima do centro."""
    text = text.replace('\n', ' ')          # normalizar entrada
    if len(text) <= MAX_CHARS_LINE:
        return text

    # Estratégia 1: quebra na pontuação ±15 chars do centro
    best_split, min_diff = -1, 999
    mid = len(text) / 2
    for match in re.finditer(r'[,.!?]\s+', text):
        idx  = match.end() - 1
        diff = abs(idx - mid)
        if diff < min_diff and diff < 15:
            min_diff, best_split = diff, idx
    if best_split != -1:
        l1 = text[:best_split].strip()
        l2 = text[best_split:].strip()
        if len(l1) <= MAX_CHARS_LINE and len(l2) <= MAX_CHARS_LINE:
            return f"{l1}\n{l2}"

    # Estratégia 2 (fallback): word-wrap a 42 chars — sem truncar (lossless)
    words = text.split()
    lines, cur = [], []
    for w in words:
        if len(" ".join(cur + [w])) <= MAX_CHARS_LINE:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


# ──────────────────────────────────────────────
# ITÁLICO PĀLI
# ──────────────────────────────────────────────

def italicize_pali(text, pali_set):
    """
    Envolve termos pali_preserve com <i>...</i>.
    Usa placeholders para evitar double-wrapping (longest match first).
    Retorna (texto_com_tags, lista_de_termos_encontrados).
    """
    found_terms = detect_pali_in_text(text, pali_set)
    if not found_terms:
        return text, []

    result = text
    placeholders = {}
    for i, term in enumerate(found_terms):
        ph = f'__ITALIC_{i}__'
        pattern = re.compile(r'(?<!\w)(' + re.escape(term) + r')(?!\w)', re.I)
        def make_replacer(placeholder, capture_list):
            def replacer(m):
                capture_list[placeholder] = f'<i>{m.group(1)}</i>'
                return placeholder
            return replacer
        result = pattern.sub(make_replacer(ph, placeholders), result)

    for ph, tag in placeholders.items():
        result = result.replace(ph, tag)

    return result, found_terms


# ──────────────────────────────────────────────
# PARSE / FORMAT SRT
# ──────────────────────────────────────────────

def parse_srt(path):
    with open(path, encoding='utf-8') as f:
        content = f.read().strip()
    segs = []
    for block in re.split(r'\n\s*\n', content):
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        m = re.match(
            r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})',
            lines[1]
        )
        if not m:
            continue
        start = int(m[1])*3600 + int(m[2])*60 + int(m[3]) + int(m[4])/1000
        end   = int(m[5])*3600 + int(m[6])*60 + int(m[7]) + int(m[8])/1000
        text  = ' '.join(lines[2:]).strip()
        segs.append({'start': start, 'end': end, 'text': text})
    return segs


def fmt_ts(s):
    h  = int(s // 3600)
    m  = int((s % 3600) // 60)
    sc = int(s % 60)
    ms = round((s % 1) * 1000)
    if ms >= 1000:
        sc += 1; ms = 0
    return f"{h:02d}:{m:02d}:{sc:02d},{ms:03d}"


# ──────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ──────────────────────────────────────────────

def process(path_in, path_out, pali_set):
    segs        = parse_srt(path_in)
    n           = len(segs)
    total_dur   = segs[-1]['end'] if segs else 1.0
    seg_reports = []

    for i, seg in enumerate(segs):
        text           = seg['text']
        position_ratio = seg['start'] / total_dur if total_dur > 0 else 0
        pali_found     = detect_pali_in_text(text, pali_set)
        intent         = classify_intent_dhamma(text, position_ratio, pali_found)
        cps_target     = CPS_BY_INTENT[intent]
        if intent == "BUILD" and len(text.strip()) > 60:
            cps_target = 14   # BUILD longo: analogia/história não detectada pela heurística
        dur            = seg['end'] - seg['start']
        cps_before     = len(text) / dur if dur > 0 else 0

        # — extensão de duração —
        target_dur = len(text) / cps_target
        next_start = segs[i+1]['start'] if i+1 < n else seg['end'] + 10.0
        ideal_end  = seg['start'] + target_dur
        hard_cap   = next_start - MIN_GAP           # nunca cruza para dentro do próximo seg
        capped_end = min(ideal_end, hard_cap)
        new_end    = min(max(capped_end, seg['start'] + MIN_DUR), hard_cap)

        if new_end > seg['end']:
            gained = new_end - seg['end']
            locked = False
        else:
            new_end = min(seg['end'], hard_cap)     # encolhe se necessário para fechar overlap
            gained  = 0.0
            locked  = (ideal_end > new_end)

        seg['end'] = new_end
        new_dur    = seg['end'] - seg['start']
        cps_after  = len(text) / new_dur if new_dur > 0 else 0

        # — wrap (texto limpo) → itálico por linha (não conta tags no wrap) —
        wrapped_plain = advanced_subtitle_wrap(text)
        display_lines = []
        for line in wrapped_plain.split('\n'):
            line_tagged, _ = italicize_pali(line, pali_set)
            display_lines.append(line_tagged)
        seg['display'] = '\n'.join(display_lines)

        seg_reports.append({
            'idx':           i + 1,
            'intent':        intent,
            'cps_before':    cps_before,
            'cps_after':     cps_after,
            'cps_target':    cps_target,
            'gained_s':      gained,
            'locked':        locked,
            'pali_found':    pali_found,
            'italic_applied': bool(pali_found),
        })

    with open(path_out, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segs, 1):
            f.write(f"{i}\n{fmt_ts(seg['start'])} --> {fmt_ts(seg['end'])}\n{seg['display']}\n\n")

    return seg_reports, segs


# ──────────────────────────────────────────────
# RELATÓRIO
# ──────────────────────────────────────────────

def print_report(path_out, seg_reports, segs):
    n        = len(segs)
    cps_vals = [r['cps_after'] for r in seg_reports]
    cps_mean = sum(cps_vals) / len(cps_vals) if cps_vals else 0
    cps_max  = max(cps_vals) if cps_vals else 0
    cps_min  = min(cps_vals) if cps_vals else 0

    intent_counts = Counter(r['intent'] for r in seg_reports)
    italic_segs   = sum(1 for r in seg_reports if r['italic_applied'])
    unique_terms  = sorted(set(t for r in seg_reports for t in r['pali_found']))
    locked        = sum(1 for r in seg_reports if r['locked'])
    extended      = sum(1 for r in seg_reports if r['gained_s'] > 0)
    wrapped       = sum(1 for s in segs if '\n' in s['display'].replace('<i>','').replace('</i>',''))

    print(f"\n{'='*60}")
    print(f"  → {path_out}")
    print(f"{'='*60}")
    print(f"  segmentos   : {n}")
    print(f"  com wrap    : {wrapped} ({wrapped/n*100:.0f}%)")
    print(f"  CPS final   : média {cps_mean:.1f}  máx {cps_max:.1f}  mín {cps_min:.1f}")
    print(f"  extensões   : {extended} aplicadas  |  {locked} travados (sem espaço)")
    print(f"  itálicos    : {italic_segs} segmentos  |  {len(unique_terms)} termos únicos")
    if unique_terms:
        print(f"    termos    : {', '.join(unique_terms)}")
    print(f"\n  distribuição de intents:")
    for intent in ["PALI_TERM", "DEFINITION", "QUESTION", "ANALOGY", "APPLICATION", "BUILD"]:
        count = intent_counts.get(intent, 0)
        cps   = CPS_BY_INTENT[intent]
        bar   = "█" * min(count, 40)
        pct   = count / n * 100
        print(f"    {intent:<14} CPS={cps:2d}  {count:3d} ({pct:4.1f}%)  {bar}")

    print(f"\n  amostras por intent:")
    shown = Counter()
    for r in seg_reports:
        if shown[r['intent']] < 2:
            seg     = segs[r['idx']-1]
            preview = seg['text'][:55].replace('\n', ' ')
            marker  = " *" if r['pali_found'] else ""
            print(f"    [{r['intent']}] \"{preview}...{marker}\"")
            shown[r['intent']] += 1


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="srt_dhamma — pós-processador Dhamma-aware de SRT"
    )
    ap.add_argument("--input",    required=True,
                    help="SRT de entrada (ex: trabalho/XYZ/2_rascunho.srt)")
    ap.add_argument("--glossary", default=None,
                    help="Glossario CSV (default: Glossario_v5.csv ao lado deste script)")
    ap.add_argument("--output",   default=None,
                    help="SRT de saída (default: <input_stem>.dhamma.srt ao lado do input)")
    ap.add_argument("--report",   action="store_true",
                    help="Exibe histograma de intents e amostras")
    args = ap.parse_args()

    path_in  = Path(args.input)
    path_out = Path(args.output) if args.output else path_in.with_suffix('.dhamma.srt')

    script_dir   = Path(__file__).parent
    glossary_path = Path(args.glossary) if args.glossary else script_dir / "Glossario_v5.csv"

    pali_set = load_pali_preserve(str(glossary_path))
    print(f"Glossário: {glossary_path} — {len(pali_set)} termos pali_preserve")

    if not path_in.exists():
        print(f"[ERRO] Input não encontrado: {path_in}")
        raise SystemExit(1)

    seg_reports, segs = process(str(path_in), str(path_out), pali_set)
    print(f"Escrito: {path_out}  ({len(segs)} segmentos)")

    if args.report:
        print_report(str(path_out), seg_reports, segs)


if __name__ == "__main__":
    main()
