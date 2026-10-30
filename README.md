# 🤖 Telegram-бот с AI-агентом и Google Sheets

Бот получает сообщения в Telegram, обрабатывает их через **Gemini AI** и может
читать/записывать данные в **Google Таблицу**. Аналог n8n-воркфлоу, но на чистом Python.

---

## 📋 Что нужно (всё бесплатно)

| Компонент | Где получить |
|---|---|
| Python 3.10+ | [python.org](https://www.python.org/downloads/) |
| Telegram Bot Token | [@BotFather](https://t.me/BotFather) |
| Gemini API Key | [Google AI Studio](https://aistudio.google.com/apikey) |
| Google Sheets сервисный аккаунт | [Google Cloud Console](https://console.cloud.google.com/) |

---

## 🚀 Пошаговая настройка

### Шаг 1: Создать Telegram-бота

1. Откройте Telegram и найдите **@BotFather**
2. Отправьте команду `/newbot`
3. Введите имя бота (например: `Мой AI Ассистент`)
4. Введите username бота (например: `my_ai_sheets_bot`)
5. **Скопируйте токен** — он выглядит так: `7123456789:AAHxxx...`

---

### Шаг 2: Получить Gemini API Key

1. Перейдите на [Google AI Studio](https://aistudio.google.com/apikey)
2. Войдите в Google-аккаунт
3. Нажмите **"Create API key"**
4. **Скопируйте ключ**

---

### Шаг 3: Настроить Google Sheets

#### 3.1. Включить Google Sheets API

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект (или выберите существующий)
3. Перейдите в **APIs & Services → Library**
4. Найдите **"Google Sheets API"** и нажмите **Enable**
5. Найдите **"Google Drive API"** и нажмите **Enable**

#### 3.2. Создать сервисный аккаунт

1. Перейдите в **APIs & Services → Credentials**
2. Нажмите **"Create Credentials" → "Service account"**
3. Введите имя (например: `telegram-bot`)
4. Нажмите **Create and Continue → Done**
5. Нажмите на созданный аккаунт → вкладка **Keys**
6. **Add Key → Create new key → JSON → Create**
7. Скачается файл — **переименуйте его в `service_account.json`**

#### 3.3. Создать таблицу и дать доступ

1. Создайте новую [Google Таблицу](https://sheets.google.com)
2. Добавьте заголовки в первую строку (например: `Имя | Сумма | Дата`)
3. **Скопируйте ID таблицы** из URL:
   ```
   https://docs.google.com/spreadsheets/d/ЭТОТ_ТЕКСТ_И_ЕСТЬ_ID/edit
   ```
4. Нажмите **"Поделиться"** (Share)
5. Вставьте email сервисного аккаунта (из файла `service_account.json`,
   поле `"client_email"`) и дайте доступ **"Редактор"**

---

### Шаг 4: Установить и запустить

```bash
# 1. Перейти в папку проекта
cd telegram-gemini-bot

# 2. Создать виртуальное окружение
python -m venv venv

# 3. Активировать (Windows)
venv\Scripts\activate

# 4. Установить зависимости
pip install -r requirements.txt

# 5. Скопировать шаблон настроек
copy .env.example .env

# 6. Открыть .env и заполнить своими ключами
notepad .env

# 7. Положить service_account.json в папку проекта

# 8. Запустить бота!
python bot.py
```

---

## 💬 Как пользоваться

После запуска откройте своего бота в Telegram и напишите:

| Что написать | Что бот сделает |
|---|---|
| `Какие листы есть в таблице?` | Покажет список листов |
| `Покажи все данные` | Прочитает строки из таблицы |
| `Добавь: Иван, 500, обед` | Добавит строку в таблицу |
| `Сколько записей?` | Посчитает строки |
| Любой вопрос | Ответит как AI-ассистент |

### Команды

- `/start` — приветствие
- `/reset` — очистить историю диалога
- `/help` — справка

---

## 📁 Структура проекта

```
telegram-gemini-bot/
├── bot.py              # Telegram-бот (точка входа)
├── gemini_agent.py     # AI-агент с Gemini + tools
├── sheets_tools.py     # Функции Google Sheets
├── config.py           # Загрузка настроек
├── requirements.txt    # Зависимости Python
├── .env                # Ваши ключи (НЕ делитесь!)
├── .env.example        # Шаблон ключей
└── service_account.json # Ключ Google (НЕ делитесь!)
```

---

## ⚠️ Безопасность

> **Никогда не публикуйте** файлы `.env` и `service_account.json`!
> Они содержат секретные ключи доступа к вашим аккаунтам.
