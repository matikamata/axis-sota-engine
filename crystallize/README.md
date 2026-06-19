# crystallize/ — Trinca de integridade + pós-processadores SRT

Scripts de captura, assinatura e verificação do pipeline HiFiOss/Sotā.

## Arquivos

| script | papel |
|---|---|
| `capture_transcribe.py` | Phase 0 — captura yt-dlp + transcrição Whisper local; grava `archive/` |
| `sign_bundle.py` | Phase 1 — traduz (DeepL), assina Ed25519, monta bundle em `deliverables/` |
| `verify_bundle.py` | Verificador independente — recomputa Merkle + valida assinaturas |
| `srt_dhamma.py` | Pós-processador SRT Dhamma-aware (`*_clean.srt` → `*_dhamma.srt`) |
| `srt_scheele.py` | Pós-processador SRT CPS/wrap (`*_clean.srt` → `*_scheele.srt`) |
| `run_hifi.sh.template` | Template de invocação sem chaves (copiar → `run_hifi.sh`, preencher via `pass`) |

## TODO — gestão de chaves (CHAT DEDICADO)

- `keys/node_*_private.key` → migrar para cofre `age` (não versionar nunca)
- `keys/node_*_public.key` → ficam em claro (públicas por design)
- Ajustar `sign_bundle.py` para ler a chave privada do cofre `age` em vez de `keys/`
- Decisão separada da faxina atual — ver chat dedicado de gestão de cofre

## Nota sobre srt_dhamma / srt_scheele

Ambos têm `BUNDLE = "deliverables/RAW_LEGACY/UBIjZTOh6Pc/bundle"` hardcoded.
Refactor pendente: aceitar path como argumento CLI antes de próxima rodada de edição.
