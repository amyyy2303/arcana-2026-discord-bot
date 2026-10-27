import os
import sys
import logging
import discord
from discord import app_commands
from discord.ext import commands

from database.db import get_db
from utils.embeds import error_embed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("discord_bot")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

# Set up gateway intents
intents = discord.Intents.default()
intents.message_content = True  # Required for ./cipher, ./answer, ./pass, ./reset
# Enable members intent if explicitly toggled in environment
if os.getenv("ENABLE_MEMBERS_INTENT", "false").lower() in ("true", "1", "yes"):
    intents.members = True


class DiscordBot(commands.Bot):
    """Modular Discord Bot with Cogs and slash command integration."""

    def __init__(self):
        super().__init__(
            command_prefix=["./", "!", "."],
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        """Asynchronous setup before the bot connects to Discord gateway."""
        # Initialize SQLite database schema
        db = get_db()
        await db.init()
        logger.info("Database initialized successfully.")

        # Load extension cogs
        initial_extensions = [
            "cogs.general",
            "cogs.server_management",
            "cogs.teams",
            "cogs.links",
            "cogs.json_tools",
            "cogs.cipher_event",
        ]

        for ext in initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}", exc_info=True)

        # Global command tree error handler
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.errors.MissingPermissions):
                perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
                msg = f"You do not have permission to use this command. Missing: {perms}"
                embed = error_embed("Permission Denied", msg)
            elif isinstance(error, app_commands.errors.BotMissingPermissions):
                perms = ", ".join(f"`{p}`" for p in error.missing_permissions)
                msg = f"I am missing permissions to execute this command: {perms}"
                embed = error_embed("Bot Missing Permission", msg)
            elif isinstance(error, app_commands.errors.CommandOnCooldown):
                msg = f"This command is on cooldown. Try again in {error.retry_after:.1f} seconds."
                embed = error_embed("Cooldown", msg)
            else:
                logger.error(f"Unhandled command error: {error}", exc_info=error)
                embed = error_embed("Command Error", "An unexpected error occurred while executing this command.")

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        # Sync application commands globally
        logger.info("Syncing slash commands...")
        synced = await self.tree.sync()
        logger.info(f"Slash commands synced successfully. Total commands: {len(synced)}")

    async def on_ready(self):
        """Event triggered when connection to Discord is ready."""
        print(f"Logged in as {self.user}")
        print("Slash commands synced successfully.")


bot = DiscordBot()

if __name__ == "__main__":
    bot.run(TOKEN)

