"""
Keith Discord Bot - An AI-powered Discord bot using OpenAI Assistants API.

Features:
- "Keith <prompt>": Query the OpenAI Assistant
- "HalcM": Manual control mode for bot owner (requires tkinter)
"""

import asyncio
import logging
import os
import queue
import threading
import time
from functools import partial

import discord
import openai
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
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ASSISTANT_ID: str = os.getenv("OPENAI_ASSISTANT_ID", "")
    ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID", "0"))
    
    # Runtime settings
    MAX_POLL_TIME: int = 300  # seconds
    POLL_INTERVAL: float = 1.5  # seconds
    DISCORD_MAX_LENGTH: int = 2000
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present."""
        errors = []
        
        if not cls.BOT_TOKEN:
            errors.append("DISCORD_BOT_TOKEN is not set")
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is not set")
        if not cls.ASSISTANT_ID:
            errors.append("OPENAI_ASSISTANT_ID is not set")
        if cls.ALLOWED_USER_ID == 0:
            errors.append("ALLOWED_USER_ID is not set (required for HalcM feature)")
        
        if errors:
            logger.error("Configuration errors found:")
            for error in errors:
                logger.error(f"  - {error}")
            logger.error("Please check your .env file. See .env.example for reference.")
            return False
        
        return True


# =============================================================================
# OpenAI Assistant Handler
# =============================================================================

class AssistantHandler:
    """Handles all OpenAI Assistant API interactions."""
    
    def __init__(self, api_key: str, assistant_id: str):
        self.client = openai.OpenAI(api_key=api_key)
        self.assistant_id = assistant_id
        self.channel_threads: dict[int, str] = {}
    
    async def verify_assistant(self) -> bool:
        """Verify the assistant exists and is accessible."""
        try:
            loop = asyncio.get_event_loop()
            assistant = await loop.run_in_executor(
                None, 
                self.client.beta.assistants.retrieve, 
                self.assistant_id
            )
            logger.info(f"Connected to Assistant: {assistant.name} ({self.assistant_id})")
            return True
        except openai.NotFoundError:
            logger.error(f"Assistant '{self.assistant_id}' not found. Check the ID.")
        except openai.AuthenticationError:
            logger.error("OpenAI authentication failed. Check your API key.")
        except Exception as e:
            logger.error(f"Failed to retrieve assistant: {e}")
        return False
    
    def _get_or_create_thread(self, channel_id: int) -> str | None:
        """Get existing thread or create a new one for a channel."""
        if channel_id in self.channel_threads:
            return self.channel_threads[channel_id]
        
        try:
            thread = self.client.beta.threads.create()
            self.channel_threads[channel_id] = thread.id
            logger.info(f"[Channel {channel_id}] Created thread: {thread.id}")
            return thread.id
        except Exception as e:
            logger.error(f"[Channel {channel_id}] Failed to create thread: {e}")
            return None
    
    def _clear_thread(self, channel_id: int) -> None:
        """Remove a thread from the cache."""
        self.channel_threads.pop(channel_id, None)
    
    async def process_prompt(self, channel_id: int, prompt: str) -> tuple[str | None, str | None]:
        """
        Process a user prompt and return the assistant's response.
        
        Returns:
            tuple: (response_text, error_message) - one will be None
        """
        loop = asyncio.get_event_loop()
        
        # Get or create thread
        thread_id = await loop.run_in_executor(
            None, 
            self._get_or_create_thread, 
            channel_id
        )
        if not thread_id:
            return None, "Sorry, I couldn't start a new conversation thread."
        
        logger.info(f"[Channel {channel_id}] Using thread: {thread_id}")
        
        # Add message to thread
        try:
            await loop.run_in_executor(
                None,
                partial(
                    self.client.beta.threads.messages.create,
                    thread_id=thread_id,
                    role="user",
                    content=prompt
                )
            )
        except Exception as e:
            if "no thread found" in str(e).lower() or "not_found" in str(e).lower():
                self._clear_thread(channel_id)
                return None, "Our conversation history was lost. Please try again to start a new one."
            logger.error(f"[Channel {channel_id}] Failed to add message: {e}")
            return None, "Sorry, I couldn't process your message."
        
        # Create and poll the run
        try:
            run = await loop.run_in_executor(
                None,
                partial(
                    self.client.beta.threads.runs.create,
                    thread_id=thread_id,
                    assistant_id=self.assistant_id
                )
            )
            logger.info(f"[Channel {channel_id}] Created run: {run.id}")
            
            # Poll for completion
            response = await self._poll_run(channel_id, thread_id, run.id)
            return response
            
        except openai.RateLimitError:
            logger.warning("OpenAI rate limit exceeded")
            return None, "Sorry, I'm getting too many requests. Please try again in a moment."
        except openai.AuthenticationError:
            logger.error("OpenAI authentication error during run")
            return None, "Sorry, there's an authentication issue. Please contact the bot owner."
        except openai.NotFoundError:
            logger.error(f"[Channel {channel_id}] Resource not found during run")
            self._clear_thread(channel_id)
            return None, "Sorry, the conversation context was lost. Please try again."
        except Exception as e:
            logger.error(f"[Channel {channel_id}] Unexpected error: {e}")
            return None, "Sorry, an unexpected error occurred."
    
    async def _poll_run(self, channel_id: int, thread_id: str, run_id: str) -> tuple[str | None, str | None]:
        """Poll for run completion and retrieve the response."""
        loop = asyncio.get_event_loop()
        start_time = time.time()
        
        while True:
            # Check timeout
            if time.time() - start_time > Config.MAX_POLL_TIME:
                logger.warning(f"[Channel {channel_id}] Run timed out")
                try:
                    await loop.run_in_executor(
                        None,
                        partial(
                            self.client.beta.threads.runs.cancel,
                            thread_id=thread_id,
                            run_id=run_id
                        )
                    )
                except Exception:
                    pass
                return None, "Sorry, the request took too long to process."
            
            await asyncio.sleep(Config.POLL_INTERVAL)
            
            # Check run status
            try:
                run = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.beta.threads.runs.retrieve,
                        thread_id=thread_id,
                        run_id=run_id
                    )
                )
            except openai.NotFoundError:
                logger.error(f"[Channel {channel_id}] Run/thread not found during polling")
                self._clear_thread(channel_id)
                return None, "There was an issue tracking the AI's progress."
            except Exception as e:
                logger.warning(f"[Channel {channel_id}] Poll error: {e}")
                await asyncio.sleep(3)
                continue
            
            logger.debug(f"[Channel {channel_id}] Run status: {run.status}")
            
            if run.status == "completed":
                return await self._get_assistant_response(channel_id, thread_id, run_id)
            elif run.status in ["queued", "in_progress"]:
                continue
            else:
                # Handle failed, cancelled, expired, requires_action
                error_msg = f"Sorry, the process ended with status: {run.status}."
                if run.last_error:
                    error_msg += f" ({run.last_error.code}: {run.last_error.message})"
                return None, error_msg[:1950]
    
    async def _get_assistant_response(self, channel_id: int, thread_id: str, run_id: str) -> tuple[str | None, str | None]:
        """Retrieve the assistant's response from a completed run."""
        loop = asyncio.get_event_loop()
        
        try:
            messages = await loop.run_in_executor(
                None,
                partial(
                    self.client.beta.threads.messages.list,
                    thread_id=thread_id,
                    order="desc"
                )
            )
            
            # Find the assistant's response for this run
            for msg in messages.data:
                if msg.run_id == run_id and msg.role == "assistant":
                    response_text = "".join(
                        block.text.value 
                        for block in msg.content 
                        if block.type == "text"
                    )
                    logger.info(f"[Channel {channel_id}] Got response ({len(response_text)} chars)")
                    return response_text or None, None if response_text else "I received an empty response."
            
            return None, "Sorry, I couldn't retrieve a response."
            
        except Exception as e:
            logger.error(f"[Channel {channel_id}] Failed to get response: {e}")
            return None, "Sorry, I couldn't retrieve the response."


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
        
        self.assistant = AssistantHandler(Config.OPENAI_API_KEY, Config.ASSISTANT_ID)
        self.manual_mode = ManualModeController()
    
    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        self.loop.create_task(self._process_message_queue())
    
    async def on_ready(self) -> None:
        """Called when the bot has connected to Discord."""
        logger.info(f"Logged in as {self.user}")
        
        # Verify OpenAI assistant connection
        if not await self.assistant.verify_assistant():
            logger.warning("Assistant verification failed - Keith commands may not work")
        
        logger.info(f'Ready! Listening for "Keith" commands.')
        
        if TKINTER_AVAILABLE:
            logger.info(f'HalcM enabled for user ID: {Config.ALLOWED_USER_ID}')
        else:
            logger.warning('HalcM disabled (tkinter not available)')
    
    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        # Ignore own messages
        if message.author == self.user:
            return
        
        content_lower = message.content.lower()
        
        # Check for HalcM command
        if content_lower == "halcm":
            await self._handle_halcm(message)
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
                    f"Manual mode is already active. Type `stop` in the popup to exit.",
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
        
        # Process with typing indicator
        async with message.channel.typing():
            response, error = await self.assistant.process_prompt(message.channel.id, prompt)
        
        # Send response or error
        if error:
            await message.channel.send(error)
        elif response:
            await self._send_long_message(message.channel, response)
        else:
            await message.channel.send("I received an empty response.")
    
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
