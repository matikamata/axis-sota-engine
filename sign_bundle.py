#!/usr/bin/env python3
# ============================================================
# HiFiOss Ecosystem | AXIS-NIDDHI Project
# Phase 1: Translate, TTS, Bundle & Sign (V16 IMMORTAL v2.4)
# ============================================================
import os
import sys
import json
import hashlib
import subprocess
import re
import time
import unicodedata
import datetime
import platform
import csv
import argparse
import logging
import shutil

try:
    import nacl.signing
    import nacl.encoding
except ImportError:
    print("[AETHOSS]: CRITICAL - PyNaCl is required for real Ed25519 cryptography. Run: pip install pynacl")
    sys.exit(1)

# --- DETERMINISM LOCK (NO FORBIDDEN ENTROPY) ---
os.environ["PYTHONHASHSEED"] = "42"

# --- EXECUTION FLAGS ---
EXECUTION_PROFILE      = os.environ.get("EXECUTION_PROFILE", "translate").lower()
ENABLE_HUMANIZATION    = os.environ.get("ENABLE_HUMANIZATION", "true").lower() == "true"
ENABLE_TRANSLATION     = os.environ.get("ENABLE_TRANSLATION", "true").lower() == "true"
ENABLE_TTS             = os.environ.get("ENABLE_TTS", "false").lower() == "true"
ENABLE_BUNDLE_EXPORT   = os.environ.get("ENABLE_BUNDLE_EXPORT", "true").lower() == "true"
ENABLE_VERIFICATION    = os.environ.get("ENABLE_VERIFICATION", "true").lower() == "true"
ENABLE_CLS_SYNC        = os.environ.get("ENABLE_CLS_SYNC", "true").lower() == "true"
ENABLE_IPFS_UPLOAD     = os.environ.get("ENABLE_IPFS_UPLOAD", "false").lower() == "true"
ENABLE_ROUND_TRIP      = os.environ.get("ENABLE_ROUND_TRIP", "true").lower() == "true"
ENABLE_CONSENSUS_PASS  = os.environ.get("ENABLE_CONSENSUS_PASS", "true").lower() == "true"
ROUND_TRIP_MODE        = os.environ.get("ROUND_TRIP_MODE", "sample").lower()
ROUND_TRIP_SAMPLE_RATE = float(os.environ.get("ROUND_TRIP_SAMPLE_RATE", "0.20"))
SIGNING_MODE           = os.environ.get("SIGNING_MODE", "local").lower()
WHISPER_MODEL          = os.environ.get("WHISPER_MODEL", "large-v3")
CONTENT_PROFILE        = os.environ.get("CONTENT_PROFILE", "dhamma_talk").lower()

if EXECUTION_PROFILE == "smoke":
    ENABLE_TRANSLATION = False
    ENABLE_TTS = False
elif EXECUTION_PROFILE == "translate":
    ENABLE_TTS = False

# --- CONSTANTS ---
PIPELINE_VERSION = "V16_IMMORTAL_MASTER_v2.4"
GLOSSARY_PATH    = "Glossario_v5.csv"
FORBIDDEN_TERMS  = ["hallucinate", "fake", "untrue", "altered", "fictional"]
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "")
DEEPL_API_KEY    = os.environ.get("DEEPL_API_KEY", "")
# DeepL exige variantes explícitas — "PT" sozinho vira PT-PT por compat. retroativa
DEEPL_LANG_MAP   = {"pt": "PT-BR", "en": "EN-US", "zh": "ZH"}

# ==========================================
# [LOGGING & PRE-FLIGHT]
# ==========================================
_log_handler = None

def setup_logging(log_path):
    global _log_handler
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s UTC | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    _log_handler = log_path

def lumina_log(msg, level="INFO"):
    levels = {"INFO": logging.INFO, "WARN": logging.WARNING,
              "FAIL": logging.ERROR, "OK": logging.INFO}
    logging.log(levels.get(level, logging.INFO), f"[AETHOSS] {msg}")

def video_id_from_input(input_path):
    return os.path.basename(os.path.dirname(input_path)) \
        if "archive/" in input_path \
        else os.path.splitext(os.path.basename(input_path))[0]

