import datetime
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from utils.embeds import success_embed, error_embed, info_embed


class ServerManagementCog(commands.Cog, name="Server Management"):
    """Server management, moderation, and diagnostic commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Group for role management
    role_group = app_commands.Group(name="role", description="Manage guild member roles")

    # ---------------- SERVER INFO ---------------- #

    @app_commands.command(name="serverinfo", description="Display comprehensive information about this server")
    @app_commands.guild_only()
    async def server_info(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                embed=error_embed("Error", "This command can only be used in a server."), ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Server Information: {guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        owner = guild.owner or (await self.bot.fetch_user(guild.owner_id) if guild.owner_id else "Unknown")
        created_str = guild.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Counts
        total_members = guild.member_count or len(guild.members)
        humans = sum(1 for m in guild.members if not m.bot) if guild.members else "N/A"
        bots = sum(1 for m in guild.members if m.bot) if guild.members else "N/A"
        member_breakdown = f"Total: **{total_members}**"
        if humans != "N/A":
            member_breakdown += f" (Humans: {humans}, Bots: {bots})"

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        channel_info = f"Text: **{text_channels}** | Voice: **{voice_channels}** | Categories: **{categories}**"

        embed.add_field(name="👑 Owner", value=f"{owner}", inline=True)
        embed.add_field(name="🆔 Server ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="📅 Created", value=f"<t:{int(guild.created_at.timestamp())}:R>\n`{created_str}`", inline=True)
        embed.add_field(name="👥 Members", value=member_breakdown, inline=False)
        embed.add_field(name="📁 Channels", value=channel_info, inline=False)
        embed.add_field(name="🏷️ Roles", value=f"**{len(guild.roles)}** roles", inline=True)
        embed.add_field(name="🚀 Boost Level", value=f"Tier **{guild.premium_tier}** ({guild.premium_subscription_count} boosts)", inline=True)
        embed.add_field(name="🔒 Verification", value=f"{str(guild.verification_level).capitalize()}", inline=True)

        embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ---------------- USER INFO ---------------- #

    @app_commands.command(name="userinfo", description="Display details about a user or yourself")
    @app_commands.describe(member="The server member to inspect (leave blank for yourself)")
    @app_commands.guild_only()
    async def user_info(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        if not isinstance(target, discord.Member):
            target = interaction.guild.get_member(target.id) or target

        embed = discord.Embed(
            title=f"User Profile: {target.display_name}",
            color=target.color if target.color.value != 0 else discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(name="👤 Username", value=f"{target.name}", inline=True)
        embed.add_field(name="🆔 User ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="🤖 Bot?", value="Yes" if target.bot else "No", inline=True)

        created_ts = int(target.created_at.timestamp())
        embed.add_field(name="🎂 Account Created", value=f"<t:{created_ts}:D> (<t:{created_ts}:R>)", inline=False)

        if isinstance(target, discord.Member) and target.joined_at:
            joined_ts = int(target.joined_at.timestamp())
            embed.add_field(name="📥 Joined Server", value=f"<t:{joined_ts}:D> (<t:{joined_ts}:R>)", inline=False)

            roles = [r.mention for r in target.roles if r != interaction.guild.default_role]
            roles_str = ", ".join(reversed(roles)) if roles else "None"
            if len(roles_str) > 1024:
                roles_str = f"{len(roles)} roles (list truncated)"
            embed.add_field(name=f"🏷️ Roles [{len(roles)}]", value=roles_str, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------------- ROLE ASSIGNMENT ---------------- #

    @role_group.command(name="add", description="Assign a role to a member")
    @app_commands.describe(member="Member to receive the role", role="Role to assign")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        guild = interaction.guild
        bot_member = guild.me

        # Check permissions & hierarchy
        if not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                embed=error_embed("Missing Bot Permission", "I do not have the `Manage Roles` permission."),
                ephemeral=True,
            )
            return

        if bot_member.top_role <= role:
            await interaction.response.send_message(
                embed=error_embed("Role Hierarchy Error", f"I cannot assign {role.mention} because it is equal to or higher than my highest role."),
                ephemeral=True,
            )
            return

        if interaction.user != guild.owner and interaction.user.top_role <= role:
            await interaction.response.send_message(
                embed=error_embed("Role Hierarchy Error", f"You cannot assign {role.mention} because it is equal to or higher than your highest role."),
                ephemeral=True,
            )
            return

        if role in member.roles:
            await interaction.response.send_message(
                embed=info_embed("Role Already Assigned", f"{member.mention} already has the {role.mention} role."),
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(role, reason=f"Assigned by {interaction.user} via /role add")
            await interaction.response.send_message(
                embed=success_embed("Role Assigned", f"Successfully assigned {role.mention} to {member.mention}.")
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Forbidden", "I do not have permission to modify roles for that user."),
                ephemeral=True,
            )

    @role_group.command(name="remove", description="Remove a role from a member")
    @app_commands.describe(member="Member to remove role from", role="Role to remove")
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        guild = interaction.guild
        bot_member = guild.me

        if not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                embed=error_embed("Missing Bot Permission", "I do not have the `Manage Roles` permission."),
                ephemeral=True,
            )
            return

        if bot_member.top_role <= role:
            await interaction.response.send_message(
                embed=error_embed("Role Hierarchy Error", f"I cannot remove {role.mention} because it is equal to or higher than my highest role."),
                ephemeral=True,
            )
            return

        if interaction.user != guild.owner and interaction.user.top_role <= role:
            await interaction.response.send_message(
                embed=error_embed("Role Hierarchy Error", f"You cannot remove {role.mention} because it is equal to or higher than your highest role."),
                ephemeral=True,
            )
            return

        if role not in member.roles:
            await interaction.response.send_message(
                embed=info_embed("Role Not Present", f"{member.mention} does not have the {role.mention} role."),
                ephemeral=True,
            )
            return

        try:
            await member.remove_roles(role, reason=f"Removed by {interaction.user} via /role remove")
            await interaction.response.send_message(
                embed=success_embed("Role Removed", f"Successfully removed {role.mention} from {member.mention}.")
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Forbidden", "I do not have permission to modify roles for that user."),
                ephemeral=True,
            )

    # ---------------- MESSAGE PURGE ---------------- #

    @app_commands.command(name="clear", description="Bulk delete recent messages in this channel")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear_messages(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                embed=error_embed("Error", "Messages can only be cleared in text channels or threads."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await channel.purge(limit=amount)
            await interaction.followup.send(
                embed=success_embed("Messages Cleared", f"Deleted **{len(deleted)}** messages from {channel.mention}."),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed("Forbidden", "I do not have permission to delete messages in this channel."),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                embed=error_embed("Error", f"Failed to purge messages: {str(e)}"),
                ephemeral=True,
            )

    # ---------------- TIMEOUT / MODERATE ---------------- #

    @app_commands.command(name="timeout", description="Temporarily timeout a member")
    @app_commands.describe(
        member="Member to timeout",
        duration_minutes="Duration in minutes (1 to 40320 - max 28 days)",
        reason="Reason for the timeout",
    )
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout_member(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration_minutes: app_commands.Range[int, 1, 40320],
        reason: Optional[str] = "No reason provided",
    ):
        guild = interaction.guild
        bot_member = guild.me

        if not bot_member.guild_permissions.moderate_members:
            await interaction.response.send_message(
                embed=error_embed("Missing Bot Permission", "I do not have `Timeout Members` permission."),
                ephemeral=True,
            )
            return

        if member.top_role >= bot_member.top_role or member == guild.owner:
            await interaction.response.send_message(
                embed=error_embed("Hierarchy Error", f"I cannot timeout {member.mention} due to role hierarchy."),
                ephemeral=True,
            )
            return

        if interaction.user != guild.owner and member.top_role >= interaction.user.top_role:
            await interaction.response.send_message(
                embed=error_embed("Hierarchy Error", f"You cannot timeout {member.mention} because their role is higher than or equal to yours."),
                ephemeral=True,
            )
            return

        until = discord.utils.utcnow() + datetime.timedelta(minutes=duration_minutes)
        try:
            await member.timeout(until, reason=f"By {interaction.user}: {reason}")
            await interaction.response.send_message(
                embed=success_embed(
                    "Member Timed Out",
                    f"{member.mention} has been timed out for **{duration_minutes} minutes**.\n**Reason:** {reason}\n**Expires:** <t:{int(until.timestamp())}:R>",
                )
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Forbidden", "I do not have permission to timeout this member."),
                ephemeral=True,
            )

    # ---------------- SLOWMODE ---------------- #

    @app_commands.command(name="slowmode", description="Set channel slowmode rate limit")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, up to 21600)")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
    ):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                embed=error_embed("Error", "Slowmode can only be configured in text channels or threads."),
                ephemeral=True,
            )
            return

        try:
            await channel.edit(slowmode_delay=seconds)
            status = "disabled" if seconds == 0 else f"set to **{seconds} seconds**"
            await interaction.response.send_message(
                embed=success_embed("Slowmode Updated", f"Slowmode in {channel.mention} has been {status}.")
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Forbidden", "I do not have permission to manage this channel."),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerManagementCog(bot))

