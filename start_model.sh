#!/bin/bash
# Starts the local model with llama.cpp (no Ollama). Leave this terminal open.
# The first run downloads Gemma 3 4B (about 2.5 GB) from Hugging Face.
# To try another model:  SLT_MODEL="<huggingface repo>:<quant>" ./start_model.sh
cd "$(dirname "$0")"
MODEL="${SLT_MODEL:-ggml-org/gemma-3-4b-it-GGUF:Q4_K_M}"
PORT="${SLT_MODEL_PORT:-8080}"
if ! command -v llama-server >/dev/null 2>&1; then
  echo "llama-server was not found. Install llama.cpp first:"
  echo "  brew install llama.cpp"
  exit 1
fi
echo "Starting $MODEL on http://127.0.0.1:$PORT"
echo "Wait until you see that the server is listening, then start the app in another terminal."
# --no-mmproj: the app only sends text, so the image part of Gemma 3 (about 850 MB) is not loaded.
exec llama-server -hf "$MODEL" --host 127.0.0.1 --port "$PORT" -c 8192 --no-mmproj
