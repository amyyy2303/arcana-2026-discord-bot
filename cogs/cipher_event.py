import os
import re
import json
import hashlib
import asyncio
import logging
from typing import Optional, Dict, Any, List

import discord
from discord import app_commands
from discord.ext import commands

from database.db import get_db
from utils.embeds import success_embed, error_embed, info_embed, warning_embed
from utils.security import normalize_answer, hash_answer, verify_answer

logger = logging.getLogger("discord_bot.cipher")


class CipherEventCog(commands.Cog, name="Cipher Event"):
    """Core Cog for the 13-team Discord Cipher Competition Event."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = get_db()
        self._leaderboard_locks: Dict[int, asyncio.Lock] = {}
        self._last_lb_update: Dict[int, float] = {}

    def _get_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._leaderboard_locks:
            self._leaderboard_locks[guild_id] = asyncio.Lock()
        return self._leaderboard_locks[guild_id]

    async def _resolve_team(self, ctx_or_interaction) -> Optional[Dict[str, Any]]:
        """Resolves the cipher team from channel, user roles, or server mapping."""
        if isinstance(ctx_or_interaction, commands.Context):
            guild = ctx_or_interaction.guild
            channel = ctx_or_interaction.channel
            author = ctx_or_interaction.author
        else:
            guild = ctx_or_interaction.guild
            channel = ctx_or_interaction.channel
            author = ctx_or_interaction.user

        if not guild:
            return None

        role_ids = [r.id for r in author.roles] if hasattr(author, "roles") else []
        channel_name = getattr(channel, "name", "")

        return await self.db.find_cipher_team_by_context(
            guild_id=guild.id,
            channel_id=channel.id,
            role_ids=role_ids,
            channel_name=channel_name,
        )

    # ---------------- LIVE LEADERBOARD ENGINE ---------------- #

    async def update_live_leaderboard(self, guild: discord.Guild):
        """Refreshes the live leaderboard embed in the designated admin room."""
        if not guild:
            return

        lock = self._get_lock(guild.id)
        async with lock:
            try:
                cfg = await self.db.get_cipher_config(guild.id)
                admin_chan_id = cfg.get("admin_channel_id") if cfg else None

                admin_channel = None
                if admin_chan_id:
                    admin_channel = guild.get_channel(admin_chan_id)
                if not admin_channel:
                    # Look for standard fallback channel names
                    for ch in guild.text_channels:
                        if ch.name.lower() in ("admin-room", "cipher-admin", "admin-live-leaderboard", "admin"):
                            admin_channel = ch
                            await self.db.set_cipher_config(guild.id, admin_channel_id=ch.id)
                            break

                if not admin_channel:
                    return

                leaderboard = await self.db.get_cipher_leaderboard(guild.id)
                embed = self._build_leaderboard_embed(guild, leaderboard)

                msg_id = cfg.get("leaderboard_message_id") if cfg else None
                message = None
                if msg_id:
                    try:
                        message = await admin_channel.fetch_message(msg_id)
                    except (discord.NotFound, discord.HTTPException):
                        message = None

                if message:
                    await message.edit(embed=embed)
                else:
                    new_msg = await admin_channel.send(embed=embed)
                    try:
                        await new_msg.pin(reason="Live Cipher Leaderboard")
                    except Exception:
                        pass
                    await self.db.set_cipher_config(guild.id, leaderboard_message_id=new_msg.id)

            except Exception as e:
                logger.error(f"Failed to update live leaderboard in guild {guild.id}: {e}", exc_info=True)

    def _build_leaderboard_embed(self, guild: discord.Guild, teams: List[Dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(
            title="🏆 LIVE CIPHER EVENT LEADERBOARD",
            description="Real-time scores & queue statistics for all 13 participating teams.\nUpdates automatically on every submission or pass.",
            color=discord.Color.gold(),
        )

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}

        for idx, t in enumerate(teams):
            rank_str = medals.get(idx, f"`{idx + 1:2d}.`")
            score = t["score"]
            name = t["name"]

            if t.get("is_disqualified"):
                status_icon = "⛔ **DISQUALIFIED**"
            elif t["active_question_id"]:
                diff_tag = t.get("active_q_diff", "").upper()
                pts = t.get("active_q_points", 0)
                attempt = t.get("active_attempts", 0) + 1
                status_icon = (
                    f"🟢 **ACTIVE — Q#{t['active_question_id']}** ({diff_tag} - {pts} pts; "
                    f"attempt {attempt}/4)"
                )
            else:
                status_icon = "⚪ **IDLE**"

            solved = t.get("solved_count", 0)
            passed = t.get("passed_count", 0)
            burned = t.get("burned_count", 0)
            exhausted = t.get("exhausted_count", 0)
            avail = t.get("available_count", 0)

            val = (
                f"**Score:** `{score} pts` | {status_icon}\n"
                f"📊 Solved: **{solved}** | Passed: **{passed}** | Burned: **{burned}** | "
                f"Exhausted: **{exhausted}** | Eligible: **{avail}**"
            )
            embed.add_field(name=f"{rank_str} {name}", value=val, inline=False)

        embed.set_footer(text=f"Total Teams: {len(teams)} • Starts at 100 pts • Easy +150 | Med +250 | Hard +400 | Pass +20 to Opponents")
        embed.timestamp = discord.utils.utcnow()
        return embed

    # ---------------- USER EVENT COMMANDS (./cipher, ./answer, ./pass) ---------------- #

    @commands.command(name="cipher", aliases=["c"])
    async def cipher_cmd(self, ctx: commands.Context):
        """Fetch a random cipher question for your team."""
        team = await self._resolve_team(ctx)
        if not team:
            await ctx.send(
                embed=error_embed(
                    "Team Not Recognized",
                    "Could not associate this channel with any registered team.\n"
                    "Please ensure you are in your assigned team channel (e.g. `#inovexa`) or have your team's role.",
                )
            )
            return

        if team.get("is_disqualified") or team["score"] <= 0:
            await ctx.send(
                embed=error_embed(
                    "Team Disqualified",
                    f"⛔ **{team['name']}** is DISQUALIFIED and cannot request another cipher.",
                )
            )
            return

        if team["is_finished"]:
            await ctx.send(
                embed=info_embed(
                    "Challenge Completed",
                    f"🎉 **{team['name']}** has already solved or passed all available ciphers!\n"
                    f"Final Score: **{team['score']} points**.",
                )
            )
            return

        # Check if already has active question
        active_q = await self.db.get_active_cipher(team["id"])
        if active_q:
            embed = warning_embed(
                f"Active Cipher Pending (Cipher #{active_q['id']:02d})",
                f"Your team already has an active challenge: **Cipher #{active_q['id']:02d}** ({active_q['difficulty'].upper()} - {active_q['points']} pts)!\n\n"
                f"• Next attempt: **{active_q['active_attempts'] + 1}/4** "
                f"({4 - active_q['active_attempts']} submissions remaining)\n"
                f"• Incorrect answer penalty: **-12 points**\n"
                f"• Submit your solution: `./answer <your_answer>`\n"
                f"• Or skip this question: `./pass`",
            )
            await self._send_cipher_embed(ctx.channel, team, active_q, embed)
            return

        # Assign random cipher from remaining available queue
        q = await self.db.assign_random_cipher(team["id"])
        if not q:
            await ctx.send(
                embed=info_embed(
                    "All Ciphers Done",
                    f"🎉 No remaining questions in your queue! Your final score is **{team['score']} pts**.",
                )
            )
            await self.update_live_leaderboard(ctx.guild)
            return

        # Build challenge embed (hide title completely so answer is not spoiled)
        diff_str = q["difficulty"].upper()
        if diff_str == "EASY":
            color = discord.Color.green()
            diff_badge = f"🟢 **EASY** (+{q['points']} Points)"
        elif diff_str == "MEDIUM":
            color = discord.Color.gold()
            diff_badge = f"🟡 **MEDIUM** (+{q['points']} Points)"
        else:
            color = discord.Color.red()
            diff_badge = f"🔴 **HARD** (+{q['points']} Points)"

        embed = discord.Embed(
            title=f"🔒 Cipher Challenge #{q['id']:02d}",
            description=(
                f"**Difficulty:** {diff_badge}\n"
                f"**Category:** `{q['category']}`\n\n"
                f"🔍 *Analyze the cipher puzzle image attached below.*"
            ),
            color=color,
        )
        embed.add_field(
            name="Instructions",
            value=(
                "• Solve the puzzle and submit: `./answer <full_answer>`\n"
                "• Attempt: **1/4** (4 submissions remaining)\n"
                "• Incorrect answer penalty: **-12 points**\n"
                "• Four incorrect answers exhaust this question.\n"
                "• Skip question: `./pass` *(Burns current + 1 random question, awards +20 to opponents)*"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Team: {team['name']} • Current Balance: {team['score']} pts")

        await self._send_cipher_embed(ctx.channel, team, q, embed)
        await self.update_live_leaderboard(ctx.guild)

    def _find_image_path(self, question: dict) -> tuple:
        """Finds valid image path for the question."""
        qid = question.get("id")
        candidates = [
            question.get("image_filename"),
            f"{qid}.png",
            f"cipher_{qid}.png",
            f"{qid}.jpg",
            f"{qid}.jpeg",
        ]
        for cand in candidates:
            if not cand:
                continue
            path = os.path.join("data", "ciphers", cand)
            if os.path.exists(path):
                return path, cand
        return None, None

    async def _send_cipher_embed(self, channel, team: dict, question: dict, embed: discord.Embed):
        """Sends cipher embed with image attachment if image file exists."""
        img_path, filename = self._find_image_path(question)

        if img_path and os.path.exists(img_path):
            file = discord.File(img_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await channel.send(file=file, embed=embed)
        else:
            await channel.send(embed=embed)

    @commands.command(name="answer", aliases=["ans", "a"])
    async def answer_cmd(self, ctx: commands.Context, *, full_answer: Optional[str] = None):
        """Submit an answer for your team's active cipher."""
        team = await self._resolve_team(ctx)
        if not team:
            await ctx.send(embed=error_embed("Team Not Recognized", "Please use your team's assigned channel."))
            return

        if team.get("is_disqualified") or team["score"] <= 0:
            await ctx.send(
                embed=error_embed(
                    "Team Disqualified",
                    f"⛔ **{team['name']}** is DISQUALIFIED. Answers can no longer be submitted.",
                )
            )
            return

        if not full_answer or not full_answer.strip():
            await ctx.send(
                embed=warning_embed(
                    "Missing Answer",
                    "Please provide your answer with the command:\n`./answer <full_answer>`",
                )
            )
            return

        active_q = await self.db.get_active_cipher(team["id"])
        if not active_q:
            await ctx.send(
                embed=warning_embed(
                    "No Active Cipher",
                    "Your team does not have an active cipher question right now.\n"
                    "Type `./cipher` to draw your next question!",
                )
            )
            return

        is_correct = verify_answer(full_answer, active_q)

        updated_team = await self.db.submit_cipher_answer(
            guild_id=ctx.guild.id,
            team_id=team["id"],
            question_id=active_q["id"],
            user_id=ctx.author.id,
            submitted_answer=full_answer.strip(),
            is_correct=is_correct,
            points_reward=active_q["points"],
            submission_id=f"message:{ctx.message.id}",
        )

        if not updated_team["accepted"]:
            if updated_team.get("is_disqualified"):
                message = f"⛔ **{team['name']}** is DISQUALIFIED. This answer was not processed."
            elif updated_team.get("duplicate"):
                message = "This answer submission was already processed; no additional points were changed."
            else:
                message = "The active question changed before this answer was processed. No points were changed."
            await ctx.send(embed=warning_embed("Answer Not Processed", message))
            await self.update_live_leaderboard(ctx.guild)
            return

        if is_correct:
            embed = success_embed(
                f"CORRECT ANSWER! (+{active_q['points']} pts)",
                f"🎉 Congratulations **{team['name']}**! You solved **Cipher #{active_q['id']:02d}** "
                f"on attempt **{updated_team['attempt_number']}/4**!\n\n"
                f"💰 **Points Awarded:** `+{active_q['points']} pts`\n"
                f"🏆 **New Total Score:** `{updated_team['score']} pts`\n\n"
                f"👉 Type `./cipher` to draw your next cipher challenge!",
            )
            await ctx.send(embed=embed)
        else:
            if updated_team["is_disqualified"]:
                description = (
                    f"❌ Incorrect answer **{updated_team['attempt_number']}/4**. "
                    f"**-12 points** deducted.\n"
                    f"⏳ **Attempts remaining:** `{updated_team['attempts_remaining']}`\n"
                    f"⛔ Your score is `{updated_team['score']} pts`; your team is now **DISQUALIFIED**. "
                    "The active question was interrupted."
                )
                title = "Team Disqualified"
            elif updated_team["exhausted"]:
                description = (
                    f"❌ Incorrect answer **4/4**. **-12 points** deducted.\n"
                    "⏳ **Attempts remaining:** `0`\n"
                    f"Cipher #{active_q['id']:02d} is **EXHAUSTED** and will not return to your queue.\n"
                    f"📉 **Current Total Score:** `{updated_team['score']} pts`\n"
                    "👉 Type `./cipher` to request another question."
                )
                title = "Question Exhausted"
            else:
                description = (
                    f"❌ Incorrect answer **{updated_team['attempt_number']}/4**. "
                    f"**-12 points** deducted.\n"
                    f"📉 **Current Total Score:** `{updated_team['score']} pts`\n"
                    f"⏳ **Attempts remaining:** `{updated_team['attempts_remaining']}`\n\n"
                    f"• Try again: `./answer <full_answer>`\n"
                    f"• Or explicitly pass: `./pass`"
                )
                title = "Incorrect Answer (-12 pts)"
            embed = error_embed(title, description)
            await ctx.send(embed=embed)

        await self.update_live_leaderboard(ctx.guild)

    @commands.command(name="pass", aliases=["skip"])
    async def pass_cmd(self, ctx: commands.Context):
        """Pass the active question, burn a random unattempted question, and give +20 to opponents."""
        team = await self._resolve_team(ctx)
        if not team:
            await ctx.send(embed=error_embed("Team Not Recognized", "Please use your team's assigned channel."))
            return

        if team.get("is_disqualified") or team["score"] <= 0:
            await ctx.send(
                embed=error_embed(
                    "Team Disqualified",
                    f"⛔ **{team['name']}** is DISQUALIFIED and cannot pass questions.",
                )
            )
            return

        active_q = await self.db.get_active_cipher(team["id"])
        if not active_q:
            await ctx.send(
                embed=warning_embed(
                    "No Active Cipher",
                    "There is no active cipher to pass! Type `./cipher` to request a question.",
                )
            )
            return

        result = await self.db.pass_cipher_question(
            guild_id=ctx.guild.id,
            team_id=team["id"],
            user_id=ctx.author.id,
            opposition_bonus=20,
        )
        if not result:
            await ctx.send(embed=warning_embed("Pass Not Processed", "The active question changed or your team was disqualified."))
            await self.update_live_leaderboard(ctx.guild)
            return

        passed_q = result["passed_question"]
        burned_q = result["burned_question"]
        updated_team = result["team"]

        desc = (
            f"**{team['name']}** chose to pass on **Cipher #{passed_q['id']:02d}**.\n\n"
            f"🚫 **Passed Question:** Cipher #{passed_q['id']:02d} ({passed_q['difficulty'].upper()}) — *Removed permanently*\n"
        )

        if burned_q:
            desc += f"🔥 **Collateral Burn:** Cipher #{burned_q['id']:02d} ({burned_q['difficulty'].upper()}) was randomly eliminated from your pool!\n"
        else:
            desc += "🔥 **Collateral Burn:** No remaining questions in queue to burn.\n"

        desc += (
            f"\n🎁 **Opposition Buff:** All other teams have received **+20 points**!\n"
            f"📊 **Your Current Score:** `{updated_team['score']} pts`\n\n"
            f"👉 Type `./cipher` when your team is ready for your next puzzle."
        )

        embed = discord.Embed(
            title="⏭️ Question Passed & Double Burned",
            description=desc,
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"Team: {team['name']} • Score: {updated_team['score']} pts")
        await ctx.send(embed=embed)

        await self.update_live_leaderboard(ctx.guild)

    # ---------------- ADMIN COMMANDS (./reset, ./setup_event, ./leaderboard) ---------------- #

    @commands.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def reset_cmd(self, ctx: commands.Context, score: Optional[int] = 100):
        """Reset the competition to starting state (default: 100 points, all queues restored)."""
        await self.db.reset_cipher_event(ctx.guild.id, reset_score=score)
        embed = success_embed(
            "Event Reset Successfully",
            f"All 13 teams have been reset to **{score} points**.\n"
            f"• All question queues have been restored to 16 available ciphers.\n"
            f"• All active questions have been cleared.\n"
            f"• Live leaderboard updated.",
        )
        await ctx.send(embed=embed)
        await self.update_live_leaderboard(ctx.guild)

    @commands.command(name="admin_room", aliases=["setadminroom"])
    @commands.has_permissions(administrator=True)
    async def set_admin_room_cmd(self, ctx: commands.Context):
        """Designate the current channel as the Admin Room with the Live Leaderboard."""
        await self.db.set_cipher_config(ctx.guild.id, admin_channel_id=ctx.channel.id)
        embed = success_embed(
            "Admin Room Registered",
            f"This channel {ctx.channel.mention} is now designated as the Admin Room.\n"
            f"Publishing the live leaderboard now...",
        )
        await ctx.send(embed=embed)
        await self.update_live_leaderboard(ctx.guild)

    @commands.command(name="leaderboard", aliases=["lb"])
    async def leaderboard_cmd(self, ctx: commands.Context):
        """Display the current cipher tournament leaderboard."""
        leaderboard = await self.db.get_cipher_leaderboard(ctx.guild.id)
        embed = self._build_leaderboard_embed(ctx.guild, leaderboard)
        await ctx.send(embed=embed)

    @commands.command(name="setup_event")
    @commands.has_permissions(administrator=True)
    async def setup_event_cmd(self, ctx: commands.Context, create_channels: Optional[bool] = False):
        """
        Initializes the 13 teams and optionally creates private channels/roles.
        Usage: `./setup_event` or `./setup_event true`
        """
        teams = await self.db.ensure_cipher_event(ctx.guild.id)
        msg_lines = [
            f"Registered {len(teams)} teams. Existing team scores and mappings are preserved.",
            "New teams: `Team Mavericks` and `The Way Makers`.",
        ]

        if create_channels and ctx.guild.me.guild_permissions.manage_channels:
            # Create category
            cat_name = "🏆 CIPHER EVENT 🏆"
            category = discord.utils.get(ctx.guild.categories, name=cat_name)
            if not category:
                category = await ctx.guild.create_category(cat_name)

            for t in teams:
                # Format channel slug
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", t["name"]).strip("-").lower()
                existing_chan = discord.utils.get(ctx.guild.text_channels, name=slug)
                if not existing_chan:
                    overwrites = {
                        ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                        ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    }
                    chan = await ctx.guild.create_text_channel(slug, category=category, overwrites=overwrites)
                    await self.db.link_cipher_team_channel(ctx.guild.id, t["name"], chan.id)
                    msg_lines.append(f"• Created channel: {chan.mention} -> `{t['name']}`")
                else:
                    await self.db.link_cipher_team_channel(ctx.guild.id, t["name"], existing_chan.id)
                    msg_lines.append(f"• Linked existing channel: {existing_chan.mention} -> `{t['name']}`")

        embed = success_embed("Cipher Event Setup Complete", "\n".join(msg_lines))
        await ctx.send(embed=embed)
        await self.update_live_leaderboard(ctx.guild)

    # ---------------- SLASH COMMANDS (/cipher, /answer, /pass, /leaderboard) ---------------- #

    @app_commands.command(name="cipher", description="Request your team's next cipher challenge")
    @app_commands.guild_only()
    async def cipher_slash(self, interaction: discord.Interaction):
        team = await self._resolve_team(interaction)
        if not team:
            await interaction.response.send_message(
                embed=error_embed("Team Not Recognized", "Please use your assigned team channel or ensure you have your team role."),
                ephemeral=True,
            )
            return

        if team.get("is_disqualified") or team["score"] <= 0:
            await interaction.response.send_message(
                embed=error_embed("Team Disqualified", f"⛔ **{team['name']}** is DISQUALIFIED and cannot request another cipher."),
                ephemeral=True,
            )
            return

        if team["is_finished"]:
            await interaction.response.send_message(
                embed=info_embed("Finished", f"🎉 **{team['name']}** has finished all questions with {team['score']} pts!"),
            )
            return

        active_q = await self.db.get_active_cipher(team["id"])
        if active_q:
            embed = warning_embed(
                f"Active Cipher Pending (Cipher #{active_q['id']:02d})",
                f"Your team already has an active puzzle: **Cipher #{active_q['id']:02d}** ({active_q['difficulty'].upper()} - {active_q['points']} pts)!\n"
                f"• Next attempt: **{active_q['active_attempts'] + 1}/4** "
                f"({4 - active_q['active_attempts']} submissions remaining)\n"
                f"• Incorrect answer penalty: **-12 points**\n"
                f"• Submit answer: `/answer full_answer:<text>` or `./answer <text>`\n"
                f"• Pass: `/pass` or `./pass`",
            )
            await interaction.response.send_message(embed=embed)
            return

        q = await self.db.assign_random_cipher(team["id"])
        if not q:
            await interaction.response.send_message(
                embed=info_embed("Complete", f"🎉 No more questions available! Final Score: **{team['score']} pts**."),
            )
            await self.update_live_leaderboard(interaction.guild)
            return

        diff_str = q["difficulty"].upper()
        color = discord.Color.green() if diff_str == "EASY" else (discord.Color.gold() if diff_str == "MEDIUM" else discord.Color.red())

        embed = discord.Embed(
            title=f"🔒 Cipher Challenge #{q['id']:02d}",
            description=(
                f"**Difficulty:** {diff_str} (+{q['points']} pts)\n"
                f"**Category:** `{q['category']}`\n\n"
                "**Attempt:** 1/4 (4 submissions remaining)\n"
                "**Incorrect answer penalty:** -12 points\n"
                "Four incorrect answers exhaust this question.\n\n"
                f"🔍 *Analyze the cipher puzzle image attached below.*"
            ),
            color=color,
        )
        embed.set_footer(text=f"Team: {team['name']} • Score: {team['score']} pts")

        img_path, filename = self._find_image_path(q)
        if img_path and os.path.exists(img_path):
            file = discord.File(img_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
            await interaction.response.send_message(file=file, embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

        await self.update_live_leaderboard(interaction.guild)

    @app_commands.command(name="answer", description="Submit your answer to the active cipher question")
    @app_commands.describe(full_answer="The full solution to the cipher")
    @app_commands.guild_only()
    async def answer_slash(self, interaction: discord.Interaction, full_answer: str):
        team = await self._resolve_team(interaction)
        if not team:
            await interaction.response.send_message(embed=error_embed("Team Not Recognized", "Please use your team channel."), ephemeral=True)
            return

        if team.get("is_disqualified") or team["score"] <= 0:
            await interaction.response.send_message(
                embed=error_embed("Team Disqualified", f"⛔ **{team['name']}** is DISQUALIFIED. Answers can no longer be submitted."),
                ephemeral=True,
            )
            return

        active_q = await self.db.get_active_cipher(team["id"])
        if not active_q:
            await interaction.response.send_message(
                embed=warning_embed("No Active Cipher", "No cipher in progress. Run `/cipher` or `./cipher` first!"),
                ephemeral=True,
            )
            return

        is_correct = verify_answer(full_answer, active_q)

        updated_team = await self.db.submit_cipher_answer(
            guild_id=interaction.guild.id,
            team_id=team["id"],
            question_id=active_q["id"],
            user_id=interaction.user.id,
            submitted_answer=full_answer.strip(),
            is_correct=is_correct,
            points_reward=active_q["points"],
            submission_id=f"interaction:{interaction.id}",
        )

        if not updated_team["accepted"]:
            if updated_team.get("is_disqualified"):
                message = f"⛔ **{team['name']}** is DISQUALIFIED. This answer was not processed."
            elif updated_team.get("duplicate"):
                message = "This answer submission was already processed; no additional points were changed."
            else:
                message = "The active question changed before this answer was processed. No points were changed."
            await interaction.response.send_message(embed=warning_embed("Answer Not Processed", message), ephemeral=True)
            await self.update_live_leaderboard(interaction.guild)
            return

        if is_correct:
            embed = success_embed(
                f"CORRECT ANSWER! (+{active_q['points']} pts)",
                f"🎉 Cracked **Cipher #{active_q['id']:02d}** on attempt "
                f"**{updated_team['attempt_number']}/4**!\n"
                f"New Score: **{updated_team['score']} pts**.",
            )
        else:
            if updated_team["is_disqualified"]:
                title = "Team Disqualified"
                description = (
                    f"❌ Incorrect answer **{updated_team['attempt_number']}/4**. **-12 points** deducted.\n"
                    f"⏳ **Attempts remaining:** `{updated_team['attempts_remaining']}`\n"
                    f"⛔ Your score is `{updated_team['score']} pts`; your team is now **DISQUALIFIED**. "
                    "The active question was interrupted."
                )
            elif updated_team["exhausted"]:
                title = "Question Exhausted"
                description = (
                    "❌ Incorrect answer **4/4**. **-12 points** deducted.\n"
                    "⏳ **Attempts remaining:** `0`\n"
                    f"Cipher #{active_q['id']:02d} is **EXHAUSTED** and will not return to your queue.\n"
                    f"Score: `{updated_team['score']} pts`. Type `/cipher` or `./cipher` for another question."
                )
            else:
                title = "Incorrect Answer (-12 pts)"
                description = (
                    f"❌ Incorrect answer **{updated_team['attempt_number']}/4**. **-12 points** deducted.\n"
                    f"Score: `{updated_team['score']} pts` | "
                    f"Attempts remaining: **{updated_team['attempts_remaining']}**."
                )
            embed = error_embed(
                title,
                description,
            )

        await interaction.response.send_message(embed=embed)
        await self.update_live_leaderboard(interaction.guild)

    @app_commands.command(name="pass", description="Pass the current question (+20 pts to opponents, burns current + 1 random)")
    @app_commands.guild_only()
    async def pass_slash(self, interaction: discord.Interaction):
        team = await self._resolve_team(interaction)
        if not team:
            await interaction.response.send_message(embed=error_embed("Team Not Recognized", "Please use your team channel."), ephemeral=True)
            return

        if team.get("is_disqualified") or team["score"] <= 0:
            await interaction.response.send_message(
                embed=error_embed("Team Disqualified", f"⛔ **{team['name']}** is DISQUALIFIED and cannot pass questions."),
                ephemeral=True,
            )
            return

        active_q = await self.db.get_active_cipher(team["id"])
        if not active_q:
            await interaction.response.send_message(
                embed=warning_embed("No Active Cipher", "No active question to pass!"),
                ephemeral=True,
            )
            return

        result = await self.db.pass_cipher_question(
            guild_id=interaction.guild.id,
            team_id=team["id"],
            user_id=interaction.user.id,
            opposition_bonus=20,
        )
        if not result:
            await interaction.response.send_message(
                embed=warning_embed("Pass Not Processed", "The active question changed or your team was disqualified."),
                ephemeral=True,
            )
            await self.update_live_leaderboard(interaction.guild)
            return

        passed_q = result["passed_question"]
        burned_q = result["burned_question"]
        updated_team = result["team"]

        burn_summary = (
            f"• Burned: Cipher #{burned_q['id']:02d} ({burned_q['difficulty'].upper()})\n"
            if burned_q else "• No additional eligible question was available to burn.\n"
        )
        desc = (
            f"**{team['name']}** passed Cipher #{passed_q['id']:02d}!\n"
            f"{burn_summary}"
            "• Opponents received: **+20 points each**\n"
            f"• Team Score: **{updated_team['score']} pts**"
        )
        embed = discord.Embed(title="⏭️ Cipher Passed", description=desc, color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)
        await self.update_live_leaderboard(interaction.guild)

    @app_commands.command(name="leaderboard", description="View current cipher competition leaderboard")
    @app_commands.guild_only()
    async def leaderboard_slash(self, interaction: discord.Interaction):
        leaderboard = await self.db.get_cipher_leaderboard(interaction.guild.id)
        embed = self._build_leaderboard_embed(interaction.guild, leaderboard)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CipherEventCog(bot))
