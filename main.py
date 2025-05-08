import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio
import logging

# --- Basic Logging Setup ---
# On Choreo.dev, this will output to the platform's logging stream
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')


# --- Load Environment Variables ---
# load_dotenv() will load from .env for local development
# On Choreo.dev, os.getenv will pick up variables set in the platform's environment
load_dotenv()

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
PREFIX = os.getenv('COMMAND_PREFIX', '!') # Default to '!' if not set
BOT_COLOR_STR = os.getenv('BOT_COLOR', '0x7289DA') # Default to Blurple

# Validate that BOT_COLOR_STR is a valid hex before conversion
try:
    BOT_COLOR = int(BOT_COLOR_STR, 16)
except ValueError:
    logger.warning(f"Invalid BOT_COLOR format: '{BOT_COLOR_STR}'. Using default Blurple (0x7289DA).")
    BOT_COLOR = 0x7289DA


if not TOKEN:
    logger.critical("FATAL ERROR: DISCORD_BOT_TOKEN not found. Ensure it's set in your environment variables (e.g., .env locally, or platform settings on Choreo.dev).")
    exit() # Critical failure, bot cannot start
if not OPENROUTER_API_KEY:
    # Non-critical, lyrics command will just inform user API key is missing
    logger.warning("WARNING: OPENROUTER_API_KEY not found. Lyrics command will not function.")

# --- Bot Intents ---
intents = discord.Intents.default()
intents.message_content = True # Required for reading message content for commands
intents.voice_states = True    # Required for voice channel operations

# --- Bot Initialization ---
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# --- Global Bot Attributes (accessible in cogs) ---
bot.bot_color = discord.Color(BOT_COLOR)
bot.openrouter_api_key = OPENROUTER_API_KEY # Pass API key to cogs

# --- Event: Bot Ready ---
@bot.event
async def on_ready():
    logger.info(f'{bot.user.name} has connected to Discord!')
    logger.info(f'Bot ID: {bot.user.id}')
    logger.info(f'Command Prefix: {PREFIX}')
    logger.info(f'Using Bot Color: #{BOT_COLOR:06X}')
    if not bot.openrouter_api_key:
        logger.warning("OpenRouter API Key is not set. The 'lyrics' command will be unavailable.")
    await bot.change_presence(activity=discord.Game(name=f"{PREFIX}help | Groovin'"))
    logger.info("Presence updated.")
    logger.info("IMPORTANT FOR CHOREO.DEV (and similar platforms): Ensure FFmpeg is installed in your deployment environment, or music playback will fail!")


# --- Load Cogs ---
async def load_cogs():
    logger.info("Attempting to load cogs...")
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and not filename.startswith('_'): # Ignore files like __init__.py
            cog_name = filename[:-3]
            try:
                await bot.load_extension(f'cogs.{cog_name}')
                logger.info(f'Successfully loaded cog: {cog_name}')
            except commands.ExtensionAlreadyLoaded:
                logger.info(f'Cog {cog_name} already loaded.')
            except Exception as e:
                logger.error(f'Failed to load cog {cog_name}: {e}', exc_info=True) # Log full traceback

