import os
import revolt
from dotenv import load_dotenv
from openai import OpenAI
import asyncio

print("--- SCRIPT STARTING - DEBUG MODE ---")
print("Attempting to load .env file (for local testing, Choreo uses platform env vars)...")
load_dotenv() # This is mainly for local, Choreo provides them directly

print("\n--- PRINTING ALL ENVIRONMENT VARIABLES SEEN BY THE SCRIPT ---")
for key, value in os.environ.items():
    # For security, let's only print full values for the ones we care about or partially hide others
    if key in ["REVOLT_TOKEN", "SHAPESINC_API_KEY", "SHAPESINC_SHAPE_USERNAME"]:
        print(f"ENV VAR: {key} = {value}")
    elif "TOKEN" in key.upper() or "KEY" in key.upper() or "SECRET" in key.upper():
        print(f"ENV VAR: {key} = {value[:3]}...{value[-3:] if len(value) > 6 else ''} (partially hidden)")
    # else:
    # print(f"ENV VAR: {key} = {value}") # Uncomment to see all other env vars, can be noisy

print("\n--- CHECKING SPECIFIC EXPECTED ENVIRONMENT VARIABLES ---")

REVOLT_TOKEN = os.getenv("REVOLT_TOKEN")
SHAPES_API_KEY = os.getenv("SHAPESINC_API_KEY")
SHAPES_USERNAME = os.getenv("SHAPESINC_SHAPE_USERNAME")

print(f"Value of REVOLT_TOKEN: {REVOLT_TOKEN}")
print(f"Value of SHAPESINC_API_KEY: {SHAPES_API_KEY[:5] + '...' if SHAPES_API_KEY else None}") # Print part of API key
print(f"Value of SHAPESINC_SHAPE_USERNAME: {SHAPES_USERNAME}")


if not all([REVOLT_TOKEN, SHAPES_API_KEY, SHAPES_USERNAME]):
    print("\n--- ERROR DETECTED ---")
    print("Error: Missing one or more environment variables. See values above.")
    if not REVOLT_TOKEN:
        print("REVOLT_TOKEN is missing or empty.")
    if not SHAPES_API_KEY:
        print("SHAPESINC_API_KEY is missing or empty.")
    if not SHAPES_USERNAME:
        print("SHAPESINC_SHAPE_USERNAME is missing or empty.")
    print("--- SCRIPT EXITING DUE TO MISSING ENV VARS ---")
    exit(1)
else:
    print("\n--- SUCCESS: All required environment variables found. ---")


# --- The rest of your bot code would normally go here ---
# For now, we can stop to focus on env vars. If they are found, the bot will proceed.

SHAPES_MODEL_NAME = f"shapesinc/{SHAPES_USERNAME}"
SHAPES_BASE_URL = "https://api.shapes.inc/v1/"

try:
    shapes_client = OpenAI(
        api_key=SHAPES_API_KEY,
        base_url=SHAPES_BASE_URL,
    )
    shapes_api_available = True
    print("Shapes API client initialized.")
except Exception as e:
    print(f"Error initializing Shapes API client: {e}")
    shapes_client = None
    shapes_api_available = False

class ShapesBotClient(revolt.Client):
    async def on_ready(self):
        print(f"Logged in as {self.user.name} (ID: {self.user.id})")
        print("Bot is ready to receive messages.")
        if not shapes_api_available:
            print("WARNING: Shapes API client not initialized. Shape interactions will fail.")
    # ... (rest of your on_message and other methods) ...
    async def on_message(self, message: revolt.Message):
        if message.author.bot: return
        is_dm = isinstance(message.channel, revolt.DMChannel)
        is_mentioned = self.user.id in message.mention_ids
        if is_dm or is_mentioned:
            print(f"Bot triggered by {'DM' if is_dm else 'mention'} from {message.author.name}")
            await message.reply(f"Env vars look OK! You said: {message.content}", mention=False)


async def main():
    client = ShapesBotClient()
    print("Starting bot with (presumably) correct env vars...")
    try:
        await client.start(REVOLT_TOKEN)
    except revolt.errors.LoginError as e:
        print(f"Failed to log in: {e}. Please check your REVOLT_TOKEN's VALUE.")
    except Exception as e:
        print(f"An error occurred while starting or running the bot: {e}")
    finally:
        print("Bot is shutting down or encountered a critical error.")
        if client.is_ready():
            await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested by user (Ctrl+C).")
