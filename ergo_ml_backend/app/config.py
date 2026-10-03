"""
Loads ergo_ml_backend/.env (if present) into the environment, before anything
reads settings. Real environment variables win, so on Render the dashboard
values are used. .env is git-ignored — secrets never reach GitHub.
"""
import os

ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


def load_env(path: str = ENV_FILE) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
