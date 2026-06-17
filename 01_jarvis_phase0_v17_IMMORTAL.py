#!/usr/bin/env python3
# ============================================================
# JARVIS — Phase 0: Capture & Crystallize
# HiFiOss Ecosystem | AXIS-NIDDHI Project
# ============================================================
import subprocess
import os
import sys
import json
import hashlib
import datetime
import platform
import unicodedata
import re
import glob

try:
    import whisper
    from whisper.utils import get_writer
except ImportError:
    print("\n[JARVIS]: CRITICAL — openai-whisper não instalado.")
    print("Execute: pip install openai-whisper")
    sys.exit(1)

JARVIS_VERSION   = "JARVIS_PHASE0_v17_IMMORTAL"
TARGET_ERA       = "2222 dC"
ROOT_TEACHER     = "Prof. Waharaka Thero"
ROOT_SOURCE      = "PureDhamma.net"
WHISPER_MODELS   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_models")

DEFAULT_PALI_PROMPT = (
    "jāti, anicca, dukkha, anattā, Nibbāna, saṅkhāra, "
    "paṭicca-samuppāda, kamma, cetanā, vedanā, taṇhā, "
    "avijjā, Sotāpanna, Dhamma, Buddha, Sutta, Pāli, "
    "Abhidhamma, mettā, karuṇā, paññā, sīla, samādhi, "
    "Chanda, chanda, Dosa, dosa, Moha, moha, Lobha, lobha, Bhaya, bhaya"
)

VERIFIED_CHANNELS = {
    "@ScientistinRobes":  "https://www.youtube.com/@ScientistinRobes",
    "@jethavanarama_eng": "https://www.youtube.com/@jethavanarama_eng",
    "@theory.of.e":       "https://www.youtube.com/@theory.of.e",
    "@enlight_u":         "https://www.youtube.com/@enlight_u",
}

def jarvis(msg, level="INFO"):
    icons = {"INFO": ">>", "OK": "✓", "WARN": "⚠", "FAIL": "✗", "STARK": "⚙"}
    print(f"\n[JARVIS {icons.get(level,'>>')}]: {msg}")