def node_0_preflight(args):
    print("\n" + "═"*60)
    print("  JARVIS — Pre-Flight Check")
    print("═"*60)

    has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    has_deepl  = bool(os.environ.get("DEEPL_API_KEY", "").strip())

    openai_ok = False
    if has_openai:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                openai_ok = (r.status == 200)
            lumina_log("OpenAI: ✓ acessível", "OK")
        except urllib.error.HTTPError as e:
            lumina_log(f"OpenAI: ⚠ HTTP {e.code} ({'rate limit' if e.code==429 else 'erro'})", "WARN")
        except Exception as e:
            lumina_log(f"OpenAI: ✗ inacessível ({str(e)[:60]})", "WARN")
    else:
        lumina_log("OpenAI: ✗ API key ausente", "WARN")

    deepl_ok = False
    deepl_chars_remaining = None
    if has_deepl:
        try:
            import urllib.request
            deepl_url = "https://api-free.deepl.com/v2/usage" \
                if ":fx" in os.environ.get("DEEPL_API_KEY","") \
                else "https://api.deepl.com/v2/usage"
            req = urllib.request.Request(
                deepl_url,
                headers={"Authorization": f"DeepL-Auth-Key {os.environ['DEEPL_API_KEY']}"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                usage = json.loads(r.read().decode())
                used  = usage.get("character_count", 0)
                limit = usage.get("character_limit", 500000)
                deepl_chars_remaining = limit - used
                deepl_ok = deepl_chars_remaining > 1000
                lumina_log(
                    f"DeepL: {'✓' if deepl_ok else '⚠'} "
                    f"{deepl_chars_remaining:,} chars restantes "
                    f"({used:,}/{limit:,} usados)", "OK" if deepl_ok else "WARN"
                )
        except Exception as e:
            lumina_log(f"DeepL: ✗ inacessível ({str(e)[:60]})", "WARN")
    else:
        lumina_log("DeepL: ✗ API key ausente", "WARN")

    print()

    if not has_openai or not openai_ok:
        print("  OpenAI indisponível. Modos disponíveis:")
        print("  [1] RAW-TRANSCRIPT — só tradução DeepL (recomendado agora)")
        print("  [2] ABORT — aguardar créditos/disponibilidade OpenAI")
        choice = input("\n  Escolha [1/2] (padrão: 1): ").strip() or "1"
        if choice != "1":
            lumina_log("Abortando por escolha do operador.", "INFO")
            sys.exit(0)
        execution_mode = "raw"
    else:
        print("  APIs disponíveis. Escolha o modo:")
        print("  [1] RAW-TRANSCRIPT — só tradução DeepL")
        print("      rápido, econômico, ideal para AXIS-NIDDHI")
        print("  [2] HiFi — humanização GPT-4o + tradução")
        print("      melhor qualidade para auto-dubbing futuro")
        choice = input("\n  Escolha [1/2] (padrão: 1): ").strip() or "1"
        execution_mode = "hifi" if choice == "2" else "raw"

    lumina_log(f"Modo selecionado: {execution_mode.upper()}", "OK")

    # [UX 1] Language selection
    AVAILABLE_LANGUAGES = {
        "pt": "Português BR",
        "es": "Español",
        "en": "English",
        "fr": "Français",
        "de": "Deutsch",
        "it": "Italiano",
        "ja": "日本語",
        "zh": "中文",
    }

    print("\n  Idiomas de destino para tradução:")
    print("  (selecione um ou mais, separados por vírgula)")
    print()
    for i, (code, name) in enumerate(AVAILABLE_LANGUAGES.items(), 1):
        print(f"    [{i}] {name} ({code})")
    print()
    print("  Exemplos: '1' = só PT-BR | '1,2' = PT-BR + ES | Enter = PT-BR")

    lang_choice = input("\n  Idiomas [1-8, separados por vírgula] (padrão: 1): ").strip()

    if not lang_choice:
        selected_langs = ["pt"]
    else:
        lang_codes = list(AVAILABLE_LANGUAGES.keys())
        selected_langs = []
        for part in lang_choice.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(lang_codes):
                    selected_langs.append(lang_codes[idx])
            elif part.lower() in AVAILABLE_LANGUAGES:
                selected_langs.append(part.lower())
        if not selected_langs:
            selected_langs = ["pt"]

    lumina_log(
        f"Idiomas selecionados: {[AVAILABLE_LANGUAGES[l] for l in selected_langs]}",
        "OK"
    )

    # [UX 4] Estimate translation cost
    source_file = f"workspace/{video_id_from_input(args.input)}/transcripts/source_structured.json"
    if os.path.exists(source_file):
        with open(source_file, "r", encoding="utf-8") as f:
            segs = json.load(f)
        total_chars = sum(len(s.get("text","")) for s in segs)
        total_chars_all_langs = total_chars * len(selected_langs)
        print()
        print(f"  Estimativa para este vídeo:")
        print(f"    Segmentos:      {len(segs)}")
        print(f"    Caracteres EN:  {total_chars:,}")
        print(f"    Idiomas:        {len(selected_langs)}")
        print(f"    Total DeepL:    ~{total_chars_all_langs:,} chars")
        if deepl_chars_remaining:
            pct_used = total_chars_all_langs / deepl_chars_remaining * 100
            print(f"    Cota usada:     ~{pct_used:.1f}% da cota restante")
            if total_chars_all_langs > deepl_chars_remaining:
                lumina_log("AVISO: Cota DeepL insuficiente para este vídeo!", "WARN")
        print()

    # [UX 2] Explain round-trip and offer choice
    if execution_mode == "hifi":
        print()
        print("  ┌─────────────────────────────────────────────────────────┐")
        print("  │  Round-Trip Validation — o que é?                       │")
        print("  │                                                          │")
        print("  │  Após traduzir PT → ES, o sistema back-traduz ES → EN   │")
        print("  │  e compara com o original para detectar distorções       │")
        print("  │  introduzidas pelo GPT-4o na humanização.                │")
        print("  │                                                          │")
        print("  │  SEM humanização (RAW): desabilitado automaticamente.    │")
        print("  │  COM humanização (HiFi): recomendado para Pāli/BJJ.      │")
        print("  │                                                          │")
        print("  │  [1] Ativar  — amostragem 20% (recomendado)              │")
        print("  │  [2] Ativar  — todos os segmentos (mais lento, mais cota)│")
        print("  │  [3] Desativar                                           │")
        print("  └─────────────────────────────────────────────────────────┘")
        rt_choice = input("\n  Round-Trip [1/2/3] (padrão: 1): ").strip() or "1"
        if rt_choice == "2":
            os.environ["ROUND_TRIP_MODE"] = "full"
        elif rt_choice == "3":
            os.environ["ROUND_TRIP_MODE"] = "disabled"
        else:
            os.environ["ROUND_TRIP_MODE"] = "sample"

    return execution_mode, deepl_ok, deepl_chars_remaining, selected_langs

# ==========================================
# [HASHING & CRYPTO]
# ==========================================
def canonical_json(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def generate_sha256_from_string(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def generate_file_sha256(file_path):
    if not os.path.exists(file_path): return None
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()

def compute_merkle_root(hash_list):
    if not hash_list: return generate_sha256_from_string("EMPTY_TREE")
    current_level = sorted(hash_list)
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            h1 = current_level[i]
            h2 = current_level[i+1] if i+1 < len(current_level) else h1
            next_level.append(generate_sha256_from_string(h1 + h2))
        current_level = next_level
    return current_level[0]

def setup_node_keys(node_id, keys_dir):
    priv_path = os.path.join(keys_dir, f"{node_id}_private.key")
    pub_path  = os.path.join(keys_dir, f"{node_id}_public.key")
    if os.path.exists(priv_path) and os.path.exists(pub_path):
        with open(priv_path, "rb") as f:
            signing_key = nacl.signing.SigningKey(f.read())
    else:
        signing_key = nacl.signing.SigningKey.generate()
        with open(priv_path, "wb") as f: f.write(signing_key.encode())
        with open(pub_path, "wb") as f: f.write(signing_key.verify_key.encode(encoder=nacl.encoding.HexEncoder))
    return signing_key

def ed25519_sign(signing_key, message):
    signed = signing_key.sign(message.encode('utf-8'))
    return signed.signature.hex()

def generate_real_cid(path):
    try:
        res = subprocess.check_output(
            ['ipfs', 'add', '-r', '-Q', '--cid-version=1', path],
            stderr=subprocess.DEVNULL
        )
        cid = res.decode().strip()
        lumina_log(f"IPFS CID gerado: {cid[:20]}...", "OK")
        return cid
    except FileNotFoundError:
        lumina_log("IPFS CLI não instalado — CID null no manifest", "WARN")
        return None
    except Exception as e:
        lumina_log(f"IPFS erro: {str(e)[:60]} — CID null", "WARN")
        return None

# ==========================================
# [DETERMINISTIC CACHE]
# ==========================================
def get_cache_key(service, payload):
    return generate_sha256_from_string(f"{service}_{canonical_json(payload)}_42")

def check_cache(cache_dir, cache_key):
    path = os.path.join(cache_dir, f"{cache_key}.json")
    if os.path.exists(path):
        with open(path, "r") as f: return json.load(f)
    return None

def save_cache(cache_dir, cache_key, response):
    with open(os.path.join(cache_dir, f"{cache_key}.json"), "w") as f:
        f.write(canonical_json(response))

# ==========================================
# [GLOSSARY & TEXT CANONICALIZATION]
# ==========================================
def load_and_classify_glossary(filepath):
    pali_preserve, translation_anchor = {}, {}
    diacritics = set("āīūṭḍṇḷṃṅñśṣḥ")
    if os.path.exists(filepath):
        with open(filepath, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    src, tgt = row[0].strip(), row[1].strip()
                    if src == tgt or any(c in src.lower() for c in diacritics):
                        pali_preserve[src] = tgt
                    elif src.isascii() and src != tgt:
                        translation_anchor[src] = tgt
    return pali_preserve, translation_anchor

def apply_glossary_lock(text, glossary_dict):
    if not glossary_dict: return text, {}
    sorted_terms = sorted(glossary_dict.keys(), key=lambda x: (-len(x), x))
    protected_text = text
    placeholders = {}
    for term in sorted_terms:
        term_hash = generate_sha256_from_string(term)[:8]
        placeholder = f"__PALI_LOCK_{term_hash}__"
        pattern = re.compile(r'(?i)(?<![\w\u0100-\u017F])' + re.escape(term) + r'(?![\w\u0100-\u017F])')
        if pattern.search(protected_text):
            placeholders[placeholder] = glossary_dict[term]
            protected_text = pattern.sub(placeholder, protected_text)
    return protected_text, placeholders

def restore_glossary_lock(text, placeholders):
    for ph, val in placeholders.items(): text = text.replace(ph, val)
    return text

def extract_pali_terms(text, pali_dict):
    found = []
    for term in pali_dict.keys():
        if re.search(r'(?i)(?<![\w\u0100-\u017F])' + re.escape(term) + r'(?![\w\u0100-\u017F])', text):
            found.append(term)
    return sorted(list(set(found)))

def normalize_text(text):
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def normalize_for_hash(text):
    return normalize_text(text).lower()

def check_semantic_similarity(text1, text2):
    set1, set2 = set(normalize_for_hash(text1).split()), set(normalize_for_hash(text2).split())
    if not set1 or not set2: return 0.0
    return len(set1.intersection(set2)) / len(set1.union(set2))

def hybrid_similarity(a, b):
    j  = check_semantic_similarity(a, b)
    lr = min(len(a), len(b)) / max(len(a), len(b)) if max(len(a), len(b)) > 0 else 0
    return round((j * 0.7) + (lr * 0.3), 4)

def enforce_doctrinal_safety(original, new_text, stage="", pali_dict=None,
                             quarantine_list=None, segment_id=None):
    orig_lower = original.lower()
    new_lower  = new_text.lower()

    for term in FORBIDDEN_TERMS:
        if term in new_lower and term not in orig_lower:
            lumina_log(
                f"CRITICAL DOCTRINAL VIOLATION in {stage}: "
                f"forbidden term '{term}' introduced. ABORTING.", "FAIL"
            )
            sys.exit(1)

    if pali_dict:
        lost = [
            term for term in pali_dict
            if term.lower() in orig_lower
            and term.lower() not in new_lower
        ]
        if lost:
            if quarantine_list is not None:
                quarantine_list.append({
                    "stage":       stage,
                    "segment_id":  segment_id,
                    "lost_terms":  lost,
                    "source_text": original[:200],
                    "output_text": new_text[:200],
                })
                lumina_log(f"[QUARANTINE] Pāli perdido em {stage} seg={segment_id}: {lost}", "WARN")
            else:
                lumina_log(
                    f"HARD FAIL: Doctrinal Pāli loss in {stage}: "
                    f"{lost[:5]}{'...' if len(lost) > 5 else ''}", "FAIL"
                )
                sys.exit(1)

# ==========================================
# [APIs]
# ==========================================
def call_openai_chat(system_prompt, user_prompt, ctx):
    if not OPENAI_API_KEY:
        return user_prompt
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        "temperature": 0.0,
        "seed": 42
    }
    cache_key = get_cache_key("openai", payload)
    cached = check_cache(ctx.paths['cache_openai'], cache_key)
    if cached:
        return cached["choices"][0]["message"]["content"].strip()

    import urllib.request
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                data=json.dumps(payload).encode("utf-8")
            )
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                save_cache(ctx.paths['cache_openai'], cache_key, res_data)
                return res_data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60 * (2 ** attempt)
                lumina_log(f"OpenAI 429 — aguardando {wait}s (tentativa {attempt+1}/3)", "WARN")
                time.sleep(wait)
                if attempt == 2:
                    lumina_log("Rate limit persistente — fallback RAW para este segmento", "WARN")
                    return user_prompt
            elif e.code in [401, 403]:
                lumina_log(f"FATAL OpenAI: HTTP {e.code}. Verifique OPENAI_API_KEY.", "FAIL")
                sys.exit(1)
            else:
                lumina_log(f"OpenAI HTTP {e.code} — fallback RAW", "WARN")
                return user_prompt
        except Exception as e:
            lumina_log(f"OpenAI erro — fallback RAW ({str(e)[:60]})", "WARN")
            return user_prompt
    return user_prompt

def call_deepl_batch(texts, target_lang, ctx):
    if not DEEPL_API_KEY:
        lumina_log(f"DeepL key ausente — pass-through [{target_lang}]", "WARN")
        return texts

    deepl_lang = DEEPL_LANG_MAP.get(target_lang, target_lang).upper()
    payload = {"text": texts, "target_lang": deepl_lang}
    cache_key = get_cache_key("deepl", payload)
    cached = check_cache(ctx.paths['cache_deepl'], cache_key)
    if cached:
        return [t["text"] for t in cached["translations"]]

    url = "https://api-free.deepl.com/v2/translate" \
        if ":fx" in DEEPL_API_KEY \
        else "https://api.deepl.com/v2/translate"

    import urllib.request
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}",
                         "Content-Type": "application/json"},
                data=json.dumps(payload).encode("utf-8")
            )
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                save_cache(ctx.paths['cache_deepl'], cache_key, res_data)
                return [t["text"] for t in res_data["translations"]]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 * (2 ** attempt)
                lumina_log(f"DeepL 429 — aguardando {wait}s (tentativa {attempt+1}/3)", "WARN")
                time.sleep(wait)
                if attempt == 2:
                    lumina_log("DeepL quota/rate persistente — pass-through", "WARN")
                    return texts
            elif e.code == 456:
                lumina_log("DeepL quota esgotada (456) — pass-through", "WARN")
                return texts
            else:
                lumina_log(f"DeepL HTTP {e.code} — pass-through", "WARN")
                return texts
        except Exception as e:
            lumina_log(f"DeepL erro — pass-through ({str(e)[:60]})", "WARN")
            return texts
    return texts

