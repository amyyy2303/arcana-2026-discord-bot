import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from database.db import get_db
from utils.embeds import success_embed, error_embed, info_embed, warning_embed


class TeamCog(commands.Cog, name="Teams"):
    """Team creation, membership, and management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = get_db()

    team_group = app_commands.Group(name="team", description="Team management commands")

    # ---------------- CREATE TEAM ---------------- #

    @team_group.command(name="create", description="Create a new team")
    @app_commands.describe(
        name="Team name",
        description="Optional brief description of the team",
        create_role="Create a dedicated Discord role for this team (Default: False)",
    )
    @app_commands.guild_only()
    async def team_create(
        self,
        interaction: discord.Interaction,
        name: str,
        description: Optional[str] = "",
        create_role: Optional[bool] = False,
    ):
        guild = interaction.guild
        clean_name = name.strip()
        if len(clean_name) < 2 or len(clean_name) > 50:
            await interaction.response.send_message(
                embed=error_embed("Invalid Name", "Team name must be between 2 and 50 characters."),
                ephemeral=True,
            )
            return

        # Check if team already exists in guild
        existing = await self.db.get_team(guild.id, clean_name)
        if existing:
            await interaction.response.send_message(
                embed=error_embed("Team Already Exists", f"A team named **{clean_name}** already exists in this server."),
                ephemeral=True,
            )
            return

        role_id = None
        if create_role:
            bot_member = guild.me
            if bot_member.guild_permissions.manage_roles:
                try:
                    new_role = await guild.create_role(
                        name=f"Team: {clean_name}",
                        reason=f"Created for team {clean_name} by {interaction.user}",
                    )
                    role_id = new_role.id
                    if isinstance(interaction.user, discord.Member):
                        await interaction.user.add_roles(new_role, reason="Team creator")
                except discord.HTTPException as e:
                    await interaction.response.send_message(
                        embed=warning_embed("Role Creation Failed", f"Could not create role: {e}"),
                        ephemeral=True,
                    )
            else:
                await interaction.response.send_message(
                    embed=warning_embed("Missing Permissions", "Bot lacks `Manage Roles` permission to create a team role."),
                    ephemeral=True,
                )

        team_id = await self.db.create_team(
            guild_id=guild.id,
            name=clean_name,
            description=description or "",
            leader_id=interaction.user.id,
            role_id=role_id,
        )

        if not team_id:
            await interaction.response.send_message(
                embed=error_embed("Creation Failed", "Could not save team to database. Please try again."),
                ephemeral=True,
            )
            return

        embed = success_embed(
            title=f"Team Created: {clean_name}",
            description=description if description else "No description provided.",
        )
        embed.add_field(name="👑 Leader", value=interaction.user.mention, inline=True)
        if role_id:
            embed.add_field(name="🏷️ Linked Role", value=f"<@&{role_id}>", inline=True)
        embed.add_field(name="👥 Members", value="1 (Leader)", inline=True)
        embed.set_footer(text=f"Use /team join {clean_name} to join!")

        await interaction.response.send_message(embed=embed)

    # ---------------- JOIN TEAM ---------------- #

    @team_group.command(name="join", description="Join an existing team")
    @app_commands.describe(name="Team name to join")
    @app_commands.guild_only()
    async def team_join(self, interaction: discord.Interaction, name: str):
        guild = interaction.guild
        team = await self.db.get_team(guild.id, name)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Team **{name}** was not found."),
                ephemeral=True,
            )
            return

        is_member = await self.db.is_team_member(team["id"], interaction.user.id)
        if is_member:
            await interaction.response.send_message(
                embed=info_embed("Already Joined", f"You are already a member of **{team['name']}**."),
                ephemeral=True,
            )
            return

        success = await self.db.add_team_member(team["id"], interaction.user.id)
        if not success:
            await interaction.response.send_message(
                embed=error_embed("Error", "Failed to join team."),
                ephemeral=True,
            )
            return

        # Assign role if present
        if team.get("role_id"):
            role = guild.get_role(team["role_id"])
            if role and isinstance(interaction.user, discord.Member):
                try:
                    await interaction.user.add_roles(role, reason="Joined team")
                except discord.DiscordException:
                    pass

        await interaction.response.send_message(
            embed=success_embed("Team Joined", f"{interaction.user.mention} has joined **{team['name']}**!")
        )

    # ---------------- LEAVE TEAM ---------------- #

    @team_group.command(name="leave", description="Leave a team you belong to")
    @app_commands.describe(name="Team name to leave")
    @app_commands.guild_only()
    async def team_leave(self, interaction: discord.Interaction, name: str):
        guild = interaction.guild
        team = await self.db.get_team(guild.id, name)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Team **{name}** was not found."),
                ephemeral=True,
            )
            return

        if team["leader_id"] == interaction.user.id:
            await interaction.response.send_message(
                embed=warning_embed(
                    "Leader Cannot Leave",
                    f"You are the leader of **{team['name']}**. To disband the team, use `/team delete {team['name']}`.",
                ),
                ephemeral=True,
            )
            return

        is_member = await self.db.is_team_member(team["id"], interaction.user.id)
        if not is_member:
            await interaction.response.send_message(
                embed=error_embed("Not a Member", f"You are not a member of **{team['name']}**."),
                ephemeral=True,
            )
            return

        await self.db.remove_team_member(team["id"], interaction.user.id)

        # Remove role if present
        if team.get("role_id"):
            role = guild.get_role(team["role_id"])
            if role and isinstance(interaction.user, discord.Member):
                try:
                    await interaction.user.remove_roles(role, reason="Left team")
                except discord.DiscordException:
                    pass

        await interaction.response.send_message(
            embed=success_embed("Team Left", f"{interaction.user.mention} has left **{team['name']}**.")
        )

    # ---------------- ADD MEMBER (LEADER/ADMIN) ---------------- #

    @team_group.command(name="add_member", description="Add a member to a team (Leader or Admin only)")
    @app_commands.describe(name="Team name", member="Member to add")
    @app_commands.guild_only()
    async def team_add_member(self, interaction: discord.Interaction, name: str, member: discord.Member):
        guild = interaction.guild
        team = await self.db.get_team(guild.id, name)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Team **{name}** was not found."),
                ephemeral=True,
            )
            return

        is_admin = interaction.user.guild_permissions.manage_guild or interaction.user == guild.owner
        if team["leader_id"] != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only the team leader or server administrators can add members."),
                ephemeral=True,
            )
            return

        if await self.db.is_team_member(team["id"], member.id):
            await interaction.response.send_message(
                embed=info_embed("Already in Team", f"{member.mention} is already in **{team['name']}**."),
                ephemeral=True,
            )
            return

        await self.db.add_team_member(team["id"], member.id)

        if team.get("role_id"):
            role = guild.get_role(team["role_id"])
            if role:
                try:
                    await member.add_roles(role, reason=f"Added to team by {interaction.user}")
                except discord.DiscordException:
                    pass

        await interaction.response.send_message(
            embed=success_embed("Member Added", f"{member.mention} was added to **{team['name']}** by {interaction.user.mention}.")
        )

    # ---------------- REMOVE MEMBER (LEADER/ADMIN) ---------------- #

    @team_group.command(name="remove_member", description="Remove a member from a team (Leader or Admin only)")
    @app_commands.describe(name="Team name", member="Member to remove")
    @app_commands.guild_only()
    async def team_remove_member(self, interaction: discord.Interaction, name: str, member: discord.Member):
        guild = interaction.guild
        team = await self.db.get_team(guild.id, name)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Team **{name}** was not found."),
                ephemeral=True,
            )
            return

        is_admin = interaction.user.guild_permissions.manage_guild or interaction.user == guild.owner
        if team["leader_id"] != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only the team leader or server administrators can remove members."),
                ephemeral=True,
            )
            return

        if member.id == team["leader_id"]:
            await interaction.response.send_message(
                embed=error_embed("Action Disallowed", "Cannot remove the team leader from their own team."),
                ephemeral=True,
            )
            return

        if not await self.db.is_team_member(team["id"], member.id):
            await interaction.response.send_message(
                embed=error_embed("Not in Team", f"{member.mention} is not in **{team['name']}**."),
                ephemeral=True,
            )
            return

        await self.db.remove_team_member(team["id"], member.id)

        if team.get("role_id"):
            role = guild.get_role(team["role_id"])
            if role:
                try:
                    await member.remove_roles(role, reason=f"Removed from team by {interaction.user}")
                except discord.DiscordException:
                    pass

        await interaction.response.send_message(
            embed=success_embed("Member Removed", f"{member.mention} was removed from **{team['name']}**.")
        )

    # ---------------- LIST TEAMS ---------------- #

    @team_group.command(name="list", description="List all teams in this server")
    @app_commands.guild_only()
    async def team_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        teams = await self.db.list_teams(guild.id)
        if not teams:
            await interaction.response.send_message(
                embed=info_embed("No Teams", "There are currently no teams in this server. Create one with `/team create`!"),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"Server Teams ({len(teams)})",
            color=discord.Color.teal(),
        )

        for t in teams[:25]:  # Discord embed field limit
            leader_str = f"<@{t['leader_id']}>"
            desc = t["description"] if t["description"] else "No description"
            if len(desc) > 80:
                desc = desc[:77] + "..."
            embed.add_field(
                name=f"👥 {t['name']}",
                value=f"**Leader:** {leader_str}\n**Members:** {t['member_count']}\n_{desc}_",
                inline=False,
            )

        if len(teams) > 25:
            embed.set_footer(text=f"Showing 25 of {len(teams)} teams.")
        await interaction.response.send_message(embed=embed)

    # ---------------- TEAM INFO ---------------- #

    @team_group.command(name="info", description="View detailed roster and information for a team")
    @app_commands.describe(name="Team name")
    @app_commands.guild_only()
    async def team_info(self, interaction: discord.Interaction, name: str):
        guild = interaction.guild
        team = await self.db.get_team(guild.id, name)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Team **{name}** was not found."),
                ephemeral=True,
            )
            return

        member_ids = await self.db.get_team_members(team["id"])
        member_mentions = [f"<@{uid}>" for uid in member_ids]
        members_str = ", ".join(member_mentions) if member_mentions else "None"
        if len(members_str) > 1024:
            members_str = f"{len(member_ids)} members (display truncated)"

        embed = discord.Embed(
            title=f"Team: {team['name']}",
            description=team["description"] if team["description"] else "No description provided.",
            color=discord.Color.teal(),
        )
        embed.add_field(name="👑 Leader", value=f"<@{team['leader_id']}>", inline=True)
        embed.add_field(name="👥 Member Count", value=str(len(member_ids)), inline=True)

        if team.get("role_id"):
            embed.add_field(name="🏷️ Role", value=f"<@&{team['role_id']}>", inline=True)

        embed.add_field(name="📅 Created", value=f"{team['created_at']}", inline=True)
        embed.add_field(name="📋 Members", value=members_str, inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------------- DELETE TEAM ---------------- #

    @team_group.command(name="delete", description="Delete a team (Leader or Admin only)")
    @app_commands.describe(name="Team name to delete")
    @app_commands.guild_only()
    async def team_delete(self, interaction: discord.Interaction, name: str):
        guild = interaction.guild
        team = await self.db.get_team(guild.id, name)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"Team **{name}** was not found."),
                ephemeral=True,
            )
            return

        is_admin = interaction.user.guild_permissions.manage_guild or interaction.user == guild.owner
        if team["leader_id"] != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only the team leader or server administrators can delete this team."),
                ephemeral=True,
            )
            return

        # Attempt to delete Discord role if one was tied to the team
        if team.get("role_id"):
            role = guild.get_role(team["role_id"])
            if role:
                try:
                    await role.delete(reason=f"Team {team['name']} deleted by {interaction.user}")
                except discord.DiscordException:
                    pass

        deleted = await self.db.delete_team(guild.id, name)
        if deleted:
            await interaction.response.send_message(
                embed=success_embed("Team Deleted", f"Team **{team['name']}** has been deleted.")
            )
        else:
            await interaction.response.send_message(
                embed=error_embed("Error", "Failed to delete team."),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))

