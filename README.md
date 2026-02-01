# Keith - Discord AI Chat Bot

A Python-based Discord bot named "Keith" that uses Anthropic's Claude API to provide intelligent and context-aware responses when mentioned. It also includes a special "manual control" mode for the bot owner.

This is a revamped version of a Discord bot I made all the way back in my Sophomore year before ChatGPT was even really a thing. I had a bunch of if-statements tied to various use cases back then that have now been lost. I decided to revive the bot seeing how I still have the application registered on the Discord Dev Portal, now enhanced with the power of modern AI APIs and a new manual control feature.

## Features

*   **AI Chat:** Listens for messages starting with "Keith" (case-insensitive).
*   **Claude Integration:** Connects to Anthropic's Claude API for intelligent responses.
*   **Contextual Conversations:** Maintains conversation history per Discord channel (configurable length).
*   **Clear History:** Use `Keith clear`, `Keith reset`, or `Keith forget` to start a fresh conversation.
*   **Manual Control Mode (`HalcM`):** Allows the bot owner (running the script locally) to trigger a local input popup (using Tkinter) and send messages directly *as the bot* until explicitly stopped.
*   **Secure Configuration:** Uses `.env` file for API keys and tokens - never commit secrets to version control!
*   **User Feedback:** Shows a "typing..." indicator in Discord while processing AI requests.

## Prerequisites

Before you begin, ensure you have the following:

1.  **Python:** Version 3.10 or higher recommended.
2.  **pip:** Python package installer (usually comes with Python).
3.  **Discord Bot Application:**
    *   An existing Discord application with a Bot user created via the [Discord Developer Portal](https://discord.com/developers/applications).
    *   The bot must be invited to your Discord server(s) with necessary permissions (Send Messages, Read Message History, Manage Messages for HalcM).
    *   **MESSAGE CONTENT INTENT** must be enabled in the Bot settings.
4.  **Anthropic Account & API Key:**
    *   An account on the [Anthropic Console](https://console.anthropic.com/).
    *   An active API Key from the console.
5.  **Tkinter (Optional):** Python's standard GUI library, required for the `HalcM` feature.
    *   **Windows/macOS:** Usually included with standard Python installations.
    *   **Linux (Debian/Ubuntu):** May require `sudo apt-get install python3-tk`
    *   **Linux (Fedora):** May require `sudo dnf install python3-tkinter`
    *   The bot will work without it, but `HalcM` will be disabled.

## Setup

1.  **Clone or download the repository.**

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment variables:**
    ```bash
    cp .env.example .env
    ```
    Then edit `.env` with your actual values:
    ```env
    DISCORD_BOT_TOKEN=your_discord_bot_token
    ANTHROPIC_API_KEY=your_anthropic_api_key
    CLAUDE_MODEL=claude-sonnet-4-20250514
    ALLOWED_USER_ID=your_discord_user_id
    ```

4.  **Run the bot:**
    ```bash
    python keith_bot.py
    ```

## Usage

1.  **AI Interaction (`Keith` command):**
    *   In any channel where the bot has permissions, type a message starting with `Keith` followed by your query.
    *   Example: `Keith what's the weather like in London?`
    *   The bot will show a "typing..." indicator, process the request using Claude, and respond in the channel.
    *   Conversations maintain context per channel automatically.

2.  **Clear Conversation History:**
    *   Type `Keith clear`, `Keith reset`, or `Keith forget` to start fresh.

3.  **Manual Control (`HalcM` command):**
    *   **Trigger:** Only the user whose ID matches `ALLOWED_USER_ID` can use this. Type exactly `HalcM` in any channel.
    *   **Requirement:** Only works when running the bot locally with a GUI (uses Tkinter).
    *   **Action:**
        *   The `HalcM` message in Discord will be deleted.
        *   A small input box window will pop up on your computer.
        *   Type messages to send as the bot, press Enter or OK.
        *   The input box reappears for multiple messages.
    *   **Stopping:** Type `stop` or click Cancel to exit manual mode.

## Configuration Options

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Your Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `CLAUDE_MODEL` | No | Claude model to use (default: `claude-sonnet-4-20250514`) |
| `KEITH_SYSTEM_PROMPT` | No | Custom personality prompt for Keith |
| `ALLOWED_USER_ID` | No | Discord user ID for HalcM access |
| `MAX_CONVERSATION_HISTORY` | No | Max message pairs to remember (default: 20) |

## Available Claude Models

- `claude-sonnet-4-20250514` - Best balance of speed and intelligence (default)
- `claude-opus-4-20250514` - Most capable, slower and more expensive
- `claude-3-5-haiku-20241022` - Fastest, most affordable

## Important Notes

*   **Security:** Never commit your `.env` file! It's already in `.gitignore`.
*   **HalcM Locality:** Only works when running locally with a GUI - won't work on cloud hosting.
*   **Costs:** Claude API usage incurs costs based on tokens. Monitor your usage!
*   **Rate Limits:** The bot handles rate limits gracefully with user-friendly error messages.
