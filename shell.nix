# shell.nix — Feitiço de invocação do motor SĀRA
# ================================================
# Ambiente reproduzível: qualquer máquina (ou Abelha) entra com um comando.
#
# USO:
#   nix-shell                 # entra no ambiente
#   ./run_sara.sh "URL" --language en --keep-json
#
# Ou direto:
#   nix-shell --run './run_sara.sh "URL" --language en --keep-json'
#
# Substitui o nix-shell -p ... digitado à mão toda vez. É o "feitiço de
# ressurreição" aplicado ao pipeline: a receita vive no arquivo, não na
# memória de quem digita.

{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  name = "sara-engine";

  buildInputs = [
    # Python + a SDK da Groq
    (pkgs.python3.withPackages (ps: [
      ps.groq
    ]))

    # Extração e processamento de áudio
    pkgs.yt-dlp        # link YouTube -> áudio
    pkgs.ffmpeg        # downsample 16k mono, chunking

    # Cofre de segredos (decifrar a chave Groq)
    pkgs.age
  ];

  shellHook = ''
    echo "🐝 SĀRA engine — ambiente pronto"
    echo "   python3 + groq + yt-dlp + ffmpeg + age"
    echo ""
    echo "   Rodar:  ./run_sara.sh \"URL\" --language en --keep-json"
    echo "   (run_sara.sh decifra a chave age e chama sara_engine.py)"
  '';
}
