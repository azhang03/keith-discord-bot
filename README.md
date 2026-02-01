# Keith - Discord AI Chat Bot

A Python-based Discord bot named "Keith" that uses the OpenAI Assistants API to provide intelligent and context-aware responses when mentioned. It also includes a special "manual control" mode for the bot owner.

This is a revamped version of a Discord bot I made all the way back in my Sophomore year before ChatGPT was even really a thing. I had a bunch of if-statements tied to various use cases back then that have now been lost. I decided to revive the bot seeing how I still have the application registered on the Discord Dev Portal, now enhanced with the power of modern AI APIs and a new manual control feature.

## Features

*   **AI Chat:** Listens for messages starting with "Keith" (case-insensitive).
*   **OpenAI Assistant Integration:** Connects to a pre-configured OpenAI Assistant using its ID.
*   **Contextual Conversations:** Leverages the OpenAI Assistants API and Threads for generating context-aware responses, maintaining conversation history per Discord channel.
*   **Manual Control Mode (`HalcM`):** Allows the bot owner (running the script locally) to trigger a local input popup (using Tkinter) and send messages directly *as the bot* until explicitly stopped.
*   **"Secure Configuration":** Was designed at first to use environment variables for API keys and tokens. Not sure how much of that is left over but I would recommend doing it. Still requires manual editing of the script for the owner's User ID.
*   **User Feedback:** Shows a "typing..." indicator in Discord while processing AI requests.

## Prerequisites

Before you begin, ensure you have the following:

1.  **Python:** Version 3.8 or higher recommended (uses features like `asyncio.create_task`).
2.  **pip:** Python package installer (usually comes with Python).
3.  **Discord Bot Application:**
    *   An existing Discord application with a Bot user created via the [Discord Developer Portal](https://discord.com/developers/applications).
    *   The bot must be invited to your Discord server(s) with necessary permissions (Send Messages, Read Message History, etc.).
4.  **OpenAI Account & API Key:**
    *   An account on the [OpenAI Platform](https://platform.openai.com/).
    *   An active API Key ([https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)).
    *   Billing enabled on your OpenAI account (required for API usage even with any initial free credits).
5.  **OpenAI Assistant ID:**
    *   An Assistant created via the OpenAI Platform ([https://platform.openai.com/assistants](https://platform.openai.com/assistants)). You will need its ID (starting with `asst_...`). Configure its instructions, model (e.g., `gpt-4o-mini`, `gpt-4-turbo`), and any tools directly in the OpenAI portal.
6.  **Tkinter:** Python's standard GUI library, required for the `HalcM` feature.
    *   **Windows/macOS:** Usually included with standard Python installations.
    *   **Linux (Debian/Ubuntu):** May require `sudo apt-get update && sudo apt-get install python3-tk`
    *   **Linux (Fedora):** May require `sudo dnf install python3-tkinter`
    *   The script will print a warning if Tkinter cannot be imported.

## Usage

1.  **AI Interaction (`Keith` command):**
    *   In any channel where the bot has permissions, type a message starting with `Keith` followed by your query or statement.
    *   Example: `Keith what's the weather like in London?`
    *   The bot will show a "typing..." indicator, process the request using the configured OpenAI Assistant, and respond in the channel, maintaining conversation context within that channel.

2.  **Manual Control (`HalcM` command):**
    *   **Trigger:** Only the user whose ID matches `ALLOWED_USER_ID` can use this. Type exactly `HalcM` in any channel the bot can see.
    *   **Requirement:** This command **only works** if the bot script is running on your **local computer** where a GUI can be displayed (it uses Tkinter). It will fail if Tkinter is not found or if the bot is hosted remotely.
    *   **Action:**
        *   The original `HalcM` message in Discord will be deleted (if permissions allow).
        *   A small input box window will pop up on your local computer.
        *   Type the message you want the bot to send into the popup box and press Enter or click OK.
        *   The bot will send that exact message to the Discord channel where you originally typed `HalcM`.
        *   The input box will reappear, allowing you to send multiple messages sequentially.
    *   **Stopping:** To exit manual mode, type `stop` into the popup box and press Enter/OK, or simply click the "Cancel" button on the popup.

## Important Notes & Limitations

*   **Security:** **NEVER** commit your `DISCORD_BOT_TOKEN` or `OPENAI_API_KEY` to version control (like Git). Use environment variables or a secure configuration method. Ensure `.env` is in your `.gitignore` file if used. Setting the correct `ALLOWED_USER_ID` is crucial for preventing unauthorized use of the `HalcM` command. I'm lazy so I just hardcode the stuff but yeah this is better.
*   **HalcM Locality:** The `HalcM` feature relies on Tkinter and direct script execution access. It **will not function** if the bot is hosted on a server, VPS, or cloud platform (like Heroku, Repl.it, etc.) as it cannot open a GUI window there. It's designed for local development or specific local control scenarios.
*   **Tkinter Dependency:** If Tkinter is not installed or cannot be imported, the `HalcM` command will be disabled, and the bot will notify you if you try to use it.
*   **Single HalcM Session:** The current implementation only supports one active `HalcM` session at a time. If you try to trigger it while it's already active (even in another channel), it will notify you and prevent a new session.
*   **Costs:** Using the OpenAI API incurs costs based on token usage. Careful with yo credit card!
