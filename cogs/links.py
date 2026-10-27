import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from database.db import get_db
from utils.embeds import success_embed, error_embed, info_embed


class LinkCog(commands.Cog, name="Links"):
    """Link creation, tagging, category organization, and search."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = get_db()

    link_group = app_commands.Group(name="link", description="Manage and retrieve saved links and bookmarks")

    # ---------------- ADD LINK ---------------- #

    @link_group.command(name="add", description="Save and categorize a new link")
    @app_commands.describe(
        url="Web address (e.g. https://docs.python.org)",
        title="Descriptive title for the bookmark",
        category="Category or folder name (e.g. docs, tools, design; default: general)",
        tags="Comma-separated tags for easy search (e.g. python, api, guide)",
        description="Optional notes or details about the link",
    )
    @app_commands.guild_only()
    async def link_add(
        self,
        interaction: discord.Interaction,
        url: str,
        title: str,
        category: Optional[str] = "general",
        tags: Optional[str] = "",
        description: Optional[str] = "",
    ):
        clean_url = url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            clean_url = "https://" + clean_url

        if len(clean_url) > 2000:
            await interaction.response.send_message(
                embed=error_embed("URL Too Long", "URL exceeds maximum supported length."),
                ephemeral=True,
            )
            return

        clean_cat = (category or "general").strip().lower()
        link_id = await self.db.add_link(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            url=clean_url,
            title=title.strip(),
            category=clean_cat,
            tags=tags or "",
            description=description or "",
        )

        embed = success_embed(
            title=f"Link #{link_id} Saved: {title.strip()}",
            description=f"🔗 [{title.strip()}]({clean_url})\n\n{description or ''}",
        )
        embed.add_field(name="📁 Category", value=f"`{clean_cat}`", inline=True)
        if tags:
            tag_badges = " ".join(f"`#{t.strip()}`" for t in tags.split(",") if t.strip())
            embed.add_field(name="🏷️ Tags", value=tag_badges, inline=True)
        embed.add_field(name="👤 Added By", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"Retrieve anytime with /link get {link_id} or /link search")

        await interaction.response.send_message(embed=embed)

    # ---------------- SEARCH LINKS ---------------- #

    @link_group.command(name="search", description="Search saved links by keywords, tags, or category")
    @app_commands.describe(query="Search keyword matching title, tags, or description", category="Filter by category")
    @app_commands.guild_only()
    async def link_search(
        self,
        interaction: discord.Interaction,
        query: str,
        category: Optional[str] = None,
    ):
        results = await self.db.search_links(interaction.guild.id, query=query, category=category, limit=15)
        if not results:
            cat_note = f" in category `{category}`" if category else ""
            await interaction.response.send_message(
                embed=info_embed("No Links Found", f"No saved links matched `{query}`{cat_note}."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"Search Results for: \"{query}\" ({len(results)})",
            color=discord.Color.gold(),
        )

        for item in results:
            tag_str = f" `[{item['tags']}]`" if item["tags"] else ""
            desc_str = f"\n_{item['description'][:90]}..._" if item["description"] else ""
            embed.add_field(
                name=f"#{item['id']} {item['title']}",
                value=f"🔗 [Open Link]({item['url']}) • 📁 `{item['category']}`{tag_str}{desc_str}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ---------------- LIST LINKS ---------------- #

    @link_group.command(name="list", description="List links in this server by category")
    @app_commands.describe(category="Filter links by category (leave blank to see recent)")
    @app_commands.guild_only()
    async def link_list(self, interaction: discord.Interaction, category: Optional[str] = None):
        results = await self.db.search_links(interaction.guild.id, query="", category=category, limit=20)
        if not results:
            msg = f"No links found in category `{category}`." if category else "No links have been saved in this server yet."
            await interaction.response.send_message(
                embed=info_embed("No Links Found", msg),
                ephemeral=True,
            )
            return

        cat_title = f"Category: {category.lower()}" if category else "Recent Links"
        embed = discord.Embed(
            title=f"Saved Bookmarks ({cat_title})",
            color=discord.Color.blue(),
        )

        for item in results:
            tag_str = f" `[{item['tags']}]`" if item["tags"] else ""
            embed.add_field(
                name=f"#{item['id']} • {item['title']}",
                value=f"🔗 [Link]({item['url']}) | 📁 `{item['category']}`{tag_str}",
                inline=False,
            )

        embed.set_footer(text="Use /link get <id> to view full details.")
        await interaction.response.send_message(embed=embed)

    # ---------------- LIST CATEGORIES ---------------- #

    @link_group.command(name="categories", description="List all link categories and bookmark counts")
    @app_commands.guild_only()
    async def link_categories(self, interaction: discord.Interaction):
        categories = await self.db.list_categories(interaction.guild.id)
        if not categories:
            await interaction.response.send_message(
                embed=info_embed("No Categories", "No bookmarks saved yet. Use `/link add` to create one!"),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"Bookmark Categories ({len(categories)})",
            color=discord.Color.purple(),
        )

        total_links = sum(c["count"] for c in categories)
        embed.description = f"**Total Saved Links:** {total_links}\n\n"
        for c in categories:
            embed.description += f"• 📁 **`{c['category']}`**: {c['count']} link(s)\n"

        embed.set_footer(text="Filter with /link list <category>")
        await interaction.response.send_message(embed=embed)

    # ---------------- GET LINK ---------------- #

    @link_group.command(name="get", description="Get full details for a specific saved link")
    @app_commands.describe(id="ID of the link")
    @app_commands.guild_only()
    async def link_get(self, interaction: discord.Interaction, id: int):
        link = await self.db.get_link(id, interaction.guild.id)
        if not link:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No link found with ID `#{id}`."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"Bookmark #{link['id']}: {link['title']}",
            url=link["url"],
            color=discord.Color.green(),
        )
        embed.description = f"🔗 **Direct URL:** {link['url']}\n\n" + (link["description"] or "_No description provided._")
        embed.add_field(name="📁 Category", value=f"`{link['category']}`", inline=True)
        if link["tags"]:
            tag_badges = " ".join(f"`#{t.strip()}`" for t in link["tags"].split(",") if t.strip())
            embed.add_field(name="🏷️ Tags", value=tag_badges, inline=True)
        embed.add_field(name="👤 Added By", value=f"<@{link['user_id']}>", inline=True)
        embed.add_field(name="📅 Added On", value=str(link["created_at"]), inline=True)

        await interaction.response.send_message(embed=embed)

    # ---------------- EDIT LINK ---------------- #

    @link_group.command(name="edit", description="Edit an existing link's details")
    @app_commands.describe(
        id="ID of the link to edit",
        title="New title",
        url="New URL",
        category="New category",
        tags="New tags",
        description="New description",
    )
    @app_commands.guild_only()
    async def link_edit(
        self,
        interaction: discord.Interaction,
        id: int,
        title: Optional[str] = None,
        url: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        description: Optional[str] = None,
    ):
        link = await self.db.get_link(id, interaction.guild.id)
        if not link:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No link found with ID `#{id}`."),
                ephemeral=True,
            )
            return

        is_admin = interaction.user.guild_permissions.manage_messages or interaction.user == interaction.guild.owner
        if link["user_id"] != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                embed=error_embed("Permission Denied", "You can only edit links that you created."),
                ephemeral=True,
            )
            return

        clean_url = url.strip() if url else None
        if clean_url and not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            clean_url = "https://" + clean_url

        updated = await self.db.update_link(
            link_id=id,
            guild_id=interaction.guild.id,
            title=title,
            url=clean_url,
            category=category,
            tags=tags,
            description=description,
        )

        if updated:
            await interaction.response.send_message(
                embed=success_embed("Link Updated", f"Link `#{id}` has been updated successfully.")
            )
        else:
            await interaction.response.send_message(
                embed=info_embed("No Changes", "No fields were provided to update."),
                ephemeral=True,
            )

    # ---------------- DELETE LINK ---------------- #

    @link_group.command(name="delete", description="Delete a saved link")
    @app_commands.describe(id="ID of the link to delete")
    @app_commands.guild_only()
    async def link_delete(self, interaction: discord.Interaction, id: int):
        link = await self.db.get_link(id, interaction.guild.id)
        if not link:
            await interaction.response.send_message(
                embed=error_embed("Not Found", f"No link found with ID `#{id}`."),
                ephemeral=True,
            )
            return

        is_admin = interaction.user.guild_permissions.manage_messages or interaction.user == interaction.guild.owner
        if link["user_id"] != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                embed=error_embed("Permission Denied", "You can only delete links that you created."),
                ephemeral=True,
            )
            return

        deleted = await self.db.delete_link(id, interaction.guild.id)
        if deleted:
            await interaction.response.send_message(
                embed=success_embed("Link Deleted", f"Link `#{id}` ({link['title']}) was deleted.")
            )
        else:
            await interaction.response.send_message(
                embed=error_embed("Error", "Could not delete link."),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(LinkCog(bot))

