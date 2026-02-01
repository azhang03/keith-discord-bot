"""
Keith Discord Bot - An AI-powered Discord bot using Anthropic's Claude API.

Features:
- "Keith <prompt>": Query Claude AI with conversation memory per channel
- "HalcM": Manual control mode for bot owner (requires tkinter)
"""

import asyncio
import logging
import os
import queue
import threading
from collections import defaultdict

import anthropic
import discord
from dotenv import load_dotenv

# Optional tkinter import for HalcM feature
try:
    import tkinter as tk
    from tkinter import simpledialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

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
    ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID", "0"))
    
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
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present."""
        errors = []
        
        if not cls.BOT_TOKEN:
            errors.append("DISCORD_BOT_TOKEN is not set")
        if not cls.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is not set")
        if cls.ALLOWED_USER_ID == 0:
            logger.warning("ALLOWED_USER_ID is not set - HalcM feature will be disabled")
        
        if errors:
            logger.error("Configuration errors found:")
            for error in errors:
                logger.error(f"  - {error}")
            logger.error("Please check your .env file. See .env.example for reference.")
            return False
        
        return True


# =============================================================================
# Claude Assistant Handler
# =============================================================================

class ClaudeHandler:
    """Handles all Claude API interactions with conversation memory."""
    
    def __init__(self, api_key: str, model: str, system_prompt: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        # Store conversation history per channel: {channel_id: [messages]}
        self.conversations: dict[int, list[dict]] = defaultdict(list)
    
    def clear_history(self, channel_id: int) -> None:
        """Clear conversation history for a channel."""
        self.conversations[channel_id] = []
        logger.info(f"[Channel {channel_id}] Conversation history cleared")
    
    def _trim_history(self, channel_id: int) -> None:
        """Trim conversation history to max length."""
        history = self.conversations[channel_id]
        if len(history) > Config.MAX_CONVERSATION_HISTORY * 2:  # *2 for user+assistant pairs
            # Keep only the most recent messages
            self.conversations[channel_id] = history[-(Config.MAX_CONVERSATION_HISTORY * 2):]
    
    async def process_prompt(
        self, 
        channel_id: int, 
        user_name: str, 
        prompt: str,
        recent_context: list[dict] | None = None
    ) -> tuple[str | None, str | None]:
        """
        Process a user prompt and return Claude's response.
        
        Args:
            channel_id: The Discord channel ID
            user_name: Display name of the user asking
            prompt: The user's prompt (after "Keith")
            recent_context: Optional list of recent channel messages for context
        
        Returns:
            tuple: (response_text, error_message) - one will be None
        """
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
        
        # Add user message to history
        self.conversations[channel_id].append({
            "role": "user",
            "content": full_content
        })
        
        # Trim history if needed
        self._trim_history(channel_id)
        
        try:
            # Make API call (run in executor to not block)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self._call_claude,
                channel_id
            )
            
            if response:
                # Add assistant response to history
                self.conversations[channel_id].append({
                    "role": "assistant",
                    "content": response
                })
                logger.info(f"[Channel {channel_id}] Got response ({len(response)} chars)")
                return response, None
            else:
                # Remove the user message if we failed
                self.conversations[channel_id].pop()
                return None, "I received an empty response."
                
        except anthropic.RateLimitError:
            self.conversations[channel_id].pop()  # Remove failed user message
            logger.warning("Claude rate limit exceeded")
            return None, "Sorry, I'm getting too many requests. Please try again in a moment."
        except anthropic.AuthenticationError:
            self.conversations[channel_id].pop()
            logger.error("Claude authentication error")
            return None, "Sorry, there's an authentication issue. Please contact the bot owner."
        except anthropic.APIStatusError as e:
            self.conversations[channel_id].pop()
            logger.error(f"Claude API error: {e}")
            return None, f"Sorry, there was an API error: {e.message}"
        except Exception as e:
            self.conversations[channel_id].pop()
            logger.error(f"[Channel {channel_id}] Unexpected error: {e}")
            return None, "Sorry, an unexpected error occurred."
    
    def _call_claude(self, channel_id: int) -> str | None:
        """Make the synchronous Claude API call."""
        messages = self.conversations[channel_id]
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=Config.MAX_TOKENS,
            system=self.system_prompt,
            messages=messages
        )
        
        # Extract text from response
        if response.content and len(response.content) > 0:
            return response.content[0].text
        return None


# =============================================================================
# Manual Control Mode (HalcM)
# =============================================================================

class ManualModeController:
    """Handles the HalcM manual control feature."""
    
    def __init__(self):
        self.active = False
        self.channel_id: int | None = None
        self._lock = threading.Lock()
        self._message_queue: queue.Queue = queue.Queue()
    
    @property
    def is_active(self) -> bool:
        with self._lock:
            return self.active
    
    def is_active_in_channel(self, channel_id: int) -> bool:
        with self._lock:
            return self.active and self.channel_id == channel_id
    
    def activate(self, channel_id: int) -> bool:
        """Attempt to activate manual mode for a channel."""
        with self._lock:
            if self.active:
                return False
            self.active = True
            self.channel_id = channel_id
            return True
    
    def deactivate(self) -> None:
        """Deactivate manual mode."""
        with self._lock:
            self.active = False
            self.channel_id = None
    
    def queue_message(self, channel_id: int, text: str) -> None:
        """Add a message to the send queue."""
        self._message_queue.put((channel_id, text))
    
    def get_queued_message(self) -> tuple[int, str] | None:
        """Get a message from the queue (non-blocking)."""
        try:
            return self._message_queue.get_nowait()
        except queue.Empty:
            return None
    
    def mark_sent(self) -> None:
        """Mark a queued message as sent."""
        self._message_queue.task_done()
    
    def run_input_loop(self, channel_id: int) -> None:
        """Run the tkinter input dialog loop (called in a separate thread)."""
        if not TKINTER_AVAILABLE:
            return
        
        logger.info(f"[HalcM] Started input loop for channel {channel_id}")
        
        while self.is_active:
            user_input = self._show_dialog()
            
            if user_input is None:
                logger.info("[HalcM] Dialog cancelled")
                break
            
            if user_input.strip().lower() == "stop":
                logger.info("[HalcM] Stop command received")
                break
            
            if user_input.strip():
                self.queue_message(channel_id, user_input)
        
        self.deactivate()
        logger.info("[HalcM] Input loop ended")
    
    def _show_dialog(self) -> str | None:
        """Show the tkinter input dialog."""
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            user_input = simpledialog.askstring(
                "Manual Bot Input",
                "Enter message (or 'stop' to exit):",
                parent=root
            )
            root.destroy()
            return user_input
        except Exception as e:
            logger.error(f"[HalcM] Dialog error: {e}")
            return None


# =============================================================================
# Discord Bot
# =============================================================================

class KeithBot(discord.Client):
    """The main Discord bot client."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        self.claude = ClaudeHandler(
            Config.ANTHROPIC_API_KEY,
            Config.CLAUDE_MODEL,
            Config.SYSTEM_PROMPT
        )
        self.manual_mode = ManualModeController()
    
    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        self.loop.create_task(self._process_message_queue())
    
    async def on_ready(self) -> None:
        """Called when the bot has connected to Discord."""
        logger.info(f"Logged in as {self.user}")
        logger.info(f"Using Claude model: {Config.CLAUDE_MODEL}")
        logger.info(f'Ready! Listening for "Keith" commands.')
        
        if TKINTER_AVAILABLE and Config.ALLOWED_USER_ID != 0:
            logger.info(f'HalcM enabled for user ID: {Config.ALLOWED_USER_ID}')
        else:
            if not TKINTER_AVAILABLE:
                logger.warning('HalcM disabled (tkinter not available)')
            elif Config.ALLOWED_USER_ID == 0:
                logger.warning('HalcM disabled (ALLOWED_USER_ID not set)')
    
    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        # Ignore own messages
        if message.author == self.user:
            return
        
        content_lower = message.content.lower().strip()
        
        # Check for HalcM command
        if content_lower == "halcm":
            await self._handle_halcm(message)
            return
        
        # Check for clear history command
        if content_lower in ["keith clear", "keith reset", "keith forget"]:
            self.claude.clear_history(message.channel.id)
            await message.channel.send("Conversation history cleared! Starting fresh.")
            return
        
        # Ignore commands while manual mode is active in this channel
        if self.manual_mode.is_active_in_channel(message.channel.id):
            return
        
        # Check for Keith command
        if content_lower.startswith("keith"):
            await self._handle_keith(message)
    
    async def _handle_halcm(self, message: discord.Message) -> None:
        """Handle the HalcM manual control command."""
        # Check permissions
        if message.author.id != Config.ALLOWED_USER_ID:
            return
        
        if not TKINTER_AVAILABLE:
            try:
                await message.channel.send(
                    "The local input feature requires `tkinter` which is not installed.",
                    delete_after=10
                )
                await message.delete()
            except Exception:
                pass
            return
        
        # Try to activate
        if not self.manual_mode.activate(message.channel.id):
            try:
                await message.channel.send(
                    "Manual mode is already active. Type `stop` in the popup to exit.",
                    delete_after=15
                )
                await message.delete()
            except Exception:
                pass
            return
        
        logger.info(f"[HalcM] Activated for channel {message.channel.id} by {message.author}")
        
        # Delete trigger message
        try:
            await message.delete()
        except Exception:
            pass
        
        # Start input loop in separate thread
        thread = threading.Thread(
            target=self.manual_mode.run_input_loop,
            args=(message.channel.id,),
            daemon=True
        )
        thread.start()
    
    async def _handle_keith(self, message: discord.Message) -> None:
        """Handle the Keith AI command."""
        # Extract prompt
        prompt = message.content[5:].strip()  # Remove "Keith" prefix
        if not prompt:
            return
        
        logger.info(f"[Channel {message.channel.id}] Prompt from {message.author}: '{prompt[:50]}...'")
        
        # Fetch recent channel messages for context
        recent_context = await self._get_recent_messages(message)
        
        # Process with typing indicator
        async with message.channel.typing():
            response, error = await self.claude.process_prompt(
                message.channel.id,
                message.author.display_name,
                prompt,
                recent_context
            )
        
        # Send response or error
        if error:
            await message.channel.send(error)
        elif response:
            await self._send_long_message(message.channel, response)
        else:
            await message.channel.send("I received an empty response.")
    
    async def _get_recent_messages(self, trigger_message: discord.Message) -> list[dict] | None:
        """
        Fetch recent messages from the channel before the trigger message.
        
        This gives Keith context about what people were discussing,
        so users can ask things like "Keith, what do you think about what User B said?"
        """
        if Config.RECENT_CHANNEL_MESSAGES <= 0:
            return None
        
        try:
            recent = []
            async for msg in trigger_message.channel.history(
                limit=Config.RECENT_CHANNEL_MESSAGES + 1,  # +1 because it includes the trigger
                before=trigger_message
            ):
                # Skip bot's own messages and empty messages
                if msg.author == self.user or not msg.content.strip():
                    continue
                
                # Skip other Keith commands (don't include them as context)
                if msg.content.lower().strip().startswith("keith"):
                    continue
                
                recent.append({
                    "author": msg.author.display_name,
                    "content": msg.content[:500]  # Truncate very long messages
                })
            
            # Reverse to get chronological order (oldest first)
            recent.reverse()
            
            if recent:
                logger.debug(f"[Channel {trigger_message.channel.id}] Got {len(recent)} recent messages for context")
                return recent
            return None
            
        except discord.Forbidden:
            logger.warning(f"[Channel {trigger_message.channel.id}] No permission to read message history")
            return None
        except Exception as e:
            logger.warning(f"[Channel {trigger_message.channel.id}] Failed to fetch recent messages: {e}")
            return None
    
    async def _send_long_message(self, channel: discord.TextChannel, text: str) -> None:
        """Send a message, splitting if necessary for Discord's length limit."""
        if len(text) <= Config.DISCORD_MAX_LENGTH:
            await channel.send(text)
            return
        
        # Split by paragraphs
        parts = []
        current = ""
        
        for paragraph in text.split("\n"):
            if len(current) + len(paragraph) + 1 <= Config.DISCORD_MAX_LENGTH:
                current += paragraph + "\n"
            else:
                if current:
                    parts.append(current.strip())
                # Handle very long paragraphs
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
    
    async def _process_message_queue(self) -> None:
        """Background task to process the manual mode message queue."""
        while True:
            msg = self.manual_mode.get_queued_message()
            if msg:
                channel_id, text = msg
                channel = self.get_channel(channel_id)
                if channel:
                    try:
                        await channel.send(text)
                        logger.info(f"[HalcM] Sent message to channel {channel_id}")
                    except discord.Forbidden:
                        logger.error(f"[HalcM] No permission to send to channel {channel_id}")
                    except Exception as e:
                        logger.error(f"[HalcM] Send error: {e}")
                self.manual_mode.mark_sent()
            else:
                await asyncio.sleep(0.2)


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Main entry point."""
    # Validate configuration
    if not Config.validate():
        return
    
    # Create and run bot
    bot = KeithBot()
    
    try:
        bot.run(Config.BOT_TOKEN)
    except discord.errors.LoginFailure:
        logger.error("Invalid Discord token. Check DISCORD_BOT_TOKEN in your .env file.")
    except discord.errors.PrivilegedIntentsRequired:
        logger.error("MESSAGE CONTENT INTENT not enabled in Discord Developer Portal.")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        logger.info("Bot stopped.")
        bot.manual_mode.deactivate()


if __name__ == "__main__":
    main()
