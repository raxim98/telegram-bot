#!/bin/bash
# Скрипт автоматической установки бота на любой Linux VPS (Ubuntu/Debian)
set -e

echo "=== Установка зависимостей ==="
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git

echo "=== Создание виртуального окружения ==="
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Настройка системной службы (systemd) для работы 24/7 ==="
CURRENT_DIR=$(pwd)
CURRENT_USER=$(whoami)

sudo bash -c "cat > /etc/systemd/system/telegram-bot.service <<EOL
[Unit]
Description=Telegram Gemini AI Sheets Bot (24/7)
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python $CURRENT_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL"

echo "=== Запуск службы ==="
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl restart telegram-bot
sudo systemctl status telegram-bot --no-pager

echo "=== Бот успешно запущен 24/7! ==="
