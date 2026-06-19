#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SĀRA Engine — motor de transcrição da Colmeia de Puñña
=======================================================

PAPEL NA ARQUITETURA:
    Este é o MOTOR (builder/backend-side), NÃO a página da Abelha.
    Roda onde a chave Groq está segura: tua máquina (Fase 0) ou
    um backend/Oracle VM (Fase 1). A página chama este motor; a
    Abelha nunca vê este código, nunca define language, nunca sabe
    o que é chunking. A chave Groq NUNCA vai para o frontend.

O QUE FAZ (link YouTube -> SRT pronto para revisão):
    1. Extrai áudio com yt-dlp no sweet spot: FLAC 16kHz mono
       (o Whisper faz downsample para 16k mono de qualquer jeito;
        extrair assim = menor arquivo, ZERO perda de acurácia).
    2. Se passar do limite do tier, faz chunking com overlap.
    3. Transcreve cada chunk via Groq (whisper-large-v3) com:
        - language FIXO (nunca auto-detect — lição do "Urdu")
        - temperature=0 (determinístico/reproduzível)
        - verbose_json + word-level timestamps
        - Glossário Pāli no prompt (resolve "Chand" -> "Chanda")
    4. Remonta tudo num SRT único com offsets de tempo corretos.
    5. Salva o SRT + o JSON bruto (proveniência p/ a Base Purificada).

USO (Fase 0, local):
    export GROQ_API_KEY="..."        # nunca hardcode; cofre age depois
    python sara_engine.py "https://www.youtube.com/watch?v=UBIjZTOh6Pc" --language en
    python sara_engine.py --audio meu_audio.flac --language si
    python sara_engine.py URL --language en --glossary Glossario_v5.csv

DEPENDÊNCIAS:
    pip install groq
    yt-dlp e ffmpeg no PATH (já presentes no stack do projeto)

MAPEAMENTO PARA A FASE 1 (Colmeia):
    - language vira escolha da página (menu "Inglês/Cingalês") ou
      config por canal — não digitação da Abelha.
    - GROQ_API_KEY: chave do builder (Fase 0) OU chave da própria
      Abelha passada pelo backend (modelo de cota distribuída).
    - a extração (yt-dlp) roda no backend/VM, não no browser.
