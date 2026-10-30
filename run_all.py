"""Master 24/7 Supervisor — runs BOTH the Telegram Bot and the AI Userbot together.

Designed for cloud hosting (Render.com, Railway.app, VPS, Docker):
  • Starts bot.py (Telegram Bot @AgenttgH_bot + Healthcheck HTTP server on $PORT)
  • Starts userbot.py (AI Userbot acting from your personal account)
  • Monitors both processes and auto-restarts if either crashes or drops connection
  • Graceful shutdown on termination signals
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

# ── Force UTF-8 logging on Windows ────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


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
