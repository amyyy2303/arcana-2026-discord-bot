import discord
from typing import Optional


def success_embed(title: str, description: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"✅ {title}",
        description=description,
        color=discord.Color.green(),
    )
    return embed


def error_embed(title: str, description: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=discord.Color.red(),
    )
    return embed


def info_embed(title: str, description: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"ℹ️ {title}",
        description=description,
        color=discord.Color.blue(),
    )
    return embed


def warning_embed(title: str, description: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚠️ {title}",
        description=description,
        color=discord.Color.gold(),
    )
    return embed

