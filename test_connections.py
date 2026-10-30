import os
import sys
from dotenv import load_dotenv

load_dotenv()

print("--- 1. Testing Telegram Token ---")
token = os.getenv("TELEGRAM_BOT_TOKEN")
try:
    import asyncio
    from telegram import Bot
    async def test_bot():
        b = Bot(token=token)
        me = await b.get_me()
        print(f"Telegram Bot OK: @{me.username} ({me.first_name})")
    asyncio.run(test_bot())
except Exception as e:
    print(f"Telegram Bot Error: {e}")

print("\n--- 2. Testing Gemini API Key ---")
gemini_key = os.getenv("GEMINI_API_KEY")
try:
    from google import genai
    client = genai.Client(api_key=gemini_key)
    # Check what models exist or call interactions
    print("Calling Gemini...")
    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        input="Привет! Напиши 'работает' если всё ок."
    )
    print("Gemini OK! Response:", interaction.output_text)
except Exception as e:
    print(f"Gemini Error: {e}")
    # Also test models.generate_content with gemini-2.5-flash or gemini-flash-latest
    try:
        res = client.models.generate_content(model="gemini-flash-latest", contents="Привет")
        print("Gemini generate_content OK:", res.text)
    except Exception as e2:
        print(f"Gemini fallback error: {e2}")

print("\n--- 3. Testing Google Sheets ---")
sheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
try:
    import gspread
    gc = gspread.service_account(filename=sa_file)
    sh = gc.open_by_key(sheet_id)
    print(f"Google Sheets OK! Document title: '{sh.title}'")
    for ws in sh.worksheets():
        print(f"  - Sheet: '{ws.title}' ({ws.row_count}x{ws.col_count})")
except Exception as e:
    print(f"Google Sheets Error: {e}")
