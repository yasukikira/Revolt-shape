import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import aiohttp # For OpenRouter API
import logging
import datetime
from collections import deque # For queue

logger = logging.getLogger('discord.music_cog')

# --- yt-dlp Options ---
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s', # Not strictly needed if not downloading
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'skip_download': True, # Ensure we only extract info and stream URL
    'preferredcodec': 'mp3', # Prefer mp3 if available
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3', # Request mp3 for streaming if possible
    }],
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin', # Add -nostdin
    'options': '-vn -loglevel error', # Reduce ffmpeg log spam, only show errors
}

# --- Helper to create styled embeds ---
def create_embed(ctx_or_bot, title, description="", color=None, **kwargs):
    bot_instance = ctx_or_bot.bot if isinstance(ctx_or_bot, commands.Context) else ctx_or_bot
    actual_color = color if color is not None else bot_instance.bot_color
    
    embed = discord.Embed(title=title, description=description, color=actual_color)
    if bot_instance.user: # Ensure bot.user is available (after on_ready)
        embed.set_footer(text=f"MelodyMaestro | {bot_instance.user.name}", icon_url=bot_instance.user.avatar.url if bot_instance.user.avatar else None)
    else:
        embed.set_footer(text="MelodyMaestro") # Fallback if bot.user not ready

    if 'timestamp' in kwargs and kwargs['timestamp']:
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    if 'author_name' in kwargs and 'author_icon' in kwargs:
         embed.set_author(name=kwargs['author_name'], icon_url=kwargs['author_icon'])
    return embed

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.current_song = {}
        self.loop_mode = {}
        self.auto_leave_timers = {}
        self.check_activity.start()

    def get_queue(self, guild_id):
        return self.queues.setdefault(guild_id, deque())

    def get_loop_mode(self, guild_id):
        return self.loop_mode.get(guild_id, "off")

    async def _ensure_voice(self, ctx):
        if not ctx.author.voice:
            await ctx.send(embed=create_embed(ctx, "🚫 Voice Channel Required", "You need to be in a voice channel to use this command!", discord.Color.red()))
            return None
        
        voice_client = ctx.guild.voice_client
        if voice_client and voice_client.channel != ctx.author.voice.channel:
            try:
                await voice_client.move_to(ctx.author.voice.channel)
            except asyncio.TimeoutError:
                await ctx.send(embed=create_embed(ctx, "⌛ Timeout", "Could not move to your voice channel. Please try again.", discord.Color.orange()))
                return None
        elif not voice_client:
            try:
                voice_client = await ctx.author.voice.channel.connect(timeout=15.0, reconnect=True)
            except asyncio.TimeoutError:
                await ctx.send(embed=create_embed(ctx, "⌛ Timeout", "Could not connect to your voice channel. Please try again.", discord.Color.orange()))
                return None
            except discord.ClientException as e:
                await ctx.send(embed=create_embed(ctx, "⚠️ Connection Issue", f"Could not connect: {e}", discord.Color.orange()))
                return None

        if voice_client: self._reset_auto_leave_timer(ctx.guild.id)
        return voice_client

    async def _play_next(self, guild_id):
        if guild_id not in self.current_song and guild_id not in self.queues: return
        
        voice_client = self.bot.get_guild(guild_id).voice_client if self.bot.get_guild(guild_id) else None
        if not voice_client or not voice_client.is_connected():
            logger.info(f"Guild {guild_id}: Voice client not connected or guild not found. Clearing state.")
            self.current_song.pop(guild_id, None)
            self.queues.pop(guild_id, None)
            self.loop_mode.pop(guild_id, None)
            self._cancel_auto_leave_timer(guild_id)
            return

        queue = self.get_queue(guild_id)
        loop = self.get_loop_mode(guild_id)
        
        next_song_info = None
        # Handle looping song
        if loop == "song" and self.current_song.get(guild_id):
            next_song_info = self.current_song[guild_id]
        # Handle queue
        elif queue:
            next_song_info = queue.popleft()
            if loop == "queue" and self.current_song.get(guild_id): # If queue loop is on, add previous song to end
                queue.append(self.current_song[guild_id])
        # Handle queue loop when only one song was in queue and now it's current
        elif loop == "queue" and self.current_song.get(guild_id) and not queue:
             next_song_info = self.current_song[guild_id] # Play current again

        if next_song_info:
            self.current_song[guild_id] = next_song_info
            try:
                # Re-fetch stream URL if it's old or might have expired (common for yt-dlp stream URLs)
                # This is a more robust approach but adds slight delay.
                # For simplicity, the original code assumes the URL is still valid.
                # If you face issues with "Forbidden" or expired stream URLs, uncomment and adapt:
                # with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
                #     fresh_info = ydl.extract_info(next_song_info['webpage_url'], download=False)
                # stream_url = fresh_info['url']
                
                stream_url = next_song_info['url'] # Assuming URL is fresh enough

                player = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS)
                voice_client.play(player, after=lambda e: self.bot.loop.create_task(self._play_next_after_error_check(guild_id, e)))
                
                # Announce new song
                text_channel_id = next_song_info.get('text_channel_id')
                if text_channel_id:
                    text_channel = self.bot.get_channel(text_channel_id)
                    if text_channel:
                        embed = create_embed(self.bot, "🎶 Now Playing", 
                                             f"[{discord.utils.escape_markdown(next_song_info['title'])}]({next_song_info['webpage_url']})",
                                             author_name=f"Requested by {next_song_info['requester']}",
                                             author_icon=next_song_info['requester_avatar'])
                        embed.set_thumbnail(url=next_song_info['thumbnail'])
                        embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=next_song_info['duration'])), inline=True)
                        try:
                            await text_channel.send(embed=embed)
                        except discord.Forbidden:
                            logger.warning(f"Guild {guild_id}: Missing send permissions in channel {text_channel_id}.")
                        except Exception as e_send:
                            logger.error(f"Guild {guild_id}: Error sending 'Now Playing' message: {e_send}")


            except Exception as e:
                logger.error(f"Guild {guild_id}: Error playing {next_song_info.get('title', 'unknown song')}: {e}", exc_info=True)
                text_channel_id = next_song_info.get('text_channel_id')
                if text_channel_id:
                    text_channel = self.bot.get_channel(text_channel_id)
                    if text_channel:
                        try:
                            await text_channel.send(embed=create_embed(self.bot, "❌ Playback Error", f"Could not play: {discord.utils.escape_markdown(next_song_info.get('title', 'this song'))}.\nSkipping. Error: `{str(e)[:100]}`", discord.Color.red()))
                        except discord.Forbidden:
                             logger.warning(f"Guild {guild_id}: Missing send permissions in channel {text_channel_id} for error message.")
                self.bot.loop.create_task(self._play_next_after_error_check(guild_id, e))
        else:
            self.current_song.pop(guild_id, None)
            if voice_client and voice_client.is_connected() and not voice_client.is_playing():
                self._start_auto_leave_timer(guild_id)
                # Optional: Send a "Queue finished" message
                # last_text_channel_id = getattr(self, f"last_text_channel_{guild_id}", None)
                # if last_text_channel_id:
                #     text_channel = self.bot.get_channel(last_text_channel_id)
                #     if text_channel:
                #         await text_channel.send(embed=create_embed(self.bot, "🏁 Queue Finished", "No more songs to play.", discord.Color.light_grey()))


    async def _play_next_after_error_check(self, guild_id, error):
        if error:
            logger.error(f"Player error in guild {guild_id}: {error}")
        await self._play_next(guild_id)


    @commands.command(name="play", aliases=['p'], short_doc="Plays a song or adds to queue.")
    async def play(self, ctx: commands.Context, *, query: str):
        """
        Plays a song from YouTube, SoundCloud, etc., or adds it to the queue.
        Provide a song name/URL. Use `!play <playlist_url> playlist` for playlists.
        """
        voice_client = await self._ensure_voice(ctx)
        if not voice_client:
            return

        # Store the text channel ID for this guild if play command is successful
        setattr(self, f"last_text_channel_{ctx.guild.id}", ctx.channel.id)

        async with ctx.typing():
            songs_to_add = []
            is_playlist = "playlist" in query.lower() and ("youtube.com/playlist" in query or "soundcloud.com/sets" in query) # Basic playlist detection
            
            temp_ytdl_opts = YTDL_OPTS.copy()
            if is_playlist:
                temp_ytdl_opts['noplaylist'] = False # Allow playlist processing
                temp_ytdl_opts['extract_flat'] = 'discard_in_playlist' # Get full info for playlist items
                temp_ytdl_opts['playlistend'] = 10 # Limit playlist items for now to avoid abuse/long waits
                await ctx.send(embed=create_embed(ctx, "🔄 Processing Playlist...", f"Attempting to load up to {temp_ytdl_opts['playlistend']} songs. This might take a moment.", discord.Color.blue()))
            else:
                temp_ytdl_opts['noplaylist'] = True


            try:
                with yt_dlp.YoutubeDL(temp_ytdl_opts) as ydl:
                    search_query = query.replace(" playlist", "").strip() # Remove "playlist" keyword for search
                    if not search_query.startswith(('http://', 'https://')):
                        search_query = f"ytsearch:{search_query}" # Default to YouTube search

                    info = ydl.extract_info(search_query, download=False)

                if 'entries' in info: # Playlist or search results
                    if not info['entries']:
                        await ctx.send(embed=create_embed(ctx, "🤔 Not Found", f"Couldn't find anything for `{query}`.", discord.Color.orange()))
                        return
                    
                    # If it was a search and not explicitly a playlist, take the first item.
                    # If it WAS a playlist, info['entries'] will contain the playlist items.
                    entries_to_process = info['entries'] if is_playlist else [info['entries'][0]]
                    
                    for entry in entries_to_process:
                        if not entry: continue # Skip None entries if any
                        # Some playlist entries might need re-extraction if 'url' is missing
                        stream_url = entry.get('url')
                        if not stream_url:
                             # If it's from a playlist and lacks a direct URL, it might be a partial entry.
                             # Try to re-extract full info for this specific item.
                             logger.info(f"Re-extracting stream URL for playlist item: {entry.get('title', entry.get('id', 'N/A'))}")
                             try:
                                 with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl_single: # Use non-playlist opts
                                     single_info = ydl_single.extract_info(entry.get('webpage_url') or entry.get('url'), download=False) # Use webpage_url if available
                                 stream_url = single_info.get('url')
                                 entry = single_info # Update entry with full info
                             except Exception as re_extract_err:
                                 logger.error(f"Failed to re-extract stream URL for {entry.get('title')}: {re_extract_err}")
                                 continue # Skip this song

                        if not stream_url:
                            logger.warning(f"Could not find stream URL for {entry.get('title')}. Skipping.")
                            continue


                        song = {
                            'id': entry.get('id'),
                            'url': stream_url,
                            'title': entry.get('title', 'Unknown Title'),
                            'thumbnail': entry.get('thumbnail'),
                            'duration': entry.get('duration', 0),
                            'webpage_url': entry.get('webpage_url', entry.get('original_url', entry.get('url'))),
                            'requester': ctx.author.display_name,
                            'requester_avatar': ctx.author.avatar.url if ctx.author.avatar else None,
                            'text_channel_id': ctx.channel.id
                        }
                        songs_to_add.append(song)

                else: # Single video
                    stream_url = info.get('url')
                    if not stream_url: # Should be rare for single extractions but check anyway
                        logger.warning(f"Initial extraction for single song '{info.get('title')}' did not yield a stream URL directly. Re-attempting.")
                        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl_single:
                             info = ydl_single.extract_info(info.get('webpage_url') or info.get('original_url'), download=False)
                        stream_url = info.get('url')
                    
                    if not stream_url:
                        await ctx.send(embed=create_embed(ctx, "❌ Error", "Could not retrieve a playable stream for this song.", discord.Color.red()))
                        return

                    song = {
                        'id': info.get('id'),
                        'url': stream_url,
                        'title': info.get('title', 'Unknown Title'),
                        'thumbnail': info.get('thumbnail'),
                        'duration': info.get('duration', 0),
                        'webpage_url': info.get('webpage_url'),
                        'requester': ctx.author.display_name,
                        'requester_avatar': ctx.author.avatar.url if ctx.author.avatar else None,
                        'text_channel_id': ctx.channel.id
                    }
                    songs_to_add.append(song)
            
            except yt_dlp.utils.DownloadError as e: # Catch yt-dlp specific errors
                 logger.error(f"yt-dlp DownloadError for '{query}': {e}")
                 error_msg = str(e)
                 if "is not available" in error_msg or "Unsupported URL" in error_msg:
                     await ctx.send(embed=create_embed(ctx, "🚫 Not Available", f"This video/song might be unavailable, private, or region-locked.\n`{error_msg[:200]}`", discord.Color.orange()))
                 elif "Please log in" in error_msg:
                     await ctx.send(embed=create_embed(ctx, "🔒 Login Required", f"This video requires login, which the bot cannot do.\n`{error_msg[:200]}`", discord.Color.orange()))
                 else:
                     await ctx.send(embed=create_embed(ctx, "❌ yt-dlp Error", f"Could not process your request: `{error_msg[:1000]}`", discord.Color.red()))
                 return
            except Exception as e:
                logger.error(f"Error extracting song info for '{query}': {e}", exc_info=True)
                await ctx.send(embed=create_embed(ctx, "❌ Error", f"Could not process your request: `{str(e)[:1000]}`", discord.Color.red()))
                return

        if not songs_to_add:
            if not is_playlist: # Only show if it wasn't a playlist that just failed to find items
                await ctx.send(embed=create_embed(ctx, "🤔 Not Found", f"Couldn't find a playable track for `{query}`.", discord.Color.orange()))
            return

        queue = self.get_queue(ctx.guild.id)
        for song_data in songs_to_add:
            queue.append(song_data)

        if not voice_client.is_playing() and not self.current_song.get(ctx.guild.id):
            await self._play_next(ctx.guild.id)
        else:
            if len(songs_to_add) == 1:
                song = songs_to_add[0]
                embed = create_embed(ctx, "➕ Added to Queue", f"[{discord.utils.escape_markdown(song['title'])}]({song['webpage_url']})")
                embed.set_thumbnail(url=song['thumbnail'])
                embed.add_field(name="Position", value=len(queue), inline=True)
                await ctx.send(embed=embed)
            else:
                embed = create_embed(ctx, "➕ Playlist Added", f"Added **{len(songs_to_add)}** songs to the queue.")
                await ctx.send(embed=embed)
        
        self._reset_auto_leave_timer(ctx.guild.id)

    @commands.command(aliases=['s', 'fs'], short_doc="Skips the current song.")
    async def skip(self, ctx: commands.Context):
        """Skips the currently playing song. Force skip if you are admin/DJ (not implemented)."""
        voice_client = ctx.guild.voice_client
        if not voice_client or not (voice_client.is_playing() or voice_client.is_paused()): # Check paused too
            await ctx.send(embed=create_embed(ctx, "🤷 Nothing to Skip", "I'm not playing anything right now.", discord.Color.orange()))
            return

        current = self.current_song.get(ctx.guild.id)
        title_to_skip = discord.utils.escape_markdown(current['title']) if current else "the current song"
        
        voice_client.stop() # This will trigger 'after' in play, which calls _play_next
        await ctx.send(embed=create_embed(ctx, "⏭️ Skipped", f"Skipped **{title_to_skip}** by {ctx.author.mention}."))
        self._reset_auto_leave_timer(ctx.guild.id) # Reset timer as skip is an activity

    @commands.command(aliases=['disconnect', 'dc', 'leave', 'fuckoff'], short_doc="Stops playback and leaves.")
    async def stop(self, ctx: commands.Context):
        """Stops the music, clears the queue, and disconnects the bot."""
        voice_client = ctx.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await ctx.send(embed=create_embed(ctx, "🤷 Not Connected", "I'm not in a voice channel.", discord.Color.orange()))
            return

        # Clear state for this guild
        self.queues.pop(ctx.guild.id, None)
        self.current_song.pop(ctx.guild.id, None)
        self.loop_mode.pop(ctx.guild.id, None)
        
        if voice_client.is_playing() or voice_client.is_paused():
       
