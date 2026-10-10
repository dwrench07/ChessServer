#!/usr/bin/env bash
# Waits for the Ollama container, makes sure the explanation model is present
# (pulling it once into the shared volume), then hands off to the container's
# command. Everything is idempotent, so container restarts are cheap.
set -euo pipefail

MODEL="${CHESSCOACH_MODEL:-qwen2.5:7b-instruct}"
URL="${OLLAMA_URL:-http://ollama:11434}"

echo "[chesscoach] waiting for Ollama at ${URL} ..."
for _ in $(seq 1 60); do
    if curl -sf "${URL}/api/tags" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

if ! curl -sf "${URL}/api/tags" >/dev/null 2>&1; then
    echo "[chesscoach] WARNING: Ollama not reachable; the app will fall back to"
    echo "            the deterministic template explainer (no LLM prose)."
else
    if curl -sf "${URL}/api/tags" | grep -q "\"${MODEL}\""; then
        echo "[chesscoach] model '${MODEL}' already present."
    else
        echo "[chesscoach] pulling '${MODEL}' (first run downloads a few GB; cached afterwards) ..."
        # Stream the pull; show status lines as they arrive.
        curl -sf -X POST "${URL}/api/pull" -d "{\"name\":\"${MODEL}\"}" \
            | grep -oE '"status":"[^"]*"' | uniq || true
        echo "[chesscoach] pull complete."
    fi
fi

echo "[chesscoach] ready."
echo "            Web UI  : open http://localhost:8000 in your browser"
echo "            CLI too : docker compose exec chesscoach python coach_cli.py play --level 3"

exec "$@"
