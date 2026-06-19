#!/usr/bin/env bash
GROQ_API_KEY="$(age -d -i ~/.age-key.txt ~/.password-store/axis/groq-key.age)" \
python sara_engine.py "$@"
