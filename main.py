import os
import revolt
from dotenv import load_dotenv
from openai import OpenAI
import asyncio # For potential reconnection delays if needed, though revolt.py handles much of it

# Load environment variables
load_dotenv()

# Configuration (ensure these match your .env file and Choreo settings)
REVOLT_TOKEN = os.getenv("REVOLT_TOKEN")
SHAPES_API_KEY = os.getenv("SHAPESINC_API_KEY") # Matching JS variable name
SHAPES_USERNAME = os.getenv("SHAPESINC_SHAPE_USERNAME") # Matching JS variable name

if not all([REVOLT_TOKEN, SHAPES_API_KEY, SHAPES_USERNAME]):
    print("Error: Missing one or more environment variables (REVOLT_TOKEN, SHAPESINC_API_KEY, SHAPESINC_SHAPE_USERNAME)")
    exit(1)

SHAPES_MODEL_NAME = f"shapesinc/{SHAPES_USERNAME}"
SHAPES_BASE_URL = "https://api.shapes.inc/v1/"

# Set up the Shapes API client
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

# Define the bot client
class ShapesBotClient(revolt.Client):
    async def on_ready(self):
        print(f"Logged in as {self.user.name} (ID: {self.user.id})")
        print("Bot is ready to receive messages.")
        if not shapes_api_available:
            print("WARNING: Shapes API client not initialized. Shape interactions will fail.")

    async def on_message(self, message: revolt.Message):
        # Ignore messages from bots (including self)
        if message.author.bot:
            return

        # Check if the message is a DM or if the bot is mentioned
        is_dm = isinstance(message.channel, revolt.DMChannel)
        # Check if bot's ID is in the list of mentioned user IDs
        is_mentioned = self.user.id in message.mention_ids

        if is_dm or is_mentioned:
            if is_dm:
                print(f"Message received in DM from {message.author.name}: '{message.content}'")
            if is_mentioned:
                print(f"Bot was mentioned by {message.author.name}: '{message.content}'")

            if not shapes_api_available:
                await message.reply("Sorry, the Shapes API is currently unavailable.", mention=False)
                return

            content_for_shape = message.content

            # Remove the mention from the message content if present and mentioned
            if is_mentioned and self.user.mention in content_for_shape: # self.user.mention is e.g. <@BOT_ID>
                content_for_shape = content_for_shape.replace(self.user.mention, "").strip()
            
            # If content is empty after removing mention (or was empty in DM)
            if not content_for_shape:
                await message.reply("Hello! How can I help you today?", mention=False)
                return

            print(f"Sending to Shapes API: '{content_for_shape}'")

            try:
                # Custom headers for Shapes API if needed (though user/channel usually for the main bot platform)
                # For Shapes, it's good to pass them if the shape is designed to use them.
                # The JS code didn't explicitly pass X-User-Id/X-Channel-Id to shapes_client.chat.completions.create
                # but it's good practice if your shape utilizes this context.
                # Let's assume the OpenAI client handles API key auth, and Shapes uses User/Channel context if provided.
                # For this direct translation, we will mirror the JS which doesn't add extra headers to this specific call.

                response = shapes_client.chat.completions.create(
                    model=SHAPES_MODEL_NAME,
                    messages=[
                        {"role": "user", "content": content_for_shape}
                    ],
                    temperature=0.7,  # From the JS code
                    max_tokens=1000   # From the JS code
                )

                ai_response = response.choices[0].message.content.strip()
                print(f"AI Response: '{ai_response}'")

                if ai_response:
                    await message.reply(ai_response, mention=False)
                else:
                    await message.reply("The shape returned an empty response.", mention=False)

            except Exception as e:
                print(f"Error processing message with Shapes API: {e}")
                if hasattr(e, 'response') and e.response: # Check for OpenAI specific error details
                     print(f"Shapes API Error Response: {e.response.text}") # Or e.response.json()
                await message.reply("Sorry, I encountered an error while processing your request.", mention=False)

# --- Main Execution ---
async def main():
    # The JS code uses `https` directly. `revolt.py` handles HTTP internally.
    # We use `revolt.ClientSession` which is automatically managed by `revolt.py`
    # For raw HTTP outside of revolt.py, you'd use a library like `aiohttp` for async or `requests` for sync.
    # But here, all Revolt API interaction is via `revolt.py` client.
    
    client = ShapesBotClient()
    
    print("Starting bot...")
    try:
        await client.start(REVOLT_TOKEN)
    except revolt.errors.LoginError as e:
        print(f"Failed to log in: {e}. Please check your REVOLT_TOKEN.")
    except Exception as e:
        print(f"An error occurred while starting or running the bot: {e}")
    finally:
        print("Bot is shutting down or encountered a critical error.")
        # Ensure client is closed if it was started
        if client.is_ready(): # Check if client was ever ready
            await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown requested by user (Ctrl+C).")