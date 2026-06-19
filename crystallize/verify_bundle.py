#!/usr/bin/env python3
# ============================================================
# HiFiOss Ecosystem | AXIS-NIDDHI Project
# Independent Offline Verification Script (V16 IMMORTAL)
# ============================================================
import os
import sys
import json
import hashlib
import argparse
import subprocess

try:
    import nacl.signing
    import nacl.encoding
except ImportError:
    print("[VERIFY]: CRITICAL - PyNaCl is required. Run: pip install pynacl")
    sys.exit(1)

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
    current_level = sorted(hash_list) # sorted, NO set()
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            h1 = current_level[i]
            h2 = current_level[i+1] if i+1 < len(current_level) else h1
            next_level.append(generate_sha256_from_string(h1 + h2))
        current_level = next_level
    return current_level[0]

def verify_bundle(bundle_dir):
    print(f"\n[VERIFY]: Starting verification for bundle: {bundle_dir}")
    
    manifest_path = os.path.join(bundle_dir, "manifest_v16.json")
    integrity_path = os.path.join(bundle_dir, "global_integrity.txt")
    signatures_path = os.path.join(bundle_dir, "signatures.json")
    glossary_path = os.path.join(bundle_dir, "Glossario_v5.csv")
    
    if not all(os.path.exists(p) for p in [manifest_path, integrity_path, signatures_path]):
        print("[VERIFY]: FAIL - Missing critical verification files in bundle.")
        sys.exit(1)
        
    with open(manifest_path, "r") as f: manifest = json.load(f)
    with open(integrity_path, "r") as f: expected_global_hash = f.read().strip()
    with open(signatures_path, "r") as f: signatures = json.load(f)
    
    # 1 & 2. Recompute Merkle Root
    all_bundle_hashes = []
    for root, _, files in os.walk(bundle_dir):
        for file in files:
            if file in ["manifest_v16.json", "signatures.json", "global_integrity.txt", "merkle_root.txt"]: continue
            filepath = os.path.join(root, file)
            all_bundle_hashes.append(generate_file_sha256(filepath))
            
    computed_merkle_root = compute_merkle_root(all_bundle_hashes)
    merkle_valid = (computed_merkle_root == manifest.get("merkle_chain_hash"))
    print(f"[VERIFY]: Merkle Root Valid: {merkle_valid}")
    
    # 3 & 4. Recompute Global Integrity Hash
    glossary_sha = generate_file_sha256(glossary_path) if os.path.exists(glossary_path) else "missing"
    pipeline_version = manifest.get("pipeline_version", "V16_IMMORTAL_MASTER")
    computed_global_hash = generate_sha256_from_string(computed_merkle_root + glossary_sha + pipeline_version)
    
    integrity_valid = (computed_global_hash == expected_global_hash)
    print(f"[VERIFY]: Global Integrity Valid: {integrity_valid}")
    if not integrity_valid:
        print(f"   Expected: {expected_global_hash}")
        print(f"   Computed: {computed_global_hash}")
        
    # 5. Validate Ed25519 Signatures
    valid_sigs = 0
    for sig in signatures:
        try:
            verify_key = nacl.signing.VerifyKey(sig["public_key"], encoder=nacl.encoding.HexEncoder)
            verify_key.verify(expected_global_hash.encode('utf-8'), bytes.fromhex(sig["signature"]))
            valid_sigs += 1
        except nacl.exceptions.BadSignatureError:
            pass
    signatures_valid = (valid_sigs >= 2)
    print(f"[VERIFY]: Signatures Valid: {signatures_valid} ({valid_sigs}/{len(signatures)} threshold met)")
    
    # 6. Validate CID
    cid_match = False
    try:
        res = subprocess.check_output(['ipfs', 'add', '--only-hash', '-r', '-Q', '--cid-version=1', bundle_dir])
        computed_cid = res.decode().strip()
        cid_match = (computed_cid == manifest.get("ipfs", {}).get("cid_root"))
        print(f"[VERIFY]: IPFS CID Match: {cid_match}")
    except Exception:
        print("[VERIFY]: IPFS CLI not found. Skipping CID validation.")
        
    # 7. Validate Glossary
    glossary_valid = (glossary_sha != "missing")
    print(f"[VERIFY]: Glossary Present & Hashed: {glossary_valid}")
    
    # 8. Validate Source Lineage
    lineage = manifest.get("source_lineage", {})
    lineage_present = bool(lineage and lineage.get("channel_id"))
    print(f"[VERIFY]: Source Lineage Present: {lineage_present}")
    
    trust_score = (1.0 if integrity_valid else 0.0) * 0.5 + (1.0 if signatures_valid else 0.0) * 0.5
    
    result = {
        "integrity_valid":  integrity_valid,
        "merkle_valid":     merkle_valid,
        "signatures_valid": signatures_valid,
        "cid_match":        cid_match,
        "glossary_valid":   glossary_valid,
        "lineage_present":  lineage_present,
        "trust_score":      trust_score
    }
    
    print("\n[VERIFY]: FINAL RESULT")
    print(json.dumps(result, indent=2))
    
    if not (integrity_valid and merkle_valid and signatures_valid and lineage_present):
        print("\n[VERIFY]: CRITICAL FAILURES DETECTED. BUNDLE IS NOT TRUSTED.")
        sys.exit(1)
    else:
        print("\n[VERIFY]: BUNDLE IS FULLY VERIFIED AND TRUSTED.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HiFiOss V16 Offline Verification")
    parser.add_argument("--bundle", type=str, required=True, help="Path to the bundle directory")
    args = parser.parse_args()
    verify_bundle(args.bundle)
