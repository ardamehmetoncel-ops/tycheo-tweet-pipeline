"""Entrypoint. `python run.py` -> start the local Draft Desk UI."""
from src.config import load_config
from src.web.app import app

if __name__ == "__main__":
    cfg = load_config()
    print(f"Draft Desk: {len(cfg['personas'])} personas, {len(cfg['sources'])} sources, "
          f"provider={cfg['settings']['llm']['provider']}")
    print("Open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