# --- Custom Help Command ---
@bot.command(name="help")
async def custom_help(ctx, *, command_name: str = None):
    """Shows this message or info about a command."""
    embed = discord.Embed(title="🎧 MelodyMaestro Help 🎧", color=bot.bot_color)
    
    if command_name:
        command = bot.get_command(command_name)
        if command and not command.hidden:
            embed.title = f"Help: {PREFIX}{command.qualified_name}" # Use qualified_name for subcommands if any
            aliases = ", ".join([PREFIX + alias for alias in command.aliases]) if command.aliases else "None"
            # Construct usage string carefully
            params = command.signature
            usage = f"{PREFIX}{command.qualified_name} {params}"
            
            description = command.help or command.short_doc or 'No description provided.'
            embed.description = f"{description}\n\n**Usage:** `{usage}`\n**Aliases:** {aliases}"
        else:
            embed.description = f"Sorry, I couldn't find a command called `{command_name}` or it's hidden."
            embed.color = discord.Color.red()
    else:
        embed.description = f"Hi {ctx.author.mention}! I'm MelodyMaestro, your personal DJ.\nUse `{PREFIX}help <command>` for more info on a specific command."
        
        # Categorize commands by cog
        for cog_name, cog_instance in bot.cogs.items():
            visible_commands = [cmd for cmd in cog_instance.get_commands() if not cmd.hidden]
            if visible_commands:
                cmd_list = []
                for cmd in sorted(visible_commands, key=lambda c: c.name): # Sort commands alphabetically
                    cmd_list.append(f"`{PREFIX}{cmd.name}` - {cmd.short_doc or 'No short description.'}")
                embed.add_field(name=f"🎵 {cog_name} Commands", value="\n".join(cmd_list), inline=False)
        
        embed.set_footer(text="Rock on! 🤘 | Built by YourName", icon_url=bot.user.avatar.url if bot.user.avatar else None) # Optional: add your name

    await ctx.send(embed=embed)

# --- Global Error Handler (Optional, but good practice) ---
@bot.event
async def on_command_error(ctx, error):
    if hasattr(ctx.command, 'on_error'): # If command has its own error handler, let it handle it
        return

    # This prevents any commands with local handlers being handled here.
    cog = ctx.cog
    if cog:
        if cog._get_overridden_method(cog.cog_command_error) is not None:
            return # Let cog-specific error handler take over

    error = getattr(error, 'original', error) # Get original error if it's wrapped

    if isinstance(error, commands.CommandNotFound):
        # Optional: send a message or just log and ignore
        # await ctx.send(embed=discord.Embed(title="🤷 Unknown Command", description=f"Sorry, I don't know the command `{ctx.invoked_with}`.", color=discord.Color.orange()))
        logger.warning(f"CommandNotFound: {ctx.invoked_with} by {ctx.author}")
        return
    elif isinstance(error, commands.DisabledCommand):
        await ctx.send(embed=discord.Embed(title="🚫 Command Disabled", description=f"`{ctx.command}` is currently disabled.", color=discord.Color.orange()))
    elif isinstance(error, commands.NoPrivateMessage):
        try:
            await ctx.author.send(embed=discord.Embed(title="🚫 DMs Not Allowed", description=f"`{ctx.command}` cannot be used in Direct Messages.", color=discord.Color.red()))
        except discord.Forbidden:
            pass # Can't send DMs to the user
    elif isinstance(error, commands.MissingPermissions):
        perms_needed = "\n".join([f"- {perm.replace('_', ' ').title()}" for perm in error.missing_permissions])
        embed = discord.Embed(title="🚫 Missing Permissions",
                              description=f"You are missing the following permission(s) to run this command:\n{perms_needed}",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BotMissingPermissions):
        perms_needed = "\n".join([f"- {perm.replace('_', ' ').title()}" for perm in error.missing_permissions])
        embed = discord.Embed(title="🤖 Bot Missing Permissions",
                              description=f"I am missing the following permission(s) to run this command:\n{perms_needed}\nPlease grant them to me!",
                              color=discord.Color.red())
        await ctx.send(embed=embed)
    else:
        # For other errors, log them and inform the user generically
        logger.error(f"Unhandled error in command {ctx.command}: {error}", exc_info=True)
        embed = discord.Embed(title="🔥 Oops! An Error Occurred",
                              description="Something went wrong while trying to run that command. The developers have been notified.",
                              color=discord.Color.dark_red())
        embed.set_footer(text="If this persists, please report it.")
        await ctx.send(embed=embed)


# --- Main Execution ---
async def main():
    async with bot:
        await load_cogs()
        logger.info("Starting bot...")
        await bot.start(TOKEN)

if __name__ == "__main__":
    # Add a reminder about FFmpeg for local runs too
    logger.info("Reminder: Ensure FFmpeg is installed and in your system's PATH for music functionality.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutting down via KeyboardInterrupt...")
    except Exception as e:
        logger.critical(f"An unrecoverable error occurred during bot startup or runtime: {e}", exc_info=True)