"""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ----------------------------------------------------------------------
# CONFIGURAÇÃO
# ----------------------------------------------------------------------

MODEL = "whisper-large-v3"          # NÃO o turbo: melhor em baixo-recurso (Pāli)
TARGET_SR = 16000                   # 16kHz — o ótimo do Whisper
TARGET_CHANNELS = 1                 # mono

# Limite de tamanho por requisição (free tier = 25MB; dev = 100MB).
# Usamos uma margem de segurança abaixo de 25MB.
MAX_BYTES = 24 * 1024 * 1024        # 24MB
CHUNK_SECONDS = 600                 # 10 min por chunk quando precisa fatiar
OVERLAP_SECONDS = 8                 # sobreposição p/ não cortar palavra no meio

# Refinamento 1 — filtro de alucinação.
# O Whisper "inventa" frases em trechos de silêncio/música (ex.: o famoso
# "Subtitles by the Amara.org community"). Segmentos com no_speech_prob alto
# são prováveis alucinações. Acima deste limiar, marcamos para revisão.
NO_SPEECH_THRESHOLD = 0.5
# Os timestamps de SEGMENTO e de PALAVRA não batem exatamente (desalinham
# em centésimos/décimos). Expandimos a zona suspeita por esta margem para
# garantir que as palavras da alucinação também sejam pegas.
SUSPECT_MARGIN = 3.0

# Filtro por CONTEÚDO (complemento robusto ao filtro por tempo).
# O Whisper alucina frases recorrentes do dataset de treino (créditos de
# legenda do YouTube). O cruzamento por tempo é frágil (desalinhamento
# seg×palavra), então também removemos cues cujo texto bate com estas
# assinaturas conhecidas. Lista extensível.
HALLUCINATION_PHRASES = [
    "amara.org",
    "subtitles by",
    "subscribe",
    "thanks for watching",
    "thank you for watching",
    "transcription by",
]
# Âncoras de 1 palavra: o re-fluxo pode fragmentar a frase de alucinação
# entre cues (ex.: só "Subtitles" numa cue). Estes tokens, quando aparecem
# ISOLADOS ou num trecho com no_speech alto, são fortes sinais de alucinação.
HALLUCINATION_TOKENS = ["amara.org", "amara"]

# Refinamento 2 — re-fluxo de cues por palavra.
# O Whisper devolve segmentos longos (até 12-17s) — grandes demais para
# legenda confortável. Usando os timestamps por palavra, re-quebramos em
# cues do tamanho certo para leitura.
MAX_CUE_CHARS = 42                  # padrão de legibilidade (1 linha)
MAX_CUE_SECONDS = 6.0               # duração máxima de um cue
MAX_CUE_GAP = 0.8                   # pausa que força quebra de cue

# Glossário Pāli embutido (fallback se --glossary não for passado).
# ATENÇÃO: o prompt do Whisper só considera os ÚLTIMOS ~224 tokens.
# Portanto o glossário no prompt é CURADO, não o CSV inteiro.
# (Diferente do keyterm de 1500 palavras do AssemblyAI — aqui é enxuto.)
DEFAULT_GLOSSARY = [
    "Anicca", "Anatta", "Dukkha", "Kamma", "Nibbāna", "Buddha", "Dhamma",
    "Chanda", "Dosa", "Bhaya", "Moha", "Lobha", "Avijjā", "Saṅkhāra",
    "Sotāpanna", "Jhāna", "Mettā", "Sīla", "Samādhi", "Paññā",
]


# ----------------------------------------------------------------------
# UTILIDADES DE ÁUDIO
# ----------------------------------------------------------------------

def run(cmd):
    """Roda um comando e levanta erro se falhar, mostrando stderr."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\n{res.stderr}")
    return res


def extract_audio(url, outdir):
    """
    yt-dlp -> FLAC 16kHz mono (o sweet spot). Retorna o caminho do .flac.

    NOTA: NÃO confiamos no --postprocessor-args do yt-dlp para o downsample,
    porque o prefixo nomeado se comporta de forma inconsistente entre versões
    (no teste real saiu 72MB em vez de ~15MB — o -ar/-ac foi ignorado).
    Em vez disso: baixamos o áudio bruto e re-encodamos com ffmpeg
    explicitamente, garantindo SEMPRE 16k mono. Mais robusto e previsível.
    """
    out_tmpl = str(Path(outdir) / "raw.%(ext)s")
    run([
        "yt-dlp", "-x", "--audio-format", "flac",
        "--no-playlist", "-o", out_tmpl, url,
    ])
    raw = sorted(Path(outdir).glob("raw.*"))
    if not raw:
        raise RuntimeError("Extração não produziu áudio")
    # Pega o id do vídeo para nomear a saída final
    vid = subprocess.run(
        ["yt-dlp", "--no-playlist", "--print", "%(id)s", url],
        capture_output=True, text=True,
    ).stdout.strip() or "audio"
    final = str(Path(outdir) / f"{vid}.flac")
    run([
        "ffmpeg", "-y", "-i", str(raw[-1]),
        "-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS),
        final,
    ])
    return final


def normalize_local(audio_path, outdir):
    """Converte um áudio local existente para FLAC 16k mono (idempotente)."""
    out = str(Path(outdir) / "normalized.flac")
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS),
        out,
    ]
    run(cmd)
    return out


def get_duration(path):
    """Duração em segundos via ffprobe."""
    res = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    return float(res.stdout.strip())


