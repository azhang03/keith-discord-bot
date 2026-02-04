# Keith - Discord AI Chat Bot

A desktop application for running an AI-powered Discord bot named "Keith" that uses Anthropic's Claude API.

## Features

*   **Modern GUI Application** - No command line needed, just click to connect
*   **Connection Status** - Visual indicator showing bot's connection state
*   **Chat History Log** - See all Keith interactions in real-time with color-coded messages
*   **Manual Message Sending** - Send messages as Keith to any channel directly from the app
*   **AI Chat** - Users in Discord type "Keith" followed by their message to chat with Claude
*   **Contextual Conversations** - Keith remembers conversation history per channel
*   **Recent Message Context** - Keith can see recent channel messages when invoked

## Prerequisites

1.  **Python 3.10+** 
2.  **Discord Bot Application:**
    *   Create a bot at [Discord Developer Portal](https://discord.com/developers/applications)
    *   Enable **MESSAGE CONTENT INTENT** in Bot settings
    *   Invite bot to your server with Send Messages & Read Message History permissions
3.  **Anthropic API Key:**
    *   Get one from [Anthropic Console](https://console.anthropic.com/)

## Installation

1.  **Clone or download the repository**

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment:**
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

This opens the Keith Bot GUI:

1. Click **Connect** to start the bot
2. Watch the status indicator turn green when connected
3. See chat interactions appear in the log
4. Use the dropdown and text field to send manual messages

## GUI Overview

| Section | Description |
|---------|-------------|
| **Status Bar** | Shows connection status (green = connected, yellow = connecting, gray = disconnected) |
| **Chat History** | Color-coded log of all Keith interactions |
| **Channel Selector** | Dropdown to choose which channel to send manual messages to |
| **Message Input** | Type messages to send as Keith, press Enter or click Send |
| **Clear Log** | Clears the chat history display |

### Chat Log Colors

- 🔵 **Blue** - User messages to Keith
- 🟢 **Green** - Keith's AI responses  
- 🟡 **Yellow** - Manual messages you sent
- ⚪ **Gray** - System messages
- 🔴 **Red** - Errors

## Discord Commands

Users in your Discord server can use:

| Command | Description |
|---------|-------------|
| `Keith <message>` | Talk to Keith |
| `Keith clear` | Clear conversation history (also clears the GUI log) |
| `Keith reset` | Same as clear |
| `Keith forget` | Same as clear |

## Configuration Options

All options are set in the `.env` file:

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Your Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `CLAUDE_MODEL` | No | Model to use (default: `claude-sonnet-4-20250514`) |
| `KEITH_SYSTEM_PROMPT` | No | Custom personality prompt |
| `MAX_CONVERSATION_HISTORY` | No | Max message pairs to remember (default: 20) |
| `RECENT_CHANNEL_MESSAGES` | No | Recent messages for context (default: 7) |

## Available Claude Models

- `claude-sonnet-4-20250514` - Best balance (default)
- `claude-opus-4-20250514` - Most capable
- `claude-3-5-haiku-20241022` - Fastest, cheapest

## Notes

*   **Security:** Never commit your `.env` file
*   **Costs:** Claude API usage incurs costs based on tokens
*   **Rate Limits:** The bot handles rate limits gracefully