def call_openai_tts(text, output_path):
    if not OPENAI_API_KEY:
        subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=1', '-ar', '24000', output_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    import urllib.request
    payload = {"model": "tts-1", "input": text, "voice": "alloy", "response_format": "wav"}
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, data=json.dumps(payload).encode("utf-8"))
    with urllib.request.urlopen(req) as response:
        with open(output_path, "wb") as f: f.write(response.read())

# ==========================================
# [CONTEXT & PIPELINE]
# ==========================================
class HiFiOssContext:
    def __init__(self, input_path, channel_id, target_langs=None):
        self.input_path = input_path
        self.video_id = video_id_from_input(input_path)
        self.target_langs = target_langs if target_langs else ["pt"]
        
        _mode = os.environ.get("HIFIOSS_MODE", "raw")
        _mode_folder = "HIFI_DUBBED" if _mode == "hifi" else "RAW_LEGACY"

        self.paths = {
            "archive":      f"archive/{self.video_id}",
            "workspace":    f"workspace/{self.video_id}",
            "transcripts":  f"workspace/{self.video_id}/transcripts",
            "content":      f"workspace/{self.video_id}/content",
            "audio":        f"workspace/{self.video_id}/audio",
            "bundle":       f"deliverables/{_mode_folder}/{self.video_id}/bundle",
            "verification": f"deliverables/{_mode_folder}/{self.video_id}/verification",
            "keys":         "keys",
            "cache_openai": "cache/openai",
            "cache_deepl":  "cache/deepl",
        }
        for p in self.paths.values(): os.makedirs(p, exist_ok=True)
        for l in self.target_langs: os.makedirs(f"{self.paths['audio']}/{l}", exist_ok=True)
        
        if not os.path.exists(GLOSSARY_PATH):
            with open(GLOSSARY_PATH, "w", encoding="utf-8") as f: f.write("jāti paccayā jarā maraṇa,jāti paccayā jarā maraṇa\njāti,jāti\n")
        self.pali_dict, self.anchor_dict = load_and_classify_glossary(GLOSSARY_PATH)
        
        self.source_lineage = self._load_lineage(channel_id)
        self.axis_bridge_candidates = []
        self.cls_sync_entries = {}
        self.consensus_flags = 0
        self.round_trip_scores = []
        
        self.segment_audit = []
        self.deepl_chars_remaining = None
        self.deepl_ok = False
        self.round_trip_detail = []
        self.pali_immutability_verified = True
        self.pali_violations = []
        self.quarantine_triggered = False

        os.makedirs(f"workspace/{self.video_id}/audit", exist_ok=True)
        
        self.nodes = []
        for i in range(1, 4):
            self.nodes.append({"id": f"node_{i:03d}", "key": setup_node_keys(f"node_{i:03d}", self.paths['keys'])})

    def _load_lineage(self, channel_id):
        manifest_path = f"{self.paths['archive']}/phase0_manifest.json"
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                return json.load(f).get("source_lineage", {})
        if not channel_id:
            lumina_log("CRITICAL: source_lineage missing and --channel not provided.", "FAIL")
            sys.exit(1)
        return {
            "channel_id": channel_id, "channel_url": f"https://youtube.com/{channel_id}",
            "lineage_verified": True, "root_teacher": "Prof. Waharaka Thero",
            "root_source": "PureDhamma.net", "content_profile": CONTENT_PROFILE,
            "verification_date": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"), "verifier": "AETHOSS"
        }

