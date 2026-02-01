"""
Keith Discord Bot - A GUI application for an AI-powered Discord bot using Claude.

Features:
- Modern GUI showing connection status and chat history
- Manual message sending to any channel
- "Keith <prompt>": Query Claude AI with conversation memory per channel
"""

import asyncio
import logging
import os
import queue
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import anthropic
import customtkinter as ctk
import discord
from dotenv import load_dotenv

# =============================================================================
# Configuration
# =============================================================================

load_dotenv()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("KeithBot")


class Config:
    """Bot configuration loaded from environment variables."""
    
    BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    RELEVANCE_MODEL: str = os.getenv("RELEVANCE_MODEL", "claude-3-5-haiku-20241022")
    
    # System prompt for Keith's personality
    SYSTEM_PROMPT: str = os.getenv(
        "KEITH_SYSTEM_PROMPT",
        "You are Keith, a helpful and friendly AI assistant in a Discord server. "
        "Be conversational, helpful, and concise in your responses. "
        "When recent channel messages are provided for context, you can reference them "
        "to understand what users are discussing, but focus on answering the question asked of you."
    )
    
    # Conversation settings
    MAX_CONVERSATION_HISTORY: int = int(os.getenv("MAX_CONVERSATION_HISTORY", "20"))
    RECENT_CHANNEL_MESSAGES: int = int(os.getenv("RECENT_CHANNEL_MESSAGES", "7"))
    DISCORD_MAX_LENGTH: int = 2000
    MAX_TOKENS: int = 4096
    
    # Voice channel to gather everyone into
    GATHER_VOICE_CHANNEL_ID: int = int(os.getenv("GATHER_VOICE_CHANNEL_ID", "1084054075613659206"))
    
    # FFmpeg path (if not in system PATH)
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "")
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("DISCORD_BOT_TOKEN is not set")
        if not cls.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is not set")
        return errors


# =============================================================================
# Claude Handler
# =============================================================================

class ClaudeHandler:
    """Handles all Claude API interactions with conversation memory."""
    
    def __init__(self, api_key: str, model: str, system_prompt: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.relevance_model = Config.RELEVANCE_MODEL
        self.system_prompt = system_prompt
        self.conversations: dict[int, list[dict]] = defaultdict(list)
    
    def clear_history(self, channel_id: int) -> None:
        """Clear conversation history for a channel."""
        self.conversations[channel_id] = []
    
    def clear_all_history(self) -> None:
        """Clear all conversation history."""
        self.conversations.clear()
    
    def _trim_history(self, channel_id: int) -> None:
        """Trim conversation history to max length."""
        history = self.conversations[channel_id]
        if len(history) > Config.MAX_CONVERSATION_HISTORY * 2:
            self.conversations[channel_id] = history[-(Config.MAX_CONVERSATION_HISTORY * 2):]
    
    def check_relevance(
        self, 
        message_content: str, 
        author_name: str,
        recent_context: list[dict] | None = None
    ) -> tuple[bool, str | None]:
        """
        Check if a message mentioning Keith is relevant for Keith to respond to.
        Uses a fast model (Haiku) to minimize latency and cost.
        Returns (should_respond, error).
        """
        # Build context for the relevance check
        context_text = ""
        if recent_context:
            context_text = "Recent messages:\n" + "\n".join(
                f"  {msg['author']}: {msg['content']}" 
                for msg in recent_context[-5:]  # Only last 5 for relevance check
            ) + "\n\n"
        
        prompt = f"""{context_text}New message from {author_name}: "{message_content}"

Keith is an AI assistant bot in this Discord server. Should Keith respond to this message?

Respond YES if:
- The message directly addresses Keith (e.g., "Keith how are you", "hey Keith", "yo Keith")
- Someone is asking Keith a question or starting a conversation with him
- Keith is being greeted, called, or summoned

Respond NO if:
- Someone is explaining, describing, or discussing what Keith does or how he works (e.g., "the keith bot detects...", "keith responds when...", "I programmed keith to...")
- People are talking ABOUT Keith in third person (e.g., "Keith is helpful", "I asked Keith earlier", "thats just how keith is")
- Keith is mentioned as part of an explanation or description to someone else
- The message is directed at another person, not Keith
- Someone is narrating or describing Keith's behavior/features

The key question: Is the person trying to START or CONTINUE a conversation WITH Keith, or are they talking ABOUT Keith to someone else?

Reply with only YES or NO."""

        try:
            response = self.client.messages.create(
                model=self.relevance_model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}]
            )
            
            if response.content and len(response.content) > 0:
                answer = response.content[0].text.strip().upper()
                return answer.startswith("YES"), None
            return False, "Empty response"
            
        except Exception as e:
            return False, str(e)
    
    def process_prompt(
        self, 
        channel_id: int, 
        user_name: str, 
        prompt: str,
        recent_context: list[dict] | None = None
    ) -> tuple[str | None, str | None]:
        """Process a user prompt and return Claude's response (synchronous)."""
        
        # Build the user message with optional channel context
        if recent_context:
            context_text = "\n".join(
                f"  [{msg['author']}]: {msg['content']}" 
                for msg in recent_context
            )
            full_content = (
                f"[Recent channel messages for context]\n{context_text}\n\n"
                f"[{user_name} asking you]: {prompt}"
            )
        else:
            full_content = f"[{user_name}]: {prompt}"
        
        self.conversations[channel_id].append({
            "role": "user",
            "content": full_content
        })
        
        self._trim_history(channel_id)
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=Config.MAX_TOKENS,
                system=self.system_prompt,
                messages=self.conversations[channel_id]
            )
            
            if response.content and len(response.content) > 0:
                response_text = response.content[0].text
                self.conversations[channel_id].append({
                    "role": "assistant",
                    "content": response_text
                })
                return response_text, None
            else:
                self.conversations[channel_id].pop()
                return None, "Empty response from Claude"
                
        except anthropic.RateLimitError:
            self.conversations[channel_id].pop()
            return None, "Rate limit exceeded"
        except anthropic.AuthenticationError:
            self.conversations[channel_id].pop()
            return None, "Authentication error"
        except Exception as e:
            self.conversations[channel_id].pop()
            return None, str(e)


