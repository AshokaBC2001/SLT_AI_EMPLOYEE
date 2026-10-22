"""Starts the SLT AI Employee web app on http://localhost:8000

    .venv/bin/python app.py
"""
import uvicorn

from hiring import config, llm

if __name__ == "__main__":
    h = llm.health(force=True)
    print("\nSLT AI Employee")
    print(f"  Open in your browser: http://localhost:{config.APP_PORT}")
    print(f"  Model server: {config.MODEL_URL} -> {'running' if h['ok'] else 'NOT running'}"
          + ("" if h["ok"] else " (start it with ./start_model.sh in another terminal)"))
    print("  Stop with Control+C\n")
    uvicorn.run("hiring.server:app", host=config.APP_HOST, port=config.APP_PORT, log_level="warning")
