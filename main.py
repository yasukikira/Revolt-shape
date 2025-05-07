import os
import revolt
from revolt.ext import commands
from dotenv import load_dotenv
from openai import OpenAI # For Shapes API

# --- Configuration ---
load_dotenv()
REVOLT_TOKEN = os.getenv("REVOLT_TOKEN")
SHAPES_API_KEY = os.getenv("SHAPES_API_KEY")
SHAPES_USERNAME = os.getenv("SHAPES_USERNAME")

if not all([REVOLT_TOKEN, SHAPES_API_KEY, SHAPES_USERNAME]):
    print("Error: Missing one or more environment variables (REVOLT_TOKEN, SHAPES_API_KEY, SHAPES_USERNAME)")
    exit(1)

SHAPES_MODEL_NAME = f"shapesinc/{SHAPES_USERNAME}"
SHAPES_BASE_URL = "https://api.shapes.inc/v1/"

# --- Shapes API Client ---
try:
    # Initialize a base client. We'll re-initialize with headers per request for Shapes.
    shapes_client_config = {
        "api_key": SHAPES_API_KEY,
        "base_url": SHAPES_BASE_URL,
    }
    # Test basic client initialization
    OpenAI(**shapes_client_config)
    print("Shapes API client configuration seems OK.")
    shapes_api_available = True
except Exception as e:
    print(f"Error initializing Shapes API client template: {e}")
    shapes_api_available = False

# --- Bot Setup ---
class MyClient(commands.CommandsClient):
    async def get_prefix(self, message: revolt.Message):
        return "/" # Using slash commands

    async def on_ready(self):
        print(f"Logged in as {self.user.name} (ID: {self.user.id})")
        print("Bot is ready!")
        if not shapes_api_available:
            print("WARNING: Shapes API client could not be initialized. Shape interactions will fail.")

    async def on_message(self, message: revolt.Message):
        if message.author.bot: # Ignore messages from bots (including self)
            return

        # If message starts with command prefix, let the command system handle it.
        # Commands themselves will use ctx.reply().
        if message.content.startswith(await self.get_prefix(message)):
            await self.process_commands(message)
            return # Command processed (or attempted and failed), stop further processing for Shapes.

        # If not a command, check for mention or reply-to-bot for Shapes API interaction
        should_respond_with_shape = False
        interaction_type = "" # For logging

        # 1. Was the bot mentioned?
        if self.user.id in message.mention_ids:
            should_respond_with_shape = True
            interaction_type = "mention"
            print(f"Bot was mentioned by {message.author.name} in channel {message.channel.id}: '{message.content}'")

        # 2. Is this message a reply to one of the bot's messages?
        #    (Only check if not already triggered by mention)
        if not should_respond_with_shape and message.reply_ids:
            try:
                # The first ID in reply_ids is the direct message being replied to.
                replied_to_message_id = message.reply_ids[0]
                replied_to_message = await self.fetch_message(replied_to_message_id) # Fetches from cache or API

                if replied_to_message and replied_to_message.author.id == self.user.id:
                    should_respond_with_shape = True
                    interaction_type = "reply-to-bot"
                    print(f"User {message.author.name} replied to bot's message in channel {message.channel.id}: '{message.content}'")
            except revolt.errors.RevoltError as e: # Catch Revolt-specific API errors
                print(f"Revolt API Error fetching replied-to message {message.reply_ids[0]}: {e}")
            except Exception as e: # Catch any other unexpected errors
                print(f"Unexpected error fetching replied-to message: {e}")
        
        if should_respond_with_shape and shapes_api_available:
            print(f"Processing message for Shapes API (type: {interaction_type}) from {message.author.name}: '{message.content}'")
            try:
                # Custom headers for Shapes API
                headers = {
                    "X-User-Id": str(message.author.id), # Ensure IDs are strings
                    "X-Channel-Id": str(message.channel.id)
                }
                
                # Create a client instance with headers for this specific request
                current_shapes_client = OpenAI(
                    api_key=SHAPES_API_KEY, # Fetched from env
                    base_url=SHAPES_BASE_URL,
                    default_headers=headers 
                )

                # Send the user's message content to the shape
                # For mentions, the shape will see the mention text if not stripped.
                # For replies, it's just the new message content.
                # This behavior is generally fine; LLMs can often handle/ignore mentions.
                content_for_shape = message.content

                response = current_shapes_client.chat.completions.create(
                    model=SHAPES_MODEL_NAME,
                    messages=[
                        {"role": "user", "content": content_for_shape}
                    ]
                )
                
                shape_reply_content = response.choices[0].message.content.strip()
                if shape_reply_content:
                    await message.reply(shape_reply_content, mention=False)
                else:
                    await message.reply("The shape returned an empty response.", mention=False)
            except Exception as e:
                error_message = f"Sorry, I couldn't get a response from the shape. Error: {type(e).__name__}"
                print(f"Error interacting with Shapes API: {e}")
                # Avoid sending overly detailed/technical error messages to users if possible
                if "Rate limit" in str(e): # Example of more user-friendly error
                    error_message = "The Shape API is currently busy (rate limited). Please try again in a moment."
                await message.reply(error_message, mention=False)
        elif should_respond_with_shape and not shapes_api_available:
            await message.reply("The Shapes API is currently unavailable. Please try again later.", mention=False)