# =============================================================================
# Discord Bot
# =============================================================================

class KeithBot(discord.Client):
    """The Discord bot client."""
    
    def __init__(self, gui: 'KeithGUI'):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True  # Required to see who's in voice channels
        super().__init__(intents=intents)
        
        self.gui = gui
        self.claude = ClaudeHandler(
            Config.ANTHROPIC_API_KEY,
            Config.CLAUDE_MODEL,
            Config.SYSTEM_PROMPT
        )
        self._message_queue: queue.Queue = queue.Queue()
        self._action_queue: queue.Queue = queue.Queue()  # For actions like voice moves
        self._ready = False
        self.smart_detection = False  # Toggle for AI-based relevance detection
    
    async def setup_hook(self) -> None:
        """Start background tasks."""
        self.loop.create_task(self._process_outgoing_queue())
        self.loop.create_task(self._process_action_queue())
    
    async def on_ready(self) -> None:
        """Called when connected to Discord."""
        self._ready = True
        self.gui.set_status("connected", f"Connected as {self.user.name}")
        self.gui.populate_channels(self.get_all_channels())
        self.gui.log_system(f"Logged in as {self.user.name}#{self.user.discriminator}")
        logger.info(f"Logged in as {self.user}")
    
    async def on_disconnect(self) -> None:
        """Called when disconnected."""
        self._ready = False
        self.gui.set_status("disconnected", "Disconnected")
    
    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        if message.author == self.user:
            return
        
        content_lower = message.content.lower().strip()
        
        # Check for clear history command
        if content_lower in ["keith clear", "keith reset", "keith forget"]:
            self.claude.clear_history(message.channel.id)
            await message.channel.send("Conversation history cleared! Starting fresh.")
            self.gui.log_system(f"[#{message.channel.name}] History cleared by {message.author.display_name}")
            self.gui.clear_chat_log()
            return
        
        # Check for help command
        if content_lower.startswith("khelp"):
            await self._handle_help(message)
            return
        
        # Check for purge command
        if content_lower.startswith("kpurge"):
            await self._handle_purge(message)
            return
        
        # Check for ping command
        if content_lower.startswith("ping <@"):
            await self._handle_spam_ping(message)
            return
        
        # Smart detection mode: check if "keith" appears anywhere and is relevant
        if self.smart_detection:
            if "keith" in content_lower:
                await self._handle_keith_smart(message)
        else:
            # Classic mode: only respond if message starts with "keith"
            if content_lower.startswith("keith"):
                await self._handle_keith(message)
    
    async def _handle_keith_smart(self, message: discord.Message) -> None:
        """Handle messages mentioning Keith with AI relevance check."""
        channel_name = getattr(message.channel, 'name', 'DM')
        
        # Fetch recent context for relevance check
        recent_context = await self._get_recent_messages(message)
        
        # Run relevance check in executor to not block
        loop = asyncio.get_event_loop()
        should_respond, error = await loop.run_in_executor(
            None,
            self.claude.check_relevance,
            message.content,
            message.author.display_name,
            recent_context
        )
        
        if error:
            self.gui.log_console(f"[#{channel_name}] Relevance check error: {error}", "error")
            return
        
        if not should_respond:
            self.gui.log_console(f"[#{channel_name}] Skipped (not relevant): {message.content[:50]}...", "info")
            return
        
        # It's relevant - proceed with response using full message as prompt
        self.gui.log_console(f"[#{channel_name}] Detected relevant mention", "success")
        
        # Log recent context to memory panel first (if any)
        if recent_context:
            self.gui.log_context(channel_name, recent_context)
        
        # Log the user's message
        self.gui.log_chat(f"[#{channel_name}] {message.author.display_name}: {message.content}", "user")
        
        async with message.channel.typing():
            response, error = await loop.run_in_executor(
                None,
                self.claude.process_prompt,
                message.channel.id,
                message.author.display_name,
                message.content,  # Use full message as prompt
                recent_context
            )
        
        if error:
            await message.channel.send(f"Sorry, an error occurred: {error}")
            self.gui.log_chat(f"[#{channel_name}] Error: {error}", "error")
        elif response:
            await self._send_long_message(message.channel, response)
            self.gui.log_chat(f"[#{channel_name}] Keith: {response}", "keith")
        else:
            await message.channel.send("I received an empty response.")
    
    async def _handle_keith(self, message: discord.Message) -> None:
        """Handle the Keith AI command (classic mode - starts with 'Keith')."""
        prompt = message.content[5:].strip()
        if not prompt:
            return
        
        channel_name = getattr(message.channel, 'name', 'DM')
        
        # Fetch recent context
        recent_context = await self._get_recent_messages(message)
        
        # Log recent context to memory panel first (if any)
        if recent_context:
            self.gui.log_context(channel_name, recent_context)
        
        # Log the user's actual question
        self.gui.log_chat(f"[#{channel_name}] {message.author.display_name}: {prompt}", "user")
        
        async with message.channel.typing():
            # Run Claude in executor to not block
            loop = asyncio.get_event_loop()
            response, error = await loop.run_in_executor(
                None,
                self.claude.process_prompt,
                message.channel.id,
                message.author.display_name,
                prompt,
                recent_context
            )
        
        if error:
            await message.channel.send(f"Sorry, an error occurred: {error}")
            self.gui.log_chat(f"[#{channel_name}] Error: {error}", "error")
        elif response:
            await self._send_long_message(message.channel, response)
            self.gui.log_chat(f"[#{channel_name}] Keith: {response}", "keith")
        else:
            await message.channel.send("I received an empty response.")
    
    async def _handle_help(self, message: discord.Message) -> None:
        """Handle the help command to list available commands."""
        help_text = """**Keith Bot Commands**

**Chat with Keith:**
• `Keith <message>` - Talk to Keith (or just mention him with Smart Detection on)
• `Keith clear` / `Keith reset` / `Keith forget` - Clear conversation history

**Utility Commands:**
• `khelp` - Show this help message
• `kpurge <number>` - Delete the last N messages (max 100)
• `ping @user` - Spam ping a user (count set in bot UI)
"""
        await message.channel.send(help_text)
        self.gui.log_console(f"[#{getattr(message.channel, 'name', 'DM')}] Help requested by {message.author.display_name}", "info")
    
    async def _handle_purge(self, message: discord.Message) -> None:
        """Handle the purge command to delete messages."""
        channel_name = getattr(message.channel, 'name', 'DM')
        
        # Parse the number from the command
        parts = message.content.split()
        if len(parts) < 2:
            await message.channel.send("Usage: `kpurge <number>` (e.g., `kpurge 10`)")
            return
        
        try:
            count = int(parts[1])
        except ValueError:
            await message.channel.send("Please provide a valid number. Usage: `kpurge <number>`")
            return
        
        # Limit the purge count for safety
        if count < 1:
            await message.channel.send("Please provide a number greater than 0.")
            return
        if count > 100:
            await message.channel.send("For safety, you can only purge up to 100 messages at a time.")
            count = 100
        
        # Check if the bot has permission to manage messages
        if not message.channel.permissions_for(message.guild.me).manage_messages:
            await message.channel.send("I don't have permission to delete messages. I need the 'Manage Messages' permission.")
            self.gui.log_console(f"[#{channel_name}] Purge failed - missing permissions", "error")
            return
        
        try:
            # Delete the command message first, then purge
            # purge() will delete `count` messages (not including the command since we delete it separately)
            await message.delete()
            deleted = await message.channel.purge(limit=count)
            
            # Send confirmation (will auto-delete after 3 seconds)
            confirm_msg = await message.channel.send(f"Purged {len(deleted)} messages.")
            await asyncio.sleep(3)
            await confirm_msg.delete()
            
            self.gui.log_console(f"[#{channel_name}] Purged {len(deleted)} messages (requested by {message.author.display_name})", "warning")
            
        except discord.Forbidden:
            await message.channel.send("I don't have permission to delete messages.")
            self.gui.log_console(f"[#{channel_name}] Purge failed - forbidden", "error")
        except discord.HTTPException as e:
            await message.channel.send(f"Failed to purge messages: {e}")
            self.gui.log_console(f"[#{channel_name}] Purge failed - {e}", "error")
    
    async def _handle_spam_ping(self, message: discord.Message) -> None:
        """Handle the spam ping command."""
        channel_name = getattr(message.channel, 'name', 'DM')
        
        # Extract the user mention from the message
        # Format: "ping <@userid>" or "ping <@!userid>"
        import re
        match = re.search(r'<@!?(\d+)>', message.content)
        if not match:
            await message.channel.send("Usage: `ping <@user>`")
            return
        
        user_mention = match.group(0)  # The full mention like <@123456>
        
        # Get ping count from GUI
        ping_count = self.gui.get_spam_ping_count()
        
        # Delete the command message
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        
        self.gui.log_console(f"[#{channel_name}] Spam pinging {user_mention} {ping_count} times (requested by {message.author.display_name})", "warning")
        
        # Spam ping
        for i in range(ping_count):
            try:
                ping_msg = await message.channel.send(user_mention)
                await asyncio.sleep(0.3)  # Brief delay
                await ping_msg.delete()
                await asyncio.sleep(0.2)  # Brief delay between pings
            except discord.Forbidden:
                self.gui.log_console(f"[#{channel_name}] Spam ping failed - no permission", "error")
                break
            except discord.HTTPException as e:
                self.gui.log_console(f"[#{channel_name}] Spam ping error - {e}", "error")
                break
        
        self.gui.log_console(f"[#{channel_name}] Spam ping complete", "success")
    
    async def _get_recent_messages(self, trigger_message: discord.Message) -> list[dict] | None:
        """Fetch recent messages from the channel for context."""
        if Config.RECENT_CHANNEL_MESSAGES <= 0:
            return None
        
        try:
            recent = []
            async for msg in trigger_message.channel.history(
                limit=Config.RECENT_CHANNEL_MESSAGES + 1,
                before=trigger_message
            ):
                if msg.author == self.user or not msg.content.strip():
                    continue
                if msg.content.lower().strip().startswith("keith"):
                    continue
                recent.append({
                    "author": msg.author.display_name,
                    "content": msg.content[:500]
                })
            recent.reverse()
            return recent if recent else None
        except Exception:
            return None
    
    async def _send_long_message(self, channel, text: str) -> None:
        """Send a message, splitting if necessary."""
        if len(text) <= Config.DISCORD_MAX_LENGTH:
            await channel.send(text)
            return
        
        parts = []
        current = ""
        for paragraph in text.split("\n"):
            if len(current) + len(paragraph) + 1 <= Config.DISCORD_MAX_LENGTH:
                current += paragraph + "\n"
            else:
                if current:
                    parts.append(current.strip())
                if len(paragraph) > Config.DISCORD_MAX_LENGTH:
                    for i in range(0, len(paragraph), Config.DISCORD_MAX_LENGTH - 10):
                        parts.append(paragraph[i:i + Config.DISCORD_MAX_LENGTH - 10])
                    current = ""
                else:
                    current = paragraph + "\n"
        if current:
            parts.append(current.strip())
        
        for part in parts:
            if part:
                await channel.send(part)
    
    def get_all_channels(self) -> list[tuple[int, str, str]]:
        """Get all text channels the bot can see."""
        channels = []
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    channels.append((channel.id, channel.name, guild.name))
        return channels
    
    def queue_message(self, channel_id: int, text: str) -> None:
        """Queue a message to be sent."""
        self._message_queue.put((channel_id, text))
    
    async def _process_outgoing_queue(self) -> None:
        """Process outgoing message queue."""
        while True:
            try:
                channel_id, text = self._message_queue.get_nowait()
                channel = self.get_channel(channel_id)
                if channel:
                    await channel.send(text)
                    channel_name = getattr(channel, 'name', 'Unknown')
                    self.gui.log_chat(f"[#{channel_name}] (Manual) Keith: {text}", "manual")
                self._message_queue.task_done()
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error sending queued message: {e}")
    
    async def _process_action_queue(self) -> None:
        """Process action queue (for voice moves, etc.)."""
        while True:
            try:
                action, args = self._action_queue.get_nowait()
                if action == "tomato_town":
                    await self._tomato_town()
                self._action_queue.task_done()
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error processing action: {e}")
                self.gui.log_console(f"Action error: {e}", "error")
    
    async def _tomato_town(self) -> None:
        """
        The Tomato Town sequence:
        1. Move all users to the target voice channel
        2. Join the voice channel
        3. Play tomato.mp3
        4. When audio ends, kick everyone and leave
        """
        target_channel = self.get_channel(Config.GATHER_VOICE_CHANNEL_ID)
        
        if not target_channel:
            self.gui.log_console(f"Error: Target voice channel {Config.GATHER_VOICE_CHANNEL_ID} not found", "error")
            return
        
        if not isinstance(target_channel, discord.VoiceChannel):
            self.gui.log_console(f"Error: Channel {Config.GATHER_VOICE_CHANNEL_ID} is not a voice channel", "error")
            return
        
        # Step 1: Gather everyone to Tomato Town
        self.gui.log_console(f"Gathering everyone to #{target_channel.name}...", "warning")
        
        moved_count = 0
        members_to_kick = []  # Track members to kick later
        
        for guild in self.guilds:
            for voice_channel in guild.voice_channels:
                if voice_channel.id == Config.GATHER_VOICE_CHANNEL_ID:
                    # Add existing members in target channel to kick list
                    members_to_kick.extend(voice_channel.members)
                    continue
                
                for member in voice_channel.members:
                    try:
                        await member.move_to(target_channel)
                        self.gui.log_console(f"Moved {member.display_name} to #{target_channel.name}", "info")
                        members_to_kick.append(member)
                        moved_count += 1
                    except discord.Forbidden:
                        self.gui.log_console(f"No permission to move {member.display_name}", "error")
                    except discord.HTTPException as e:
                        self.gui.log_console(f"Failed to move {member.display_name}: {e}", "error")
        
        self.gui.log_console(f"Gathered {moved_count} users to Tomato Town", "success")
        
        # Step 2: Join the voice channel
        try:
            voice_client = await target_channel.connect()
            self.gui.log_console(f"Keith joined #{target_channel.name}", "success")
        except discord.ClientException:
            # Already connected, get existing voice client
            voice_client = target_channel.guild.voice_client
            if voice_client and voice_client.channel != target_channel:
                await voice_client.move_to(target_channel)
            self.gui.log_console(f"Keith moved to #{target_channel.name}", "info")
        except Exception as e:
            self.gui.log_console(f"Failed to join voice: {e}", "error")
            return
        
        # Step 3: Play tomato.mp3
        audio_path = Path(__file__).parent / "audio" / "tomato.mp3"
        
        if not audio_path.exists():
            self.gui.log_console(f"Error: Audio file not found at {audio_path}", "error")
            await voice_client.disconnect()
            return
        
        self.gui.log_console("Playing tomato.mp3...", "warning")
        
        # Create an event to signal when audio is done
        audio_done = asyncio.Event()
        
        def after_playback(error):
            if error:
                logger.error(f"Playback error: {error}")
            # Signal that audio is done
            asyncio.run_coroutine_threadsafe(self._signal_event(audio_done), self.loop)
        
        try:
            # Use custom FFmpeg path if configured
            ffmpeg_options = {}
            if Config.FFMPEG_PATH:
                ffmpeg_exe = os.path.join(Config.FFMPEG_PATH, "ffmpeg.exe")
                audio_source = discord.FFmpegPCMAudio(str(audio_path), executable=ffmpeg_exe)
            else:
                audio_source = discord.FFmpegPCMAudio(str(audio_path))
            voice_client.play(audio_source, after=after_playback)
            
            # Wait for audio to finish
            await audio_done.wait()
            self.gui.log_console("Audio playback complete", "success")
            
        except Exception as e:
            self.gui.log_console(f"Failed to play audio: {e}", "error")
            self.gui.log_console("Make sure FFmpeg is installed on your system!", "warning")
        
        # Step 4: Kick everyone from the voice channel
        self.gui.log_console("Kicking everyone from Tomato Town...", "warning")
        
        # Refresh the member list (some may have left)
        target_channel = self.get_channel(Config.GATHER_VOICE_CHANNEL_ID)
        kicked_count = 0
        
        if target_channel:
            for member in list(target_channel.members):
                if member == self.user:
                    continue  # Don't kick ourselves yet
                try:
                    await member.move_to(None)  # Disconnect them
                    self.gui.log_console(f"Kicked {member.display_name}", "info")
                    kicked_count += 1
                except discord.Forbidden:
                    self.gui.log_console(f"No permission to kick {member.display_name}", "error")
                except Exception as e:
                    self.gui.log_console(f"Failed to kick {member.display_name}: {e}", "error")
        
        # Step 5: Leave the voice channel
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
            self.gui.log_console("Keith left the voice channel", "info")
        
        self.gui.log_console(f"Tomato Town complete! Kicked {kicked_count} users", "success")
    
    async def _signal_event(self, event: asyncio.Event) -> None:
        """Helper to signal an event from a callback."""
        event.set()
    
    def queue_action(self, action: str, args: dict = None) -> None:
        """Queue an action to be performed."""
        self._action_queue.put((action, args or {}))


