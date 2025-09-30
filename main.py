import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
from src.app import create_app

app = create_app()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, use_reloader=False, debug=False)
