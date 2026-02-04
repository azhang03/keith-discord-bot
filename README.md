# Keith - Discord AI Chat Bot

A desktop application for running an AI-powered Discord bot named "Keith" that uses Anthropic's Claude API. Features a modern dark-themed GUI with sidebar navigation.

## Features

### Core Features
* **Modern GUI Application** - Sleek dark-themed interface with sidebar navigation
* **AI Chat** - Users type "Keith" followed by their message to chat with Claude AI
* **Contextual Conversations** - Keith remembers conversation history per channel
* **Smart Detection Mode** - AI-powered detection to respond to relevant mentions
* **Manual Message Sending** - Send messages as Keith to any channel directly from the app

### Meme Features (Voice Channel)
* **Tomato Town** - Gather everyone to a voice channel, play audio, then kick them all
* **Super Server** - Join a voice channel and loop audio indefinitely
* **Stalker Mode** - Follow a specific user and play audio whenever they join voice

### GUI Features
* **Sidebar Navigation** - Switch between Dashboard, Memes, and Settings views
* **Console Logs** - Real-time system and event logging
* **Memory Panel** - View AI conversation context and history
* **High-DPI Support** - Crisp rendering on high-resolution displays

## Prerequisites

1. **Python 3.10+**
2. **Discord Bot Application:**
   * Create a bot at [Discord Developer Portal](https://discord.com/developers/applications)
   * Enable **MESSAGE CONTENT INTENT** in Bot settings
   * Enable **SERVER MEMBERS INTENT** for voice features
   * Invite bot with: Send Messages, Read Message History, Connect, Speak, Move Members permissions
3. **Anthropic API Key:**
   * Get one from [Anthropic Console](https://console.anthropic.com/)
4. **FFmpeg** (for voice features):
   * Download from [ffmpeg.org](https://ffmpeg.org/download.html)
   * Add to system PATH or set `FFMPEG_PATH` in `.env`

## Installation

1. **Clone or download the repository**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your credentials:
   ```env
   DISCORD_BOT_TOKEN=your_discord_bot_token
   ANTHROPIC_API_KEY=your_anthropic_api_key
   ```

## Running the App

```bash
python keith_bot.py
```

## GUI Overview

### Sidebar Navigation
| Icon | View | Description |
|------|------|-------------|
| ⌂ | **Dashboard** | Main view with Console Logs and Memory panels |
| ⚡ | **Memes** | Voice channel meme controls |
| ⚙ | **Settings** | Bot configuration options |

### Dashboard View
* **Console Logs** - System events, errors, and status messages
* **Memory** - AI conversation history and context

### Memes View
| Feature | Description |
|---------|-------------|
| **Tomato Town** | Moves all users to a voice channel, plays audio, then kicks everyone |
| **Super Server** | Joins a voice channel and loops audio indefinitely |
| **Stalker Mode** | Follows a target user (by ID) and plays audio when they join voice |

### Settings View
| Setting | Description |
|---------|-------------|
| **Command Prefix** | Prefix for utility commands (default: `k!`) |
| **Smart Detection** | AI-powered detection to respond to relevant Keith mentions |
| **Spam Ping Count** | Number of pings for the spam ping command |

### Log Colors
* 🔵 **Blue** - User messages to Keith
* 🟢 **Green** - Keith's AI responses
* 🟡 **Yellow/Amber** - Warnings and manual messages
* ⚪ **Gray** - System/info messages
* 🔴 **Red** - Errors

## Discord Commands

### AI Chat
| Command | Description |
|---------|-------------|
| `Keith <message>` | Talk to Keith |
| `Keith clear` | Clear conversation history |
| `Keith reset` | Same as clear |
| `Keith forget` | Same as clear |

### Utility Commands
| Command | Description |
|---------|-------------|
| `k!help` | Show available commands |
| `k!purge <number>` | Delete the last N messages (max 100) |
| `ping @user` | Spam ping a user (count set in Settings) |

## Configuration Options

All options are set in the `.env` file:

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Your Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `CLAUDE_MODEL` | No | Model to use (default: `claude-sonnet-4-20250514`) |
| `RELEVANCE_MODEL` | No | Model for Smart Detection (default: `claude-3-5-haiku-20241022`) |
| `KEITH_SYSTEM_PROMPT` | No | Custom personality prompt |
| `MAX_CONVERSATION_HISTORY` | No | Max message pairs to remember (default: 20) |
| `RECENT_CHANNEL_MESSAGES` | No | Recent messages for context (default: 7) |
| `GATHER_VOICE_CHANNEL_ID` | No | Voice channel ID for Tomato Town |
| `SUPER_SERVER_CHANNEL_ID` | No | Voice channel ID for Super Server |
| `FFMPEG_PATH` | No | Path to FFmpeg if not in system PATH |

## Available Claude Models

* `claude-sonnet-4-20250514` - Best balance (default)
* `claude-opus-4-20250514` - Most capable
* `claude-3-5-haiku-20241022` - Fastest, cheapest

## Audio Files

Place audio files in the `audio/` folder:
* `tomato.mp3` - Played during Tomato Town
* `dd.mp3` - Played for Super Server and Stalker Mode

## Notes

* **Security:** Never commit your `.env` file
* **Costs:** Claude API usage incurs costs based on tokens
* **Rate Limits:** The bot handles rate limits gracefully
* **Voice Features:** Require FFmpeg to be installed
* **Stalker Mode:** Enter the target's Discord User ID (enable Developer Mode in Discord to copy IDs)