client = MyClient()

# --- Commands ---
@client.command(name="wack")
async def wack_command(ctx: commands.Context):
    """'Wacks' the shape's short-term memory for this conversation by sending a reset instruction."""
    if not shapes_api_available:
        await ctx.reply("Shapes API is not available, cannot perform 'wack'.", mention=False)
        return

    await ctx.reply("Attempting to 'wack' the shape's short-term memory for this conversation...", mention=False)
    try:
        instruction = "Please disregard our previous conversation in this channel and start fresh. Consider this a reset of our current context."
        
        headers = {
            "X-User-Id": str(ctx.author.id),
            "X-Channel-Id": str(ctx.channel.id)
        }
        current_shapes_client = OpenAI(
            api_key=SHAPES_API_KEY,
            base_url=SHAPES_BASE_URL,
            default_headers=headers
        )
        
        response = current_shapes_client.chat.completions.create(
            model=SHAPES_MODEL_NAME,
            messages=[
                {"role": "user", "content": instruction}
            ]
        )
        reply_content = response.choices[0].message.content.strip()
        await ctx.reply(f"Shape's response to reset: \"{reply_content}\"\n(Hopefully, it understood the 'wack'!)", mention=False)
    except Exception as e:
        print(f"Error during /wack command: {e}")
        await ctx.reply(f"An error occurred while trying to 'wack' the shape: {e}", mention=False)

@client.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def purge_command(ctx: commands.Context, amount: int):
    """Deletes a certain amount of messages in the current channel (up to 100)."""
    if amount <= 0:
        await ctx.reply("Please provide a positive number of messages to delete.", mention=False)
        return
    if amount > 100: # Revolt API limits bulk delete to 100 messages at once
        await ctx.reply("You can only purge up to 100 messages at a time. Setting to 100.", mention=False)
        amount = 100
    
    try:
        # The command message itself will be deleted by default by `ctx.channel.purge` if it's among the `amount`.
        # We can send a preliminary message first.
        progress_msg = await ctx.reply(f"Attempting to purge {amount} messages (excluding this one)...", mention=False)
        
        # Purge messages *before* the command message.
        # To also delete the command message, you'd fetch 'amount + 1' or delete it separately.
        # For simplicity, this purges 'amount' messages *older* than the command message.
        # If you want to include the command message, you might need to adjust or fetch differently.
        # A common approach is to delete the command message first, then purge `amount`.
        # Or fetch `amount` messages ending *before* the command message.

        # Let's try to delete the command message itself, then `amount` previous ones.
        try:
            await ctx.message.delete() # Delete the command message
        except revolt.errors.Forbidden:
            await progress_msg.edit(content="Couldn't delete the command message (no permission), but will proceed with others.", mention=False)
        except revolt.errors.HTTPError as e:
            await progress_msg.edit(content=f"Couldn't delete the command message (error: {e}), but will proceed with others.", mention=False)


        deleted_messages = await ctx.channel.purge(limit=amount, before=ctx.message.id if ctx.message else None) # Purge messages before the original command
        
        confirmation_text = f"Successfully purged {len(deleted_messages)} messages."
        if progress_msg: # If progress_msg still exists (wasn't deleted in a very fast purge)
            await progress_msg.edit(content=confirmation_text, mention=False)
        else: # If progress_msg was somehow deleted or not sent
             await ctx.channel.send(confirmation_text) # Fallback, won't be a reply

        # Optionally, delete the confirmation message after a few seconds
        # import asyncio
        # await asyncio.sleep(5)
        # if progress_msg: await progress_msg.delete()

    except revolt.errors.Forbidden:
        await ctx.reply("I don't have permission to delete messages in this channel.", mention=False)
    except revolt.errors.HTTPError as e: # More specific Revolt error
        await ctx.reply(f"A Revolt API error occurred during purge: {e}", mention=False)
    except Exception as e:
        await ctx.reply(f"An unexpected error occurred during purge: {e}", mention=False)
        print(f"Error during /purge: {e}")

@purge_command.error
async def purge_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("You (or the bot) do not have permission to use this command (Bot needs 'Manage Messages').", mention=False)
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Invalid amount. Please provide a number (e.g., `/purge 10`).", mention=False)
    elif isinstance(error, commands.CommandInvokeError) and isinstance(error.original, revolt.errors.Forbidden):
        # This can catch Forbidden if it happens deeper within the command logic before our try-except
        await ctx.reply("I lack the necessary permissions to delete messages in this channel.", mention=False)
    else:
        await ctx.reply(f"An unexpected error occurred with the purge command: {error}", mention=False)
        print(f"Unhandled error in purge_command: {error} (Type: {type(error)})")

# --- Run the Bot ---
if __name__ == "__main__":
    if REVOLT_TOKEN:
        client.run(REVOLT_TOKEN)
    else:
        print("REVOLT_TOKEN not found in environment variables. Bot cannot start.")
