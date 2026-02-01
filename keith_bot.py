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
        
        # Check for Keith command
        if content_lower.startswith("keith"):
            await self._handle_keith(message)
    
    async def _handle_keith(self, message: discord.Message) -> None:
        """Handle the Keith AI command."""
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
                if action == "gather_voice":
                    await self._gather_all_to_voice()
                self._action_queue.task_done()
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error processing action: {e}")
                self.gui.log_chat(f"Action error: {e}", "error")
    
    async def _gather_all_to_voice(self) -> None:
        """Move all users from all voice channels to the target channel."""
        target_channel = self.get_channel(Config.GATHER_VOICE_CHANNEL_ID)
        
        if not target_channel:
            self.gui.log_chat(f"Error: Target voice channel {Config.GATHER_VOICE_CHANNEL_ID} not found", "error")
            return
        
        if not isinstance(target_channel, discord.VoiceChannel):
            self.gui.log_chat(f"Error: Channel {Config.GATHER_VOICE_CHANNEL_ID} is not a voice channel", "error")
            return
        
        self.gui.log_system(f"Gathering everyone to #{target_channel.name}...")
        
        moved_count = 0
        failed_count = 0
        
        for guild in self.guilds:
            for voice_channel in guild.voice_channels:
                # Skip the target channel itself
                if voice_channel.id == Config.GATHER_VOICE_CHANNEL_ID:
                    continue
                
                # Move each member in this voice channel
                for member in voice_channel.members:
                    try:
                        await member.move_to(target_channel)
                        self.gui.log_system(f"Moved {member.display_name} from #{voice_channel.name} to #{target_channel.name}")
                        moved_count += 1
                    except discord.Forbidden:
                        self.gui.log_chat(f"No permission to move {member.display_name}", "error")
                        failed_count += 1
                    except discord.HTTPException as e:
                        self.gui.log_chat(f"Failed to move {member.display_name}: {e}", "error")
                        failed_count += 1
        
        if moved_count > 0 or failed_count > 0:
            self.gui.log_system(f"Gather complete: {moved_count} moved, {failed_count} failed")
        else:
            self.gui.log_system("No users found in other voice channels")
    
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
        self.connect_btn.grid(row=0, column=2, padx=(15, 5), pady=10)
        
        # Gather all to voice button
        self.gather_btn = ctk.CTkButton(
            self.status_frame,
            text="Gather All",
            command=self._gather_all_to_voice,
            width=100,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            state="disabled"
        )
        self.gather_btn.grid(row=0, column=3, padx=(5, 15), pady=10)
        
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
        
        # === Manual Message Section (Bottom) ===
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))
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
            self.gather_btn.configure(state="normal")
        else:
            self.connect_btn.configure(text="Connect")
            self.message_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.channel_dropdown.configure(state="disabled")
            self.gather_btn.configure(state="disabled")
    
    def populate_channels(self, channels: list[tuple[int, str, str]]) -> None:
        """Populate channel dropdown."""
        self.channels = channels
        if channels:
            display_names = [f"#{name} ({guild})" for _, name, guild in channels]
            self.channel_dropdown.configure(values=display_names)
            self.channel_dropdown.set(display_names[0])
        else:
            self.channel_dropdown.configure(values=["No channels available"])
    
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
    
    def _gather_all_to_voice(self) -> None:
        """Trigger gathering all users to the target voice channel."""
        if not self.bot or not self.bot._ready:
            return
        
        self.log_system("Initiating voice channel gather...")
        self.bot.queue_action("gather_voice")
    
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