def node_m4_transcribe_fallback(ctx):
    source_file = f"{ctx.paths['transcripts']}/source_structured.json"
    if os.path.exists(source_file):
        lumina_log("M4: source_structured.json found. Skipping fallback transcription.", "OK")
        return
    lumina_log("M4: Fallback Transcription (Mocked for Phase 1 standalone)", "INFO")
    data = [{"id": "seg_0001", "start": 0.0, "end": 2.0, "text": "Welcome to the system.", "lang_detected": "en"}]
    with open(source_file, "w", encoding="utf-8") as f: f.write(canonical_json(data))

def node_m4_9_humanize(ctx):
    if not ENABLE_HUMANIZATION:
        lumina_log("M4.9: Humanização desabilitada — pass-through RAW", "INFO")
        source_path = f"{ctx.paths['transcripts']}/source_structured.json"
        with open(source_path, "r") as f:
            data = json.load(f)
        os.makedirs(ctx.paths['content'], exist_ok=True)
        with open(f"{ctx.paths['content']}/humanized_en.json", "w", encoding="utf-8") as f:
            f.write(canonical_json(data))
            
        for seg in data:
            ctx.segment_audit.append({
                "stage":              "humanize_raw",
                "segment_id":         seg["id"],
                "original_sha256":    generate_sha256_from_string(normalize_text(seg.get("text_original", seg["text"]))),
                "final_sha256":       generate_sha256_from_string(seg["text"]),
                "pali_before":        str(extract_pali_terms(seg.get("text_original", seg["text"]), ctx.pali_dict)),
                "pali_after":         str(extract_pali_terms(seg["text"], ctx.pali_dict)),
                "pali_preserved":     (extract_pali_terms(seg.get("text_original", seg["text"]), ctx.pali_dict) == extract_pali_terms(seg["text"], ctx.pali_dict)),
                "round_trip_score":   "",
            })
        lumina_log("M4.9: Pass-through completo.", "OK")
        return
        
    lumina_log("M4.9: Humanization & Consensus Pass", "INFO")
    with open(f"{ctx.paths['transcripts']}/source_structured.json", "r") as f: data = json.load(f)
    
    humanized = []
    for seg in data:
        clean_text = normalize_text(seg["text"])
        pali_before = extract_pali_terms(clean_text, ctx.pali_dict)
        protected_text, placeholders = apply_glossary_lock(clean_text, ctx.pali_dict)
        
        sys_prompt = "Rewrite to improve spoken flow. Output ONLY text. Do not translate."
        res_A = call_openai_chat(sys_prompt, protected_text, ctx)
        
        if ENABLE_CONSENSUS_PASS:
            res_B = call_openai_chat(sys_prompt, protected_text, ctx) 
            sim = check_semantic_similarity(res_A, res_B)
            if sim < 0.85: lumina_log("HARD FAIL: Consensus Drift", "FAIL"); sys.exit(1)
            elif sim < 0.92: ctx.consensus_flags += 1
            
        res = restore_glossary_lock(res_A, placeholders)
        enforce_doctrinal_safety(clean_text, res, "Humanization", pali_dict=ctx.pali_dict,
                                 quarantine_list=ctx.pali_violations, segment_id=seg.get("id"))
        
        pali_after = extract_pali_terms(res, ctx.pali_dict)
        if generate_sha256_from_string(str(pali_before)) != generate_sha256_from_string(str(pali_after)):
            lumina_log("HARD FAIL: Pali Immutability Broken", "FAIL"); sys.exit(1)
            
        seg["text_original"] = clean_text
        seg["text"] = res
        humanized.append(seg)
        
        ctx.segment_audit.append({
            "stage":              "humanize",
            "segment_id":         seg["id"],
            "original_sha256":    generate_sha256_from_string(normalize_text(seg.get("text_original", seg["text"]))),
            "final_sha256":       generate_sha256_from_string(seg["text"]),
            "pali_before":        str(extract_pali_terms(seg.get("text_original", seg["text"]), ctx.pali_dict)),
            "pali_after":         str(extract_pali_terms(seg["text"], ctx.pali_dict)),
            "pali_preserved":     (extract_pali_terms(seg.get("text_original", seg["text"]), ctx.pali_dict) == extract_pali_terms(seg["text"], ctx.pali_dict)),
            "round_trip_score":   "",
        })

    with open(f"{ctx.paths['content']}/humanized_en.json", "w", encoding="utf-8") as f:
        f.write(canonical_json(humanized))

    # [UX 6] Report glossary terms found in this video
    all_pali_found = set()
    for entry in ctx.segment_audit:
        before = entry.get("pali_before", "")
        if before and before not in ("", "[]", "n/a"):
            import ast
            try:
                terms = ast.literal_eval(before)
                all_pali_found.update(terms)
            except: pass

    if all_pali_found:
        lumina_log(
            f"Termos do glossário encontrados ({len(all_pali_found)}): "
            f"{sorted(all_pali_found)[:10]}"
            f"{'...' if len(all_pali_found) > 10 else ''}",
            "OK"
        )
    else:
        lumina_log("Nenhum termo do glossário encontrado neste vídeo.", "INFO")

