#!/usr/bin/env python3
"""
srt_scheele.py — SRT post-processor para vitrine YouTube.
Lê *_clean.srt  →  *_scheele.srt

Tratamentos:
  1. advanced_subtitle_wrap: max 42 chars/linha, max 2 linhas,
     split preferencial na pontuação mais próxima do centro.
  2. Extensão de duração: se CPS > MAX_CPS (texto rápido demais),
     estende o 'end' até min(start + len/MAX_CPS, next_start - MIN_GAP).

NÃO toca bundle assinado nem arquivos do engine.
Portado de: ~/xps-snapshot/HiFiOss/DEPRECATED/neon_chronos (Cópia).py
"""
import re, os, sys

MAX_CPS          = 17.0   # chars/segundo — Netflix/YouTube broadcast standard
MAX_CHARS_LINE   = 42     # chars por linha (2 linhas × 42 = MAX_CHARS 84)
MAX_DURATION     = 6.0    # teto de extensão — segmento não cresce além disto
MIN_GAP          = 0.050  # segundos de respiro entre segmentos consecutivos
BUNDLE = "deliverables/RAW_LEGACY/UBIjZTOh6Pc/bundle"


def parse_srt(path):
    with open(path, encoding="utf-8") as f:
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
    ms = int(round((s % 1) * 1000))
    if ms == 1000:          # guard against float rounding
        sc += 1; ms = 0
    return f"{h:02d}:{m:02d}:{sc:02d},{ms:03d}"


def advanced_subtitle_wrap(text):
    """Portado de neon_chronos (Cópia).py:786 — split na pontuação + fallback word-wrap."""
    if len(text) <= MAX_CHARS_LINE:
        return text

    # Estratégia 1: split na pontuação mais próxima do centro (±15 chars)
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

    # Estratégia 2 (fallback): word-wrap forçado a 42, trunca em 2 linhas
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
    return "\n".join(lines[:2])


def process(path_in, path_out):
    segs    = parse_srt(path_in)
    n       = len(segs)
    ext_log = []

    for i, seg in enumerate(segs):
        text  = seg['text']
        dur   = seg['end'] - seg['start']
        cps   = len(text) / dur if dur > 0 else 0

        # — extensão de duração se CPS > teto —
        if cps > MAX_CPS:
            min_dur    = len(text) / MAX_CPS
            capped_dur = min(min_dur, MAX_DURATION)
            next_start = segs[i + 1]['start'] if i + 1 < n else seg['end'] + 10.0
            new_end    = min(seg['start'] + capped_dur, next_start - MIN_GAP)
            if new_end > seg['end']:           # só estende, nunca encolhe
                gained  = new_end - seg['end']
                new_cps = len(text) / (new_end - seg['start'])
                seg['end'] = new_end
            else:
                gained  = 0.0
                new_cps = cps                  # CPS_VIOLATION residual — sem espaço
            ext_log.append({
                'idx': i + 1, 'cps_before': cps, 'cps_after': new_cps,
                'gained_s': gained, 'text_preview': text[:50],
                'residual': new_cps > MAX_CPS,
            })

        seg['wrapped'] = advanced_subtitle_wrap(text)

    with open(path_out, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segs, 1):
            f.write(f"{i}\n{fmt_ts(seg['start'])} --> {fmt_ts(seg['end'])}\n{seg['wrapped']}\n\n")

    # métricas finais (sobre timestamps já corrigidos)
    cps_vals = [
        len(s['text']) / (s['end'] - s['start'])
        for s in segs if s['end'] > s['start']
    ]
    wrapped_count = sum(1 for s in segs if '\n' in s['wrapped'])

    return {
        'segs': n,
        'ext_log': ext_log,
        'cps_mean': sum(cps_vals) / len(cps_vals) if cps_vals else 0,
        'cps_max':  max(cps_vals) if cps_vals else 0,
        'cps_min':  min(cps_vals) if cps_vals else 0,
        'wrapped':  wrapped_count,
    }


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    for lang in ["pt", "en"]:
        src = f"{BUNDLE}/subtitles_{lang}_clean.srt"
        dst = f"{BUNDLE}/subtitles_{lang}_scheele.srt"
        if not os.path.exists(src):
            print(f"[{lang.upper()}] {src} não encontrado — pulando")
            continue

        r = process(src, dst)
        print(f"\n=== {lang.upper()} → {dst} ===")
        print(f"  segmentos : {r['segs']}")
        print(f"  com wrap  : {r['wrapped']} ({r['wrapped']/r['segs']*100:.0f}%)")
        print(f"  CPS final : média {r['cps_mean']:.1f}  máx {r['cps_max']:.1f}  mín {r['cps_min']:.1f}")
        fixed     = [e for e in r['ext_log'] if e['gained_s'] > 0]
        residuals = [e for e in r['ext_log'] if e['residual']]
        if fixed:
            print(f"  extensões : {len(fixed)} aplicadas, {len(residuals)} violações residuais")
            for e in fixed:
                tag = " [RESIDUAL]" if e['residual'] else ""
                print(f"    seg {e['idx']:3d}: CPS {e['cps_before']:.1f}→{e['cps_after']:.1f}"
                      f"  +{e['gained_s']:.3f}s{tag}  \"{e['text_preview']}...\"")
        if residuals:
            nonfixed = [e for e in residuals if e['gained_s'] == 0]
            if nonfixed:
                print(f"  sem espaço: {len(nonfixed)} segmentos travados por segmento seguinte imediato")
                for e in nonfixed:
                    print(f"    seg {e['idx']:3d}: CPS {e['cps_before']:.1f} — próximo segmento bloqueia extensão")
        else:
            print("  extensões : nenhuma — todos os segmentos já respeitam MAX_CPS=17")


if __name__ == "__main__":
    main()