# [PATCH 1] HASHING PADRONIZADO
def generate_sha256_from_string(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def generate_sha256(file_path):
    if not os.path.exists(file_path): return None
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()

def compute_merkle_root(hash_list):
    if not hash_list:
        return generate_sha256_from_string("EMPTY_TREE")
    current_level = sorted(hash_list) # sorted, NO set() — preserva repetições
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            h1 = current_level[i]
            h2 = current_level[i+1] if i+1 < len(current_level) else h1
            next_level.append(generate_sha256_from_string(h1 + h2))
        current_level = next_level
    return current_level[0]

def compute_channel_fingerprint(channel_id, channel_url):
    return generate_sha256_from_string(channel_id + channel_url)

def get_tool_version(cmd):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip().split('\n')[0][:80]
    except:
        return "unknown"

def normalize_text(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def check_environment():
    if sys.base_prefix == sys.prefix:
        jarvis("Ambiente virtual não detectado.", "WARN")
        resp = input("   Continuar mesmo assim? [s/N]: ").strip().lower()
        if resp != 's': sys.exit(0)

def check_dependencies():
    missing = []
    for tool in ['yt-dlp', 'ffmpeg']:
        try: subprocess.check_output(['which', tool], stderr=subprocess.DEVNULL)
        except: missing.append(tool)
    if missing:
        jarvis(f"Ferramentas ausentes: {', '.join(missing)}", "FAIL")
        sys.exit(1)

def init_vault(video_id):
    paths = {
        "archive":     f"archive/{video_id}",
        "workspace":   f"workspace/{video_id}",
        "transcripts": f"workspace/{video_id}/transcripts",
        "models":      WHISPER_MODELS,
    }
    for p in paths.values(): os.makedirs(p, exist_ok=True)
    return paths

def capture_youtube(url, paths, video_id):
    video_file = f"{paths['archive']}/raw_video.mp4"
    info_json_dst = f"{paths['archive']}/metadata.info.json"
    
    # [PATCH 2] Load metadata from cache
    if os.path.exists(video_file):
        jarvis("raw_video.mp4 já em cache.", "OK")
        yt_metadata = {}
        if os.path.exists(info_json_dst):
            with open(info_json_dst, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                yt_metadata = {
                    "title":       raw.get("title", ""),
                    "upload_date": raw.get("upload_date", ""),
                    "channel":     raw.get("channel", ""),
                    "uploader_id": raw.get("uploader_id", "")
                }
        return video_file, yt_metadata

    cookies_arg = ['--cookies', 'cookies.txt'] if os.path.exists('cookies.txt') else []
    result = subprocess.run([
        'yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        '--merge-output-format', 'mp4', '--write-info-json', '--write-thumbnail',
        *cookies_arg, '-o', video_file, url
    ])
    if result.returncode != 0:
        jarvis("Falha no download.", "FAIL"); sys.exit(1)
        
    # [PATCH 2] Dynamic info.json discovery
    candidates = [c for c in glob.glob(f"{paths['archive']}/*.info.json") if not c.endswith("metadata.info.json")]
    if candidates:
        os.rename(candidates[0], info_json_dst)
        jarvis("metadata.info.json capturado.", "OK")
    else:
        jarvis("WARNING: .info.json não encontrado — metadata indisponível.", "WARN")

    yt_metadata = {}
    if os.path.exists(info_json_dst):
        with open(info_json_dst, 'r', encoding='utf-8') as f:
            raw = json.load(f)
            yt_metadata = {
                "title":       raw.get("title", ""),
                "upload_date": raw.get("upload_date", ""),
                "channel":     raw.get("channel", ""),
                "uploader_id": raw.get("uploader_id", "")
            }

    return video_file, yt_metadata

def extract_audio(video_file, paths, video_id):
    master_wav = f"{paths['archive']}/master_48k.wav"
    ai_wav     = f"{paths['workspace']}/ai_proxy.wav"
    if not os.path.exists(master_wav):
        subprocess.run(['ffmpeg', '-y', '-i', video_file, '-vn', '-acodec', 'pcm_s16le',
            '-ar', '48000', '-ac', '2', master_wav],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(ai_wav):
        subprocess.run(['ffmpeg', '-y', '-i', master_wav, '-ar', '16000', '-ac', '1',
            '-af', 'highpass=f=80,lowpass=f=8000', ai_wav],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return master_wav, ai_wav

def select_whisper_model():
    print("\n   [1] large-v3  [2] turbo  [3] base")
    choice = input("   Escolha (padrão: 1): ").strip()
    return {"1": "large-v3", "2": "turbo", "3": "base"}.get(choice, "large-v3")

def transcribe(ai_wav, paths, video_id, model_name, language="en", pali_prompt=None):
    source_file = f"{paths['transcripts']}/source_structured.json"
    
    if os.path.exists(source_file):
        resp = input("   Cache existe. Re-transcrever? [s/N]: ").strip().lower()
        if resp != 's':
            with open(source_file, 'r', encoding='utf-8') as f:
                segments = json.load(f)
            # [PATCH 4] Always recompute — never trust stored hashes
            for s in segments:
                clean = normalize_text(s["text"])
                s["text"]           = clean
                s["text_sha256"]    = generate_sha256_from_string(clean)
                s["token_estimate"] = len(clean.split())
            segment_hashes       = sorted([s["text_sha256"] for s in segments])
            segments_merkle_root = compute_merkle_root(segment_hashes)
            avg_tokens           = sum(s["token_estimate"] for s in segments) / len(segments) if segments else 0
            return segments, source_file, model_name, "from_cache", pali_prompt, segments_merkle_root, avg_tokens

    model = whisper.load_model(model_name, download_root=paths['models'])
    
    # [PATCH 8] Real model checksum
    model_pt = os.path.join(paths['models'], f"{model_name}.pt")
    model_checksum = generate_sha256(model_pt) if os.path.exists(model_pt) else "model_file_not_found"
    jarvis(f"Model checksum: {model_checksum[:24]}...", "OK")

    result = model.transcribe(ai_wav, verbose=True, task="transcribe",
        language=language, initial_prompt=pali_prompt or DEFAULT_PALI_PROMPT,
        word_timestamps=True)
        
    # [PATCH 5] Hard lock — task must be transcribe
    if result.get("task", "transcribe") != "transcribe":
        jarvis("HARD FAIL: task != transcribe. Abortando.", "FAIL")
        sys.exit(1)

    segments = []
    for seg in result['segments']:
        # [PATCH 3] Normalize + hash text-only (canonical standard)
        clean_text = normalize_text(seg['text'])
        text_sha256 = generate_sha256_from_string(clean_text)
        token_est   = len(clean_text.split())
        
        segments.append({
            "id": f"seg_{seg['id']:04d}", 
            "start": round(seg['start'], 3),
            "end": round(seg['end'], 3), 
            "text": clean_text,
            "text_sha256": text_sha256,
            "token_estimate": token_est,
            "lang_detected": result.get('language', language),
        })
        
    # [PATCH 3] Merkle root — sorted WITHOUT set() preserves all segments
    segment_hashes       = sorted([s["text_sha256"] for s in segments])
    segments_merkle_root = compute_merkle_root(segment_hashes)
    avg_tokens           = sum(s["token_estimate"] for s in segments) / len(segments) if segments else 0

    with open(source_file, 'w', encoding='utf-8') as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)
        
    return segments, source_file, model_name, model_checksum, pali_prompt, segments_merkle_root, avg_tokens

def crystallize(segments, paths, video_id, result_meta):
    archive_dir, transcripts_dir = paths['archive'], paths['transcripts']
    
    video_file  = f"{archive_dir}/raw_video.mp4"
    master_wav  = f"{archive_dir}/master_48k.wav"
    source_json = f"{transcripts_dir}/source_structured.json"
    info_json   = f"{archive_dir}/metadata.info.json"
    
    # [PATCH 7] Skip overwrite if source unchanged
    manifest_path = f"{archive_dir}/phase0_manifest.json"
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            current_sha = generate_sha256(source_json) if os.path.exists(source_json) else None
            if existing.get("integrity", {}).get("source_json_sha256") == current_sha and current_sha is not None:
                jarvis("Manifesto inalterado — preservando original (idempotência).", "OK")
                return existing, f"{transcripts_dir}/for_deepl_segmented.txt"
        except: pass

    with open(f"{transcripts_dir}/for_deepl_segmented.txt", 'w', encoding='utf-8') as f:
        for seg in segments: f.write(f"{seg['id']}: {seg['text']}\n")
    with open(f"{transcripts_dir}/source_plain.txt", 'w', encoding='utf-8') as f:
        for seg in segments: f.write(seg['text'] + ' ')
        
    # [PATCH 7] Full manifest V17
    channel_fingerprint = compute_channel_fingerprint(result_meta["channel_id"], result_meta["channel_url"])
    lineage_risk = "verified" if result_meta.get("lineage_verified") else "unverified"
    yt_metadata  = result_meta.get("yt_metadata", {})

    manifest = {
        "jarvis_version": JARVIS_VERSION,
        "target_era":     TARGET_ERA,
        "video_id":       video_id,
        "created_at":     datetime.datetime.utcnow().isoformat() + "Z",
        "system":         platform.system() + " " + platform.release(),

        "execution_env": {
            "python_version":  sys.version.split()[0],
            "whisper_version": getattr(whisper, '__version__', 'unknown'),
            "ffmpeg_version":  get_tool_version(['ffmpeg', '-version']),
            "yt_dlp_version":  get_tool_version(['yt-dlp', '--version']),
        },

        "source_proof": {
            "yt_video_id":         video_id,
            "yt_metadata_sha256":  generate_sha256(info_json) if os.path.exists(info_json) else None,
            "channel_fingerprint": channel_fingerprint,
            "title":               yt_metadata.get("title", ""),
            "upload_date":         yt_metadata.get("upload_date", ""),
        },

        "source_lineage": {
            "channel_id":        result_meta["channel_id"],
            "channel_url":       result_meta["channel_url"],
            "lineage_verified":  result_meta.get("lineage_verified", False),
            "lineage_risk":      lineage_risk,
            "channel_fingerprint": channel_fingerprint,
            "root_teacher":      ROOT_TEACHER,
            "root_source":       ROOT_SOURCE,
            "content_profile":   "dhamma_talk",
            "verification_date": datetime.date.today().isoformat(),
            "verifier":          result_meta.get("verifier", ""),
        },

        "transcription": {
            "model":                result_meta.get("model_name", ""),
            "model_checksum":       result_meta.get("model_checksum", ""),
            "language_lock":        result_meta.get("language", "en"),
            "initial_prompt":       result_meta.get("pali_prompt", DEFAULT_PALI_PROMPT),
            "pali_prompt_source":   result_meta.get("pali_prompt_source", "default"),
            "segment_count":        len(segments),
            "task":                 "transcribe",
            "segments_merkle_root": result_meta.get("segments_merkle_root", ""),
        },

        "ai_ready": {
            "embedding_ready": True,
            "segmented":       True,
            "avg_tokens":      result_meta.get("avg_tokens", 0),
        },

        "integrity": {
            "video_raw_sha256":    generate_sha256(video_file) if os.path.exists(video_file) else None,
            "audio_master_sha256": generate_sha256(master_wav) if os.path.exists(master_wav) else None,
            "source_json_sha256":  generate_sha256(source_json) if os.path.exists(source_json) else None,
        },

        "handoff": {
            "next_stage": "full_script_v16_IMMORTAL.py",
            "command":    f"python full_script_v16_IMMORTAL.py --input {video_file} --channel {result_meta['channel_id']}",
            "ready":      True,
        }
    }
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest, f"{transcripts_dir}/for_deepl_segmented.txt"

def main():
    check_environment(); check_dependencies()
    url = input("\n  URL do YouTube: ").strip()
    if not url: sys.exit(1)
    ch_list = list(VERIFIED_CHANNELS.keys())
    for i, ch in enumerate(ch_list, 1): print(f"    [{i}] {ch}")
    ch_choice = input("  Canal [1-4/0=outro]: ").strip()
    if ch_choice.isdigit() and 1 <= int(ch_choice) <= len(ch_list):
        channel_id  = ch_list[int(ch_choice)-1]
        channel_url = VERIFIED_CHANNELS[channel_id]
        lineage_verified = True
    else:
        channel_id  = input("  Channel ID: ").strip()
        channel_url = input("  Channel URL: ").strip()
        lineage_verified = False
    verifier   = input("  Verifier: ").strip()
    model_name = select_whisper_model()
    language   = input("  Idioma (padrão: en): ").strip() or "en"
    
    # [PATCH 6] Pāli prompt — ENV never silently empty
    env_prompt = os.environ.get("PALI_PROMPT", "").strip()
    custom = input("  Termos Pāli extras (Enter=pular): ").strip()

    if custom:
        pali_prompt = DEFAULT_PALI_PROMPT + f", {custom}"
        pali_prompt_source = "interactive"
    elif env_prompt:
        pali_prompt = env_prompt
        pali_prompt_source = "env"
        jarvis(f"Usando PALI_PROMPT do ENV.", "INFO")
    else:
        pali_prompt = DEFAULT_PALI_PROMPT
        pali_prompt_source = "default"
        jarvis("Usando DEFAULT_PALI_PROMPT.", "INFO")
        
    video_id = subprocess.check_output(['yt-dlp','--get-id',url], stderr=subprocess.DEVNULL).decode().strip()
    paths = init_vault(video_id)
    
    video_file, yt_metadata = capture_youtube(url, paths, video_id)
    master_wav, ai_wav = extract_audio(video_file, paths, video_id)
    
    result = transcribe(ai_wav, paths, video_id, model_name, language, pali_prompt)
    if len(result) == 7:
        segments, source_file, result_model, result_checksum, result_prompt, segments_merkle_root, avg_tokens = result
    else:
        jarvis("CRITICAL: Unexpected return from transcribe.", "FAIL"); sys.exit(1)
        
    result_meta = {
        "channel_id": channel_id, "channel_url": channel_url,
        "lineage_verified": lineage_verified, "verifier": verifier,
        "model_name": result_model, "model_checksum": result_checksum,
        "language": language, "pali_prompt": result_prompt,
        "pali_prompt_source": pali_prompt_source,
        "segments_merkle_root": segments_merkle_root,
        "avg_tokens": avg_tokens,
        "yt_metadata": yt_metadata # [FIX A] YT_METADATA PROPAGATION
    }
    crystallize(segments, paths, video_id, result_meta)
    print(f"\n  HANDOFF → python full_script_v16_IMMORTAL.py --input archive/{video_id}/raw_video.mp4 --channel {channel_id}")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n[JARVIS]: Sādhu 🙏"); sys.exit(0)