# =============================================================================
# GUI Application
# =============================================================================

class KeithGUI(ctk.CTk):
    """Main GUI application for Keith bot."""
    
    def __init__(self):
        super().__init__()
        
        # Window setup
        self.title("Keith Bot")
        self.geometry("900x700")
        self.minsize(700, 500)
        
        # Theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Bot reference (set later)
        self.bot: KeithBot | None = None
        self.bot_thread: threading.Thread | None = None
        self.channels: list[tuple[int, str, str]] = []
        
        # Build UI
        self._create_widgets()
        
        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _create_widgets(self) -> None:
        """Create all GUI widgets."""
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # === Status Bar (Top) ===
        self.status_frame = ctk.CTkFrame(self, height=50)
        self.status_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.status_frame.grid_columnconfigure(1, weight=1)
        
        self.status_indicator = ctk.CTkLabel(
            self.status_frame, 
            text="●", 
            font=("Arial", 20),
            text_color="gray"
        )
        self.status_indicator.grid(row=0, column=0, padx=(15, 5), pady=10)
        
        self.status_label = ctk.CTkLabel(
            self.status_frame, 
            text="Disconnected", 
            font=("Arial", 14)
        )
        self.status_label.grid(row=0, column=1, sticky="w", pady=10)
        
        self.connect_btn = ctk.CTkButton(
            self.status_frame, 
            text="Connect", 
            command=self._toggle_connection,
            width=100
        )
        self.connect_btn.grid(row=0, column=2, padx=(15, 10), pady=10)
        
        # Smart detection toggle
        self.smart_detection_var = ctk.BooleanVar(value=False)
        self.smart_detection_toggle = ctk.CTkSwitch(
            self.status_frame,
            text="Smart Detection",
            variable=self.smart_detection_var,
            command=self._toggle_smart_detection,
            onvalue=True,
            offvalue=False
        )
        self.smart_detection_toggle.grid(row=0, column=3, padx=(10, 15), pady=10)
        
        # === Main Content Area (Two Panels Side by Side) ===
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(1, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)
        
        # === Left Panel: Console Logs ===
        self.console_frame = ctk.CTkFrame(self.content_frame)
        self.console_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=0)
        self.console_frame.grid_columnconfigure(0, weight=1)
        self.console_frame.grid_rowconfigure(1, weight=1)
        
        # Console header with label and clear button
        self.console_header = ctk.CTkFrame(self.console_frame, fg_color="transparent")
        self.console_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.console_header.grid_columnconfigure(0, weight=1)
        
        self.console_label = ctk.CTkLabel(
            self.console_header, 
            text="Console Logs", 
            font=("Arial", 12, "bold"),
            anchor="w"
        )
        self.console_label.grid(row=0, column=0, sticky="w")
        
        self.clear_logs_btn = ctk.CTkButton(
            self.console_header,
            text="Clear Logs",
            command=self._clear_console_logs,
            width=80,
            height=24,
            font=("Arial", 11),
            fg_color="transparent",
            border_width=1
        )
        self.clear_logs_btn.grid(row=0, column=1, sticky="e")
        
        # Console log textbox
        self.console_log = ctk.CTkTextbox(
            self.console_frame, 
            font=("Consolas", 11),
            state="disabled",
            wrap="word"
        )
        self.console_log.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        
        # Console text tags
        self.console_log._textbox.tag_config("info", foreground="#8b949e")
        self.console_log._textbox.tag_config("success", foreground="#7ee787")
        self.console_log._textbox.tag_config("warning", foreground="#d29922")
        self.console_log._textbox.tag_config("error", foreground="#f85149")
        self.console_log._textbox.tag_config("timestamp", foreground="#6e7681")
        
        # === Right Panel: Memory (AI Conversations) ===
        self.memory_frame = ctk.CTkFrame(self.content_frame)
        self.memory_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=0)
        self.memory_frame.grid_columnconfigure(0, weight=1)
        self.memory_frame.grid_rowconfigure(1, weight=1)
        
        # Memory header with label and erase button
        self.memory_header = ctk.CTkFrame(self.memory_frame, fg_color="transparent")
        self.memory_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.memory_header.grid_columnconfigure(0, weight=1)
        
        self.memory_label = ctk.CTkLabel(
            self.memory_header, 
            text="Memory (AI Context)", 
            font=("Arial", 12, "bold"),
            anchor="w"
        )
        self.memory_label.grid(row=0, column=0, sticky="w")
        
        self.erase_memory_btn = ctk.CTkButton(
            self.memory_header,
            text="Erase Memory",
            command=self._erase_memory,
            width=100,
            height=24,
            font=("Arial", 11),
            fg_color="#7c3aed",
            hover_color="#6d28d9"
        )
        self.erase_memory_btn.grid(row=0, column=1, sticky="e")
        
        # Memory log textbox
        self.memory_log = ctk.CTkTextbox(
            self.memory_frame, 
            font=("Consolas", 11),
            state="disabled",
            wrap="word"
        )
        self.memory_log.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))
        
        # Memory text tags (for conversations)
        self.memory_log._textbox.tag_config("user", foreground="#58a6ff")          # Blue for user asking Keith
        self.memory_log._textbox.tag_config("keith", foreground="#7ee787")         # Green for Keith's response
        self.memory_log._textbox.tag_config("manual", foreground="#d29922")        # Yellow for manual messages
        self.memory_log._textbox.tag_config("channel", foreground="#a371f7")       # Purple for channel name
        self.memory_log._textbox.tag_config("divider", foreground="#484f58")       # Dim for dividers
        self.memory_log._textbox.tag_config("context_author", foreground="#8b949e")  # Gray for context authors
        self.memory_log._textbox.tag_config("context_msg", foreground="#6e7681")     # Dimmer gray for context text
        
        # === Tomato Town Section ===
        self.tomato_frame = ctk.CTkFrame(self)
        self.tomato_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        self.tomato_frame.grid_columnconfigure(3, weight=1)
        
        # Tomato Town button
        self.tomato_btn = ctk.CTkButton(
            self.tomato_frame,
            text="Tomato Town",
            command=self._tomato_town,
            width=120,
            height=36,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            font=("Arial", 13, "bold"),
            state="disabled"
        )
        self.tomato_btn.grid(row=0, column=0, padx=(15, 10), pady=12)
        
        # Toggle for sending message
        self.tomato_msg_var = ctk.BooleanVar(value=False)
        self.tomato_msg_toggle = ctk.CTkSwitch(
            self.tomato_frame,
            text="Send message",
            variable=self.tomato_msg_var,
            command=self._toggle_tomato_message,
            onvalue=True,
            offvalue=False
        )
        self.tomato_msg_toggle.grid(row=0, column=1, padx=(10, 10), pady=12)
        
        # Message entry (hidden by default)
        self.tomato_msg_entry = ctk.CTkEntry(
            self.tomato_frame,
            placeholder_text="Message to send...",
            width=300
        )
        self.tomato_msg_entry.insert(0, "Tomato Town Massacre")
        # Don't grid yet - will be shown when toggle is on
        
        # === Spam Ping Section ===
        self.spam_ping_frame = ctk.CTkFrame(self)
        self.spam_ping_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)
        
        self.spam_ping_label = ctk.CTkLabel(
            self.spam_ping_frame,
            text="Spam Ping:",
            font=("Arial", 12)
        )
        self.spam_ping_label.grid(row=0, column=0, padx=(15, 10), pady=12)
        
        self.spam_ping_info = ctk.CTkLabel(
            self.spam_ping_frame,
            text="Use 'ping @user' in Discord",
            font=("Arial", 11),
            text_color="#8b949e"
        )
        self.spam_ping_info.grid(row=0, column=1, padx=(0, 15), pady=12)
        
        self.spam_ping_count_label = ctk.CTkLabel(
            self.spam_ping_frame,
            text="Count:",
            font=("Arial", 12)
        )
        self.spam_ping_count_label.grid(row=0, column=2, padx=(15, 5), pady=12)
        
        self.spam_ping_count_entry = ctk.CTkEntry(
            self.spam_ping_frame,
            width=60,
            justify="center"
        )
        self.spam_ping_count_entry.insert(0, "5")
        self.spam_ping_count_entry.grid(row=0, column=3, padx=(0, 15), pady=12)
        
        # === Manual Message Section (Bottom) ===
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=(5, 10))
        self.input_frame.grid_columnconfigure(1, weight=1)
        
        # Channel selector
        self.channel_label = ctk.CTkLabel(self.input_frame, text="Channel:")
        self.channel_label.grid(row=0, column=0, padx=(15, 5), pady=10)
        
        self.channel_dropdown = ctk.CTkComboBox(
            self.input_frame, 
            values=["Not connected..."],
            width=250,
            state="disabled"
        )
        self.channel_dropdown.grid(row=0, column=1, sticky="w", padx=5, pady=10)
        
        # Message input
        self.message_label = ctk.CTkLabel(self.input_frame, text="Message:")
        self.message_label.grid(row=1, column=0, padx=(15, 5), pady=(0, 10))
        
        self.message_entry = ctk.CTkEntry(
            self.input_frame, 
            placeholder_text="Type a message to send as Keith...",
            state="disabled"
        )
        self.message_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 10))
        self.message_entry.bind("<Return>", lambda e: self._send_manual_message())
        
        self.send_btn = ctk.CTkButton(
            self.input_frame, 
            text="Send", 
            command=self._send_manual_message,
            width=80,
            state="disabled"
        )
        self.send_btn.grid(row=1, column=2, padx=(5, 15), pady=(0, 10))
    
    def set_status(self, status: str, text: str) -> None:
        """Update connection status display."""
        colors = {
            "connected": "#7ee787",
            "connecting": "#d29922",
            "disconnected": "#8b949e",
            "error": "#f85149"
        }
        self.status_indicator.configure(text_color=colors.get(status, "gray"))
        self.status_label.configure(text=text)
        
        if status == "connected":
            self.connect_btn.configure(text="Disconnect")
            self.message_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
            self.channel_dropdown.configure(state="readonly")
            self.tomato_btn.configure(state="normal")
        else:
            self.connect_btn.configure(text="Connect")
            self.message_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.channel_dropdown.configure(state="disabled")
            self.tomato_btn.configure(state="disabled")
    
    def populate_channels(self, channels: list[tuple[int, str, str]]) -> None:
        """Populate channel dropdown."""
        self.channels = channels
        if channels:
            display_names = [f"#{name} ({guild})" for _, name, guild in channels]
            self.channel_dropdown.configure(values=display_names)
            self.channel_dropdown.set(display_names[0])
        else:
            self.channel_dropdown.configure(values=["No channels available"])
    
    def get_spam_ping_count(self) -> int:
        """Get the spam ping count from the UI."""
        try:
            count = int(self.spam_ping_count_entry.get())
            return max(1, min(count, 50))  # Clamp between 1 and 50
        except ValueError:
            return 5  # Default
    
    def log_console(self, message: str, level: str = "info") -> None:
        """Add a message to the console log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console_log.configure(state="normal")
        self.console_log._textbox.insert("end", f"[{timestamp}] ", "timestamp")
        self.console_log._textbox.insert("end", f"{message}\n", level)
        self.console_log.configure(state="disabled")
        self.console_log.see("end")
    
    def log_system(self, message: str) -> None:
        """Add a system message to the console log."""
        self.log_console(message, "info")
    
    def log_chat(self, message: str, tag: str = "system") -> None:
        """Route chat messages to appropriate panel."""
        # Route to memory panel for actual conversations
        if tag in ["user", "keith", "manual"]:
            self.log_memory(message, tag)
        else:
            # Route errors and system messages to console
            level = "error" if tag == "error" else "info"
            self.log_console(message, level)
    
    def log_memory(self, message: str, tag: str = "user") -> None:
        """Add a conversation message to the memory panel."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.memory_log.configure(state="normal")
        
        # Parse channel from message if present
        if message.startswith("[#"):
            bracket_end = message.find("]")
            if bracket_end > 0:
                channel_part = message[1:bracket_end]  # e.g., "#general"
                rest = message[bracket_end + 1:].strip()
                self.memory_log._textbox.insert("end", f"[{timestamp}] ", "timestamp")
                self.memory_log._textbox.insert("end", f"[{channel_part}] ", "channel")
                self.memory_log._textbox.insert("end", f"{rest}\n", tag)
            else:
                self.memory_log._textbox.insert("end", f"[{timestamp}] ", "timestamp")
                self.memory_log._textbox.insert("end", f"{message}\n", tag)
        else:
            self.memory_log._textbox.insert("end", f"[{timestamp}] ", "timestamp")
            self.memory_log._textbox.insert("end", f"{message}\n", tag)
        
        self.memory_log.configure(state="disabled")
        self.memory_log.see("end")
    
    def log_context(self, channel_name: str, context_messages: list[dict]) -> None:
        """Log the recent channel context that Keith sees."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.memory_log.configure(state="normal")
        
        # Add a context header
        self.memory_log._textbox.insert("end", f"[{timestamp}] ", "timestamp")
        self.memory_log._textbox.insert("end", f"[#{channel_name}] ", "channel")
        self.memory_log._textbox.insert("end", "── Recent Context ──\n", "divider")
        
        # Log each context message
        for msg in context_messages:
            self.memory_log._textbox.insert("end", f"         ", "timestamp")  # Indent
            self.memory_log._textbox.insert("end", f"{msg['author']}: ", "context_author")
            self.memory_log._textbox.insert("end", f"{msg['content']}\n", "context_msg")
        
        self.memory_log._textbox.insert("end", "         ────────────────────\n", "divider")
        
        self.memory_log.configure(state="disabled")
        self.memory_log.see("end")
    
    def _clear_console_logs(self) -> None:
        """Clear only the console logs display."""
        self.console_log.configure(state="normal")
        self.console_log.delete("1.0", "end")
        self.console_log.configure(state="disabled")
        self.log_console("Console cleared", "info")
    
    def _erase_memory(self) -> None:
        """Clear the memory display and AI conversation history."""
        # Clear display
        self.memory_log.configure(state="normal")
        self.memory_log.delete("1.0", "end")
        self.memory_log.configure(state="disabled")
        
        # Clear AI memory
        if self.bot and hasattr(self.bot, 'claude'):
            self.bot.claude.clear_all_history()
            self.log_console("AI memory erased", "success")
        else:
            self.log_console("Memory display cleared", "info")
    
    def clear_chat_log(self) -> None:
        """Clear both console and memory (called by Keith clear command)."""
        self._clear_console_logs()
        self._erase_memory()
    
    def _toggle_tomato_message(self) -> None:
        """Show/hide the tomato message entry based on toggle state."""
        if self.tomato_msg_var.get():
            self.tomato_msg_entry.grid(row=0, column=3, sticky="ew", padx=(10, 15), pady=12)
        else:
            self.tomato_msg_entry.grid_remove()
    
    def _toggle_smart_detection(self) -> None:
        """Toggle smart detection mode on/off."""
        enabled = self.smart_detection_var.get()
        if self.bot:
            self.bot.smart_detection = enabled
        
        if enabled:
            self.log_console("Smart Detection ON: Keith will respond to relevant mentions", "success")
        else:
            self.log_console("Smart Detection OFF: Keith only responds to 'Keith <message>'", "info")
    
    def _toggle_connection(self) -> None:
        """Connect or disconnect the bot."""
        if self.bot and self.bot._ready:
            # Disconnect
            self.set_status("disconnected", "Disconnecting...")
            asyncio.run_coroutine_threadsafe(self.bot.close(), self.bot.loop)
        else:
            # Connect
            self._start_bot()
    
    def _start_bot(self) -> None:
        """Start the Discord bot in a separate thread."""
        errors = Config.validate()
        if errors:
            self.set_status("error", "Configuration error")
            for error in errors:
                self.log_chat(f"Config Error: {error}", "error")
            return
        
        self.set_status("connecting", "Connecting...")
        self.log_system("Starting bot...")
        
        self.bot = KeithBot(self)
        self.bot.smart_detection = self.smart_detection_var.get()  # Sync toggle state
        
        def run_bot():
            try:
                self.bot.run(Config.BOT_TOKEN)
            except discord.errors.LoginFailure:
                self.after(0, lambda: self.set_status("error", "Invalid token"))
                self.after(0, lambda: self.log_chat("Invalid Discord token", "error"))
            except Exception as e:
                self.after(0, lambda: self.set_status("error", "Connection failed"))
                self.after(0, lambda: self.log_chat(f"Error: {e}", "error"))
        
        self.bot_thread = threading.Thread(target=run_bot, daemon=True)
        self.bot_thread.start()
    
    def _send_manual_message(self) -> None:
        """Send a manual message to the selected channel."""
        if not self.bot or not self.bot._ready:
            return
        
        message = self.message_entry.get().strip()
        if not message:
            return
        
        # Get selected channel
        selection = self.channel_dropdown.get()
        channel_id = None
        for cid, name, guild in self.channels:
            if f"#{name} ({guild})" == selection:
                channel_id = cid
                break
        
        if channel_id:
            self.bot.queue_message(channel_id, message)
            self.message_entry.delete(0, "end")
    
    def _tomato_town(self) -> None:
        """Trigger the Tomato Town sequence."""
        if not self.bot or not self.bot._ready:
            return
        
        # Send message if toggle is enabled
        if self.tomato_msg_var.get():
            message = self.tomato_msg_entry.get().strip()
            if message:
                # Get selected channel
                selection = self.channel_dropdown.get()
                channel_id = None
                for cid, name, guild in self.channels:
                    if f"#{name} ({guild})" == selection:
                        channel_id = cid
                        break
                
                if channel_id:
                    self.bot.queue_message(channel_id, message)
                    self.log_console(f"Sent message: {message}", "info")
        
        self.log_console("Initiating Tomato Town...", "warning")
        self.bot.queue_action("tomato_town")
    
    def _on_close(self) -> None:
        """Handle window close."""
        if self.bot:
            try:
                asyncio.run_coroutine_threadsafe(self.bot.close(), self.bot.loop)
            except Exception:
                pass
        self.quit()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Main entry point."""
    app = KeithGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
