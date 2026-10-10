# chesscoach application image: Python + python-chess + the Stockfish engine.
# The LLM (Ollama) runs in its own container -- see docker-compose.yml.
FROM python:3.12-slim

# Stockfish is the source of truth; curl is used by the entrypoint to talk to
# the Ollama container's HTTP API.
RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV CHESSCOACH_STOCKFISH=/usr/games/stockfish \
    OLLAMA_URL=http://ollama:11434 \
    CHESSCOACH_MODEL=qwen2.5:7b-instruct \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
# Launch the web UI; the CLI is still available via `docker compose exec`.
CMD ["python", "-m", "webapp.server", "--host", "0.0.0.0", "--port", "8000"]
