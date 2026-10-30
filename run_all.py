"""Master 24/7 Supervisor — runs BOTH the Telegram Bot and the AI Userbot together.

Designed for cloud hosting (Render.com, Railway.app, VPS, Docker):
  • Starts bot.py (Telegram Bot @AgenttgH_bot + Healthcheck HTTP server on $PORT)
  • Starts userbot.py (AI Userbot acting from your personal account)
  • Self-pinging background thread to prevent Render free-tier from sleeping after 15 minutes
  • Monitors both processes and auto-restarts if either crashes or drops connection
  • Graceful shutdown on termination signals
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request

# ── Force UTF-8 logging on Windows ────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _start_keep_alive_pinger():
    """Background thread that pings the Render service every 8 minutes to prevent sleep."""
    def pinger_loop():
        # Wait 60 seconds after startup before starting pings
        time.sleep(60)
        url = os.getenv("RENDER_EXTERNAL_URL") or "https://telegram-bot-24-7-i3cs.onrender.com"
        print(f"📡 [KEEP-ALIVE] Фоновый пингер запущен для: {url}")
        
        while True:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Render-KeepAlive-Supervisor/1.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print(f"💓 [KEEP-ALIVE] Ping {url} -> HTTP {resp.status} (таймер сна Render сброшен)")
            except Exception as e:
                print(f"⚠️ [KEEP-ALIVE] Ошибка пинга: {e}")
                
            # Ping every 8 minutes (480 seconds). Render sleeps after 15 minutes.
            time.sleep(480)

    t = threading.Thread(target=pinger_loop, daemon=True)
    t.start()


def main():
    print("=" * 65)
    print("🚀 ЗАПУСК ПОЛНОЙ СИСТЕМЫ: TELEGRAM BOT + AI-USERBOT (24/7)")
    print("=" * 65)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    python_bin = sys.executable

    bot_cmd = [python_bin, os.path.join(current_dir, "bot.py")]
    userbot_cmd = [python_bin, os.path.join(current_dir, "userbot.py")]

    print(f"• Запуск 1/2: Telegram-бот (@AgenttgH_bot)...")
    p_bot = subprocess.Popen(bot_cmd)

    print(f"• Запуск 2/2: AI-юзербот (личный аккаунт)...")
    p_userbot = subprocess.Popen(userbot_cmd)

    # Start self-pinging keep-alive thread
    _start_keep_alive_pinger()

    print("\n✅ Обе службы успешно запущены и работают параллельно!")
    print("=" * 65)

    def shutdown_handler(signum, frame):
        print(f"\n[SHUTDOWN] Получен сигнал {signum}. Завершение процессов...")
        p_bot.terminate()
        p_userbot.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    while True:
        try:
            time.sleep(5)

            # Monitor bot.py
            if p_bot.poll() is not None:
                print("⚠️ [SUPERVISOR] Telegram-бот неожиданно остановился. Перезапуск через 3 сек...")
                time.sleep(3)
                p_bot = subprocess.Popen(bot_cmd)

            # Monitor userbot.py
            if p_userbot.poll() is not None:
                print("⚠️ [SUPERVISOR] AI-юзербот неожиданно остановился. Перезапуск через 3 сек...")
                time.sleep(3)
                p_userbot = subprocess.Popen(userbot_cmd)

        except KeyboardInterrupt:
            shutdown_handler(signal.SIGINT, None)
        except Exception as e:
            print(f"⚠️ Ошибка в супервизоре: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