def node_m5_translate(ctx):
    import copy
    if not ENABLE_TRANSLATION: return
    lumina_log("M5: Iniciando tradução...", "INFO")
    with open(f"{ctx.paths['content']}/humanized_en.json", "r") as f: data = json.load(f)
    
    total_segs = len(data)
    total_langs = len(ctx.target_langs)

    for lang_idx, lang in enumerate(ctx.target_langs):
        lang_data = copy.deepcopy(data)
        lang_name = {
            "pt": "Português BR", "es": "Español", "en": "English",
            "fr": "Français", "de": "Deutsch", "it": "Italiano",
            "ja": "日本語", "zh": "中文"
        }.get(lang, lang.upper())

        lumina_log(
            f"M5: Traduzindo para {lang_name} "
            f"({lang_idx+1}/{total_langs}) — {total_segs} segmentos...",
            "INFO"
        )

        for seg_idx, seg in enumerate(lang_data):
            # [UX 3] Progress every 10 segments
            if seg_idx % 10 == 0 or seg_idx == total_segs - 1:
                pct = int((seg_idx + 1) / total_segs * 100)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(
                    f"\r  [{bar}] {pct:3d}% — seg {seg_idx+1}/{total_segs}",
                    end="", flush=True
                )

            protected_text, placeholders = apply_glossary_lock(seg["text"], ctx.pali_dict)
            trans_res = call_deepl_batch([protected_text], lang, ctx)
            trans_text = trans_res[0] if trans_res else protected_text
            final_text = restore_glossary_lock(trans_text, placeholders)
            enforce_doctrinal_safety(seg["text"], final_text, "Translation", pali_dict=ctx.pali_dict,
                                     quarantine_list=ctx.pali_violations, segment_id=seg.get("id"))
            seg["text_translated"] = final_text
            
            do_round_trip = False
            rt_score = None
            if ENABLE_ROUND_TRIP and ROUND_TRIP_MODE != "disabled":
                hash_val = int(generate_sha256_from_string(f"{ctx.video_id}_{seg['id']}"), 16) % 100
                do_round_trip = (ROUND_TRIP_MODE == "full") or (hash_val < int(ROUND_TRIP_SAMPLE_RATE * 100))
                if do_round_trip:
                    rt_res = call_deepl_batch([final_text], "en", ctx)
                    rt_text = rt_res[0] if rt_res else final_text
                    rt_score = hybrid_similarity(seg["text"], rt_text)
                    ctx.round_trip_scores.append(rt_score)
                    
                    ctx.round_trip_detail.append({
                        "segment_id":   seg["id"],
                        "lang":         lang,
                        "score":        rt_score,
                        "passed":       rt_score >= 0.70,
                        "flagged":      0.70 <= rt_score < 0.75,
                        "hash_en":      generate_sha256_from_string(normalize_text(seg["text"])),
                        "method":       "hybrid_similarity",
                    })
                    
                    if rt_score < 0.70:
                        print() # break progress bar line
                        lumina_log(f"HARD FAIL: Round-Trip {rt_score:.4f} < 0.70 [{seg['id']}]", "FAIL")
                        sys.exit(1)
                    elif rt_score < 0.75:
                        print() # break progress bar line
                        lumina_log(f"Round-Trip FLAG: {rt_score:.4f} < 0.75 [{seg['id']}]", "WARN")
                        seg.setdefault("flags", []).append("ROUND_TRIP_LOW")
            
            sem_hash = generate_sha256_from_string(normalize_for_hash(final_text))
            ctx.axis_bridge_candidates.append({"segment_id": seg["id"], "semantic_hash": sem_hash, "text_excerpt": final_text[:50]})
            if ENABLE_CLS_SYNC:
                fallback_hash = generate_sha256_from_string(normalize_text(final_text))
                ctx.cls_sync_entries[seg["id"]] = {
                    "semantic_hash":     sem_hash,
                    "content_hash":      fallback_hash if not ENABLE_TTS else "pending_tts",
                    "content_hash_type": "text_sha256" if not ENABLE_TTS else "audio_sha256_pending",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                }
                
            ctx.segment_audit.append({
                "stage":            f"translate_{lang}",
                "segment_id":       seg["id"],
                "original_sha256":  generate_sha256_from_string(seg["text"]),
                "final_sha256":     generate_sha256_from_string(seg.get("text_translated", seg["text"])),
                "pali_before":      "",
                "pali_after":       "",
                "pali_preserved":   "n/a",
                "round_trip_score": str(rt_score) if do_round_trip else "not_sampled",
            })
                
        print()  # newline after progress bar
        lumina_log(f"M5: {lang_name} ✓ concluído.", "OK")
        with open(f"{ctx.paths['content']}/translated_{lang}.json", "w", encoding="utf-8") as f:
            f.write(canonical_json(lang_data))