def chunk_audio(path, outdir):
    """
    Fatia em segmentos de CHUNK_SECONDS com OVERLAP_SECONDS de sobreposição.
    Retorna lista de (caminho_chunk, offset_em_segundos).
    Só é chamado quando o arquivo passa de MAX_BYTES.
    """
    duration = get_duration(path)
    step = CHUNK_SECONDS - OVERLAP_SECONDS
    n = math.ceil(duration / step)
    chunks = []
    for i in range(n):
        start = i * step
        out = str(Path(outdir) / f"chunk_{i:03d}.flac")
        run([
            "ffmpeg", "-y", "-i", path,
            "-ss", str(start), "-t", str(CHUNK_SECONDS),
            "-ar", str(TARGET_SR), "-ac", str(TARGET_CHANNELS),
            out,
        ])
        chunks.append((out, start))
        if start + CHUNK_SECONDS >= duration:
            break
    return chunks


# ----------------------------------------------------------------------
# TRANSCRIÇÃO (GROQ)
# ----------------------------------------------------------------------

def build_glossary_prompt(glossary_terms):
    """Monta a string de prompt a partir dos termos (curada, <~224 tokens)."""
    return "Termos: " + ", ".join(glossary_terms) + "."


def load_glossary_csv(csv_path, max_terms=60):
    """Lê a 1ª coluna de um CSV (ex.: Glossario_v5.csv) como termos."""
    import csv
    terms = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip():
                terms.append(row[0].strip())
    # cabeçalho provável fora; limita p/ caber no orçamento de ~224 tokens
    return terms[1:max_terms + 1] if len(terms) > 1 else terms


def transcribe(client, path, language, prompt, retries=4):
    """
    Transcreve um arquivo via Groq. Retorna dict com text/segments/words.

    Faz retry com backoff exponencial em erros transitórios (500/502/503/429),
    porque um soluço do servidor não pode derrubar um pipeline que vai
    processar milhares de vídeos numa Colmeia.
    """
    import time
    with open(path, "rb") as f:
        data = f.read()

    last_err = None
    for attempt in range(retries):
        try:
            resp = client.audio.transcriptions.create(
                file=(os.path.basename(path), data),
                model=MODEL,
                language=language,            # FIXO — nunca auto-detect
                temperature=0,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],
                prompt=prompt,                # Glossário Pāli
            )
            # A SDK pode devolver objeto ou dict; normalizamos para dict.
            if hasattr(resp, "model_dump"):
                return resp.model_dump()
            if hasattr(resp, "to_dict"):
                return resp.to_dict()
            return dict(resp)
        except Exception as e:
            last_err = e
            status = getattr(e, "status_code", None)
            # só re-tenta erros transitórios; erros de cliente (4xx exceto 429)
            # não adianta repetir
            transient = status in (429, 500, 502, 503, 504) or status is None
            if not transient or attempt == retries - 1:
                break
            wait = 2 ** attempt          # 1s, 2s, 4s, 8s
            print(f"[retry] erro transitório ({status}); "
                  f"tentativa {attempt + 1}/{retries}, aguardando {wait}s ...")
            time.sleep(wait)

    raise RuntimeError(
        f"Groq falhou após {retries} tentativas em {os.path.basename(path)}: "
        f"{last_err}"
    )


# ----------------------------------------------------------------------
# REMONTAGEM -> SRT
# ----------------------------------------------------------------------

