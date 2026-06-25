"""
Entry point: runs Flask API + Telegram bot in parallel threads.
Railway runs: python run.py
"""
import os
import threading
import logging

logger = logging.getLogger(__name__)


def run_flask():
    from app import app
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Flask starting on port {port}…")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def run_bot():
    from bot import main as bot_main
    bot_main()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    flask_thread = threading.Thread(target=run_flask, daemon=True, name='flask')
    flask_thread.start()
    logger.info("Flask thread started")

    # Bot runs in main thread (handles its own event loop)
    run_bot()
