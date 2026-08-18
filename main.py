import logging

from src.app import create_app
from src.config import Config

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

app = create_app()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, use_reloader=False, debug=False)