def srt_time(seconds):
    """Segundos -> 'HH:MM:SS,mmm'."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def collect_words(chunk_results):
    """
    Junta as PALAVRAS de todos os chunks em tempo absoluto, aplicando offset
    e descartando duplicatas da zona de overlap. Também marca palavras que
    caem em segmentos com no_speech_prob alto (prováveis alucinações).

    Retorna: (words, flagged) onde
      words   = [{start, end, word, suspect}]  (ordenadas por tempo)
      flagged = [trechos suspeitos de alucinação]  (para revisão prioritária)
    """
    words = []
    flagged = []
    last_end = 0.0
    for result, offset in chunk_results:
        # mapa de zonas suspeitas (no_speech_prob alto) por tempo
        suspect_zones = []
        for seg in result.get("segments", []):
            if seg.get("no_speech_prob", 0) > NO_SPEECH_THRESHOLD:
                # expande a zona pela margem p/ absorver desalinhamento seg×palavra
                z0 = seg["start"] + offset - SUSPECT_MARGIN
                z1 = seg["end"] + offset + SUSPECT_MARGIN
                suspect_zones.append((z0, z1))
                flagged.append({
                    "start": seg["start"] + offset, "end": seg["end"] + offset,
                    "text": seg["text"].strip(),
                    "no_speech_prob": seg["no_speech_prob"],
                })

        for w in result.get("words", []):
            start = w["start"] + offset
            end = w["end"] + offset
            if start < last_end - 0.5:        # dedup do overlap
                continue
            token = w["word"].strip()
            if not token:
                continue
            # suspeita por ZONA: a palavra sobrepõe (não só "cai dentro") uma
            # zona de no_speech alto, já expandida pela margem.
            in_zone = any(not (end < z0 or start > z1) for z0, z1 in suspect_zones)
            # suspeita por TOKEN: assinatura inconfundível de alucinação.
            is_anchor = token.lower().strip(".,!?") in HALLUCINATION_TOKENS
            words.append({"start": start, "end": end,
                          "word": token, "suspect": in_zone or is_anchor})
            last_end = max(last_end, end)
    return words, flagged


def words_to_cues(words, drop_suspect=True):
    """
    Re-flui palavras em cues de legenda do tamanho certo (Refinamento 2).
    Quebra quando: estoura MAX_CUE_CHARS, MAX_CUE_SECONDS, ou há pausa
    > MAX_CUE_GAP entre palavras. Opcionalmente descarta palavras suspeitas
    de alucinação (Refinamento 1).
    """
    cues = []
    cur = []
    for i, w in enumerate(words):
        if drop_suspect and w["suspect"]:
            continue
        if cur:
            prev = cur[-1]
            cur_text = " ".join(x["word"] for x in cur)
            gap = w["start"] - prev["end"]
            too_long = len(cur_text) + 1 + len(w["word"]) > MAX_CUE_CHARS
            too_slow = w["end"] - cur[0]["start"] > MAX_CUE_SECONDS
            big_gap = gap > MAX_CUE_GAP
            if too_long or too_slow or big_gap:
                cues.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                             "text": cur_text})
                cur = []
        cur.append(w)
    if cur:
        cues.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                     "text": " ".join(x["word"] for x in cur)})
    # filtro por conteúdo: remove cues que batem com assinaturas de alucinação
    clean = []
    for c in cues:
        low = c["text"].lower()
        if any(p in low for p in HALLUCINATION_PHRASES):
            continue
        clean.append(c)
    return clean


def merge_segments(chunk_results):
    """
    Fallback: remonta por SEGMENTO (sem re-fluxo) quando não há palavras.
    Filtra alucinações por no_speech_prob.
    """
    merged = []
    last_end = 0.0
    for result, offset in chunk_results:
        for seg in result.get("segments", []):
            if seg.get("no_speech_prob", 0) > NO_SPEECH_THRESHOLD:
                continue                       # descarta alucinação
            start = seg["start"] + offset
            end = seg["end"] + offset
            if start < last_end - 0.5:
                continue
            text = seg["text"].strip()
            if not text:
                continue
            merged.append({"start": start, "end": end, "text": text})
            last_end = max(last_end, end)
    return merged


def build_cues(chunk_results):
    """
    Escolhe a melhor estratégia: re-fluxo por palavra se houver word-level
    timestamps; senão, cai para o merge por segmento.
    Retorna (cues, flagged).
    """
    words, flagged = collect_words(chunk_results)
    if words:
        return words_to_cues(words), flagged
    return merge_segments(chunk_results), flagged


def segments_to_srt(segments):
    """Lista de cues -> string SRT."""
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{srt_time(seg['start'])} --> {srt_time(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="SĀRA Engine — transcrição Colmeia")
    ap.add_argument("url", nargs="?", help="Link do YouTube")
    ap.add_argument("--audio", help="Caminho de áudio local (em vez de URL)")
    ap.add_argument("--language", default="en",
                    help="Idioma FIXO (en, si, ...). NUNCA confiar em auto-detect.")
    ap.add_argument("--glossary", help="CSV de glossário (1ª coluna = termos)")
    ap.add_argument("--no-glossary", action="store_true",
                    help="Roda SEM prompt de glossário (p/ isolar erros de prompt)")
    ap.add_argument("--out", default=".", help="Diretório de saída")
    ap.add_argument("--keep-json", action="store_true",
                    help="Salvar o JSON bruto (proveniência p/ a Base Purificada)")
    args = ap.parse_args()

    if not args.url and not args.audio:
        ap.error("Forneça um link do YouTube ou --audio <arquivo>")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        sys.exit("ERRO: defina GROQ_API_KEY no ambiente (nunca hardcode).")

    from groq import Groq
    client = Groq(api_key=api_key)

    # Glossário (CSV se passado, senão o embutido); --no-glossary desliga
    if args.no_glossary:
        terms = []
        prompt = ""
        print("[glossário] DESLIGADO (--no-glossary)")
    else:
        terms = load_glossary_csv(args.glossary) if args.glossary else DEFAULT_GLOSSARY
        prompt = build_glossary_prompt(terms)
        print(f"[glossário] {len(terms)} termos no prompt")

    with tempfile.TemporaryDirectory() as workdir:
        # 1) Áudio no sweet spot
        if args.audio:
            audio = normalize_local(args.audio, workdir)
            stem = Path(args.audio).stem
        else:
            audio = extract_audio(args.url, workdir)
            stem = Path(audio).stem
        print(f"[áudio] {audio} ({os.path.getsize(audio)/1e6:.1f} MB)")

        # 2) Chunking só se necessário
        if os.path.getsize(audio) > MAX_BYTES:
            chunks = chunk_audio(audio, workdir)
            print(f"[chunk] {len(chunks)} segmentos (arquivo > {MAX_BYTES/1e6:.0f}MB)")
        else:
            chunks = [(audio, 0.0)]
            print("[chunk] arquivo cabe em 1 requisição")

        # 3) Transcrição de cada chunk
        results = []
        for path, offset in chunks:
            size = os.path.getsize(path)
            if size > MAX_BYTES:
                # trava de segurança: nunca mandar silenciosamente um arquivo
                # grande demais (o free tier rejeita / trunca acima de 25MB)
                raise RuntimeError(
                    f"Chunk {path} tem {size/1e6:.1f}MB > limite {MAX_BYTES/1e6:.0f}MB. "
                    f"Reduza CHUNK_SECONDS ou confirme o downsample 16k mono."
                )
            print(f"[groq] transcrevendo offset={offset:.0f}s ({size/1e6:.1f}MB) ...")
            results.append((transcribe(client, path, args.language, prompt), offset))

        # 4) Remontagem -> SRT
        # 4) Remontagem -> cues (re-fluxo por palavra + filtro de alucinação)
        cues, flagged = build_cues(results)
        srt = segments_to_srt(cues)

        # 5) Saída
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        srt_path = out_dir / f"{stem}.srt"
        srt_path.write_text(srt, encoding="utf-8")
        print(f"[ok] SRT salvo: {srt_path} ({len(cues)} cues)")

        # Alucinações detectadas e removidas (revisão prioritária da Abelha)
        if flagged:
            print(f"[aviso] {len(flagged)} trecho(s) suspeito(s) de alucinação "
                  f"(no_speech_prob > {NO_SPEECH_THRESHOLD}) removido(s):")
            for f in flagged:
                print(f"        {srt_time(f['start'])}  \"{f['text'][:50]}\" "
                      f"(p={f['no_speech_prob']:.2f})")
            flag_path = out_dir / f"{stem}.flagged.json"
            flag_path.write_text(
                json.dumps(flagged, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[ok] Suspeitos salvos: {flag_path}")

        if args.keep_json:
            json_path = out_dir / f"{stem}.words.json"
            json_path.write_text(
                json.dumps([r for r, _ in results], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[ok] JSON bruto salvo: {json_path}")


if __name__ == "__main__":
    main()