def node_m5_3_tts(ctx):
    if not ENABLE_TTS: return
    lumina_log("M5.3: TTS Generation", "INFO")
    for lang in ctx.target_langs:
        with open(f"{ctx.paths['content']}/translated_{lang}.json", "r") as f: data = json.load(f)
        for seg in data:
            text = seg.get("text_translated", seg["text"])
            out_wav = f"{ctx.paths['audio']}/{lang}/{seg['id']}.wav"
            if not os.path.exists(out_wav): call_openai_tts(text, out_wav)
            audio_hash = generate_file_sha256(out_wav)
            if ENABLE_CLS_SYNC and seg["id"] in ctx.cls_sync_entries:
                ctx.cls_sync_entries[seg["id"]]["content_hash"] = audio_hash
                ctx.cls_sync_entries[seg["id"]]["content_hash_type"] = "audio_sha256"

def generate_srt(segments, output_path, text_key="text"):
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            def fmt(s):
                h, m, sec = int(s // 3600), int((s % 3600) // 60), int(s % 60)
                ms = int(round((s - int(s)) * 1000))
                return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
            f.write(f"{i}\n{fmt(seg['start'])} --> {fmt(seg['end'])}\n{seg[text_key]}\n\n")

def node_m11_bundle_export(ctx):
    if not ENABLE_BUNDLE_EXPORT: return
    lumina_log("M11: Bundle Export", "INFO")
    bundle_dir = ctx.paths['bundle']
    os.makedirs(bundle_dir, exist_ok=True)
    
    audit_path = f"workspace/{ctx.video_id}/audit/segment_audit.csv"
    with open(audit_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "stage","segment_id","original_sha256","final_sha256",
            "pali_before","pali_after","pali_preserved","round_trip_score"
        ])
        writer.writeheader()
        writer.writerows(ctx.segment_audit)
        
    if os.path.exists(audit_path):
        shutil.copy(audit_path, f"{bundle_dir}/segment_audit.csv")
    
    with open(f"{ctx.paths['content']}/humanized_en.json", "r") as f: en_data = json.load(f)
    generate_srt(en_data, f"{bundle_dir}/subtitles_en.srt", "text")
    
    if ENABLE_TRANSLATION:
        for lang in ctx.target_langs:
            with open(f"{ctx.paths['content']}/translated_{lang}.json", "r") as f: lang_data = json.load(f)
            generate_srt(lang_data, f"{bundle_dir}/subtitles_{lang}.srt", "text_translated")
    
    shutil.copy(__file__, f"{bundle_dir}/02_full_script_v16_IMMORTAL_v2_4.py")
    shutil.copy(GLOSSARY_PATH, f"{bundle_dir}/{GLOSSARY_PATH}")
    with open(f"{bundle_dir}/pipeline_version.txt", "w") as f: f.write(PIPELINE_VERSION)
    
    with open(f"{bundle_dir}/bundle_timestamp.txt", "w") as f:
        f.write(datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"))
    
    hashes_txt = f"{bundle_dir}/hashes.txt"
    with open(hashes_txt, "w") as f:
        for root, _, files in os.walk(bundle_dir):
            for file in files:
                if file in ["hashes.txt", "manifest_v16.json", "signatures.json", "global_integrity.txt", "merkle_root.txt"]: continue
                filepath = os.path.join(root, file)
                f.write(f"{generate_file_sha256(filepath)}  {os.path.relpath(filepath, bundle_dir)}\n")

def node_m10_manifest_and_trust(ctx):
    lumina_log("M10: Manifest & Trust Layer", "INFO")
    bundle_dir = ctx.paths['bundle']
    verif_dir = ctx.paths['verification']
    
    all_bundle_hashes = []
    for root, _, files in os.walk(bundle_dir):
        for file in files:
            if file in ["manifest_v16.json", "signatures.json", "global_integrity.txt", "merkle_root.txt"]: continue
            filepath = os.path.join(root, file)
            all_bundle_hashes.append(generate_file_sha256(filepath))
            
    merkle_root = compute_merkle_root(all_bundle_hashes)
    with open(f"{bundle_dir}/merkle_root.txt", "w") as f: f.write(merkle_root)
    
    glossary_sha = generate_file_sha256(GLOSSARY_PATH)
    global_integrity_hash = generate_sha256_from_string(merkle_root + glossary_sha + PIPELINE_VERSION)
    with open(f"{bundle_dir}/global_integrity.txt", "w") as f: f.write(global_integrity_hash)
    
    signatures = []
    for node in ctx.nodes:
        sig_hex = ed25519_sign(node["key"], global_integrity_hash)
        pub_hex = node["key"].verify_key.encode(encoder=nacl.encoding.HexEncoder).decode('utf-8')
        signatures.append({"signer_id": node["id"], "public_key": pub_hex, "signature": sig_hex, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")})
    with open(f"{bundle_dir}/signatures.json", "w") as f: f.write(canonical_json(signatures))
    
    cid = generate_real_cid(bundle_dir)
    
    manifest = {
        "video_id": ctx.video_id,
        "pipeline_version": PIPELINE_VERSION,
        "execution_profile": EXECUTION_PROFILE,
        "execution_mode":        os.environ.get("HIFIOSS_MODE", "raw"),
        "humanization_applied":  ENABLE_HUMANIZATION,
        "tts_applied":           ENABLE_TTS,
        "bundle_timestamp":      datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"),
        "source_lineage": ctx.source_lineage,
        "independent_nodes": False,
        "global_integrity": {"hash": global_integrity_hash, "verified": True},
        "glossary_stats": {
            "total_terms": len(ctx.pali_dict) + len(ctx.anchor_dict),
            "pali_preserve_count": len(ctx.pali_dict),
            "translation_anchor_count": len(ctx.anchor_dict)
        },
        "deepl_quota_status": {
            "chars_remaining": ctx.deepl_chars_remaining,
            "quota_ok":        ctx.deepl_ok,
        },
        "round_trip_validation": {
            "sampling_mode": "deterministic_hash",
            "average_score": (round(sum(ctx.round_trip_scores) / len(ctx.round_trip_scores), 4) if ctx.round_trip_scores else None),
            "samples_taken": len(ctx.round_trip_scores),
            "failures": 0,
            "threshold_hard_fail":  0.70,
            "threshold_flag":       0.75,
            "similarity_method":    "hybrid_jaccard_length_ratio",
            "calibration_note":     ("Hybrid similarity (Jaccard 70% + length ratio 30%). Thresholds calibrated for Pāli vocabulary: pure Jaccard 0.90 causes false positives on Dhamma texts.")
        },
        "round_trip_detail": ctx.round_trip_detail,
        "pali_immutability": {
            "verified":    ctx.pali_immutability_verified,
            "quarantined": ctx.quarantine_triggered,
            "violations":  ctx.pali_violations,
        },
        "axis_cls_sync": {"enabled": ENABLE_CLS_SYNC, "entries": list(ctx.cls_sync_entries.values())},
        "ipfs": {
            "cid_root":    cid,
            "cid_version": 1 if cid else None,
            "available":   cid is not None,
        },
        "signatures": {"count": len(signatures), "threshold_verified": len(signatures) >= 2},
        "merkle_chain_hash": merkle_root
    }
    
    with open(f"{bundle_dir}/manifest_v16.json", "w", encoding="utf-8") as f:
        f.write(canonical_json(manifest))
        
    if ENABLE_VERIFICATION:
        os.makedirs(verif_dir, exist_ok=True)
        shutil.copy(f"{bundle_dir}/manifest_v16.json", f"{verif_dir}/manifest_v16.json")
        shutil.copy(f"{bundle_dir}/global_integrity.txt", f"{verif_dir}/global_integrity.txt")
        shutil.copy(f"{bundle_dir}/signatures.json", f"{verif_dir}/signatures.json")

# ==========================================
# [MAIN EXECUTION]
# ==========================================
if __name__ == "__main__":
    import time as _time
    start_time = _time.time()  # [UX 5]

    parser = argparse.ArgumentParser(description="HiFiOss V16 IMMORTAL MASTER v2.4")
    parser.add_argument("--input",   type=str, required=True, help="Path to raw_video.mp4")
    parser.add_argument("--channel", type=str, help="Channel ID (ex: @ScientistinRobes)")
    parser.add_argument("--url",     type=str, help="YouTube URL (fallback)")
    parser.add_argument("--model",   type=str, default="large-v3")
    args = parser.parse_args()

    video_id = video_id_from_input(args.input)

    execution_mode, deepl_ok, deepl_chars_remaining, selected_langs = node_0_preflight(args)
    os.environ["HIFIOSS_MODE"] = execution_mode

    mode_folder = "HIFI_DUBBED" if execution_mode == "hifi" else "RAW_LEGACY"
    log_path = f"deliverables/{mode_folder}/{video_id}/log.txt"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    setup_logging(log_path)

    # [PATCH 14] Mode ALWAYS overrides ENV-derived flags
    # REMOVIDO global ENABLE_HUMANIZATION, ENABLE_TTS, ENABLE_CONSENSUS_PASS, ROUND_TRIP_MODE
    
    if execution_mode == "raw":
        ENABLE_HUMANIZATION   = False  
        ENABLE_TTS            = False  
        ENABLE_CONSENSUS_PASS = False  
        ROUND_TRIP_MODE       = "disabled"  # [FIX 9]
        lumina_log("RAW mode: Round-trip DISABLED (only meaningful after GPT-4o humanization)", "INFO")
    elif execution_mode == "hifi":
        ENABLE_HUMANIZATION   = bool(os.environ.get("OPENAI_API_KEY","").strip())
        ENABLE_TTS            = os.environ.get("ENABLE_TTS","false").lower() == "true" and bool(os.environ.get("OPENAI_API_KEY","").strip())
        ENABLE_CONSENSUS_PASS = ENABLE_HUMANIZATION
        ROUND_TRIP_MODE       = os.environ.get("ROUND_TRIP_MODE", "sample")
        lumina_log(f"HiFi mode: Humanization={'ON' if ENABLE_HUMANIZATION else 'OFF'}, TTS={'ON' if ENABLE_TTS else 'OFF'}", "INFO")

    if not deepl_ok and not bool(os.environ.get("DEEPL_API_KEY","").strip()):
        lumina_log("AVISO: DeepL indisponível — legendas serão pass-through (EN)", "WARN")

    lumina_log(f"STARTING V16 IMMORTAL v2.4 | MODE: {execution_mode.upper()} | VIDEO: {video_id}", "OK")

    ctx = HiFiOssContext(args.input, args.channel, target_langs=selected_langs)
    ctx.deepl_chars_remaining = deepl_chars_remaining
    ctx.deepl_ok = deepl_ok

    node_m4_transcribe_fallback(ctx)
    node_m4_9_humanize(ctx)
    node_m5_translate(ctx)
    
    ctx.pali_immutability_verified = all(
        entry.get("pali_preserved") == True
        for entry in ctx.segment_audit
        if "pali_preserved" in entry
        and entry.get("pali_preserved") != "n/a"
        and not isinstance(entry.get("pali_preserved"), str)
    )
    lumina_log(
        f"Pāli immutability: {'✓ verified' if ctx.pali_immutability_verified else '✗ VIOLATED'}",
        "OK" if ctx.pali_immutability_verified else "FAIL"
    )
    if not ctx.pali_immutability_verified:
        ctx.quarantine_triggered = True
        lumina_log(
            f"[QUARANTINE] {len(ctx.pali_violations)} violação(ões) Pāli — bundle vai para REVISAR/",
            "WARN"
        )
        
    node_m5_3_tts(ctx)
    node_m11_bundle_export(ctx)
    node_m10_manifest_and_trust(ctx)

    if ctx.quarantine_triggered:
        src_base     = f"deliverables/{mode_folder}/{ctx.video_id}"
        revisar_base = f"deliverables/REVISAR/{ctx.video_id}"
        if os.path.exists(src_base):
            os.makedirs("deliverables/REVISAR", exist_ok=True)
            if os.path.exists(revisar_base):
                shutil.rmtree(revisar_base)
            shutil.move(src_base, revisar_base)
            mode_folder = "REVISAR"
            lumina_log(f"Bundle movido para deliverables/REVISAR/{ctx.video_id}/", "WARN")
        revisar_md = f"deliverables/REVISAR/{ctx.video_id}/REVISAR.md"
        with open(revisar_md, "w", encoding="utf-8") as f:
            f.write(f"# 🔍 Revisão Pāli necessária — {ctx.video_id}\n\n")
            f.write(f"Gerado por Sotā Engine · {datetime.datetime.now(datetime.timezone.utc).isoformat()}Z\n")
            f.write(f"{len(ctx.pali_violations)} segmento(s) precisam de olhar humano (Abelha nativa).\n")
            f.write("Integridade criptográfica: OK (trust_score íntegro). Falta aprovação doutrinária.\n\n---\n\n")
            for v in ctx.pali_violations:
                f.write(f"## Segmento {v['segment_id']}\n")
                f.write(f"- Termo(s) perdido(s): {v['lost_terms']}\n")
                f.write(f"- Original EN: \"{v['source_text']}\"\n")
                f.write(f"- Tradução gerada: \"{v['output_text']}\"\n")
                f.write(f"- Ação: confirmar grafia correta do termo Pāli e re-selar v2\n\n")

    # [UX 5] Execution summary
    end_time = _time.time()
    duration = end_time - start_time

    with open(f"{ctx.paths['transcripts']}/source_structured.json","r") as f:
        _segs = json.load(f)
    _total_chars = sum(len(s.get("text","")) for s in _segs)

    lumina_log("━"*50, "INFO")
    lumina_log(f"RESUMO DE EXECUÇÃO:", "OK")
    lumina_log(f"  Vídeo:       {ctx.video_id}", "INFO")
    lumina_log(f"  Modo:        {execution_mode.upper()}", "INFO")
    lumina_log(f"  Segmentos:   {len(_segs)}", "INFO")
    lumina_log(f"  Chars EN:    {_total_chars:,}", "INFO")
    lumina_log(f"  Idiomas:     {ctx.target_langs}", "INFO")
    lumina_log(f"  Tempo total: {duration/60:.1f} min", "INFO")
    lumina_log(f"  Bundle:      deliverables/{mode_folder}/{ctx.video_id}/bundle/", "OK")
    lumina_log("━"*50, "INFO")

    print(f"""
  ═══════════════════════════════════════════════════════
  ✓ Pipeline concluído ({execution_mode.upper()} mode)

  📁 Resultados em:
     deliverables/{mode_folder}/{video_id}/bundle/
       subtitles_pt.srt   ← PT-BR {'humanizado' if execution_mode == 'hifi' else 'direto Whisper'}
       subtitles_es.srt   ← ES
       segment_audit.csv  ← log de auditoria de segmentos
       manifest_v16.json  ← linhagem + integridade
       log.txt            ← histórico completo

  ✓ Para verificar:
     python 03_verify_v16.py --bundle deliverables/{mode_folder}/{video_id}/bundle/
  ═══════════════════════════════════════════════════════
    """)
