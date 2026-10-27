import discord
from discord import app_commands
from discord.ext import commands
from utils.embeds import info_embed


class GeneralCog(commands.Cog, name="General"):
    """General utility commands including hello, ping, and help."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="hello", description="Say hello to the bot")
    async def hello(self, interaction: discord.Interaction):
        """Preserved command: Say hello to the bot."""
        await interaction.response.send_message(
            f"Hello, {interaction.user.mention}! The bot is working."
        )

    @app_commands.command(name="ping", description="Check bot response time")
    async def ping(self, interaction: discord.Interaction):
        """Preserved command: Check bot response time."""
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"Pong! Latency: {latency_ms} ms"
        )

    @app_commands.command(name="help", description="Show available bot commands and features")
    async def help_command(self, interaction: discord.Interaction):
        """Display help overview embed."""
        embed = info_embed(
            title="Discord Bot Commands & Features",
            description="Here is an overview of the commands available on this server:",
        )
        embed.add_field(
            name="👋 General",
            value="`/hello` - Greet the bot\n`/ping` - Check response latency\n`/help` - Show this guide",
            inline=False,
        )
        embed.add_field(
            name="🛡️ Server Management",
            value=(
                "`/serverinfo` - Server statistics & details\n"
                "`/userinfo [member]` - User profile & roles\n"
                "`/role add <member> <role>` - Assign a role\n"
                "`/role remove <member> <role>` - Revoke a role\n"
                "`/clear <amount>` - Bulk delete messages\n"
                "`/timeout <member> <minutes> [reason]` - Timeout member\n"
                "`/slowmode <seconds>` - Set channel slowmode"
            ),
            inline=False,
        )
        embed.add_field(
            name="👥 Team Management",
            value=(
                "`/team create <name> [desc] [create_role]` - Create a team\n"
                "`/team join <name>` - Join a team\n"
                "`/team leave <name>` - Leave your team\n"
                "`/team add_member <name> <member>` - Add member (leader/admin)\n"
                "`/team remove_member <name> <member>` - Remove member\n"
                "`/team list` - View all server teams\n"
                "`/team info <name>` - View team roster and details\n"
                "`/team delete <name>` - Delete a team"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔗 Link Bookmarks & Organization",
            value=(
                "`/link add <url> <title> [cat] [tags] [desc]` - Save link\n"
                "`/link search <query> [category]` - Search saved links\n"
                "`/link list [category]` - List links by category\n"
                "`/link categories` - View categories with counts\n"
                "`/link get <id>` - Get link details\n"
                "`/link edit <id>` - Edit link metadata\n"
                "`/link delete <id>` - Delete a saved link"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔧 JSON & Data Tools",
            value=(
                "`/json validate [text] [file]` - Validate JSON syntax & get stats\n"
                "`/json format [text] [file] [indent]` - Format/beautify JSON\n"
                "`/json minify [text] [file]` - Compact JSON into one line\n"
                "`/json convert <format> [text] [file]` - Convert CSV/YAML/PyDict to JSON\n"
                "`/json modal` - Open multiline interactive editor"
            ),
            inline=False,
        )
        embed.add_field(
            name="🧩 Cipher Event Competition",
            value=(
                "`./cipher` (or `/cipher`) - Request your team's random cipher challenge\n"
                "`./answer <text>` (or `/answer`) - Submit solution (+150/+250/+400, -12 wrong; max 4 attempts)\n"
                "`./pass` (or `/pass`) - Skip question (+20 to opponents, burns current + random)\n"
                "`./leaderboard` (or `/leaderboard`) - View tournament standings\n"
                "`./admin_room` - Designate channel for real-time live leaderboard (Admin)\n"
                "`./reset [score]` - Reset scores & restore all 16 queues (Admin)\n"
                "`./setup_event` - Register all 13 teams (Admin)\n"
                "`./setup_event true` - Register teams and create/link their channels (Admin)"
            ),
            inline=False,
        )
        embed.set_footer(text="discord-bot • Python & discord.py")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GeneralCog(bot))
