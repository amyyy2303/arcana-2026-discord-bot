import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Literal
from utils.embeds import success_embed, error_embed, info_embed
from utils.json_utils import (
    validate_json,
    format_json,
    minify_json,
    csv_to_json,
    json_to_csv,
    yaml_to_json,
    json_to_yaml,
    python_dict_to_json,
    prepare_discord_payload,
)


class JsonModal(discord.ui.Modal, title="JSON Formatter & Validator"):
    """Interactive modal for pasting multiline JSON directly."""

    raw_json = discord.ui.TextInput(
        label="Raw JSON Data",
        style=discord.TextStyle.paragraph,
        placeholder='{"key": "value", "list": [1, 2, 3]}',
        required=True,
        max_length=4000,
    )

    indent = discord.ui.TextInput(
        label="Indentation (default 2)",
        style=discord.TextStyle.short,
        placeholder="2",
        required=False,
        default="2",
        max_length=2,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            indent_val = int(self.indent.value.strip()) if self.indent.value else 2
        except ValueError:
            indent_val = 2

        raw_text = self.raw_json.value
        is_valid, msg, stats = validate_json(raw_text)
        if not is_valid:
            await interaction.response.send_message(
                embed=error_embed("Invalid JSON Syntax", msg),
                ephemeral=True,
            )
            return

        ok, formatted = format_json(raw_text, indent=indent_val)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Formatting Failed", formatted), ephemeral=True)
            return

        body, file_att = prepare_discord_payload(formatted, filename="formatted.json", syntax="json")
        summary = (
            f"✅ **Valid JSON** (Root: `{stats.get('root_type')}`, "
            f"Depth: `{stats.get('max_depth')}`, Size: `{stats.get('byte_size')} bytes`)\n{body}"
        )

        if file_att:
            await interaction.response.send_message(summary, file=file_att, ephemeral=True)
        else:
            await interaction.response.send_message(summary, ephemeral=True)


class JsonToolsCog(commands.Cog, name="JSON Tools"):
    """Validation, formatting, and conversion utilities for JSON and structured data."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    json_group = app_commands.Group(name="json", description="JSON validation, formatting, and data conversion tools")

    async def _extract_content(
        self, interaction: discord.Interaction, text: Optional[str], file: Optional[discord.Attachment]
    ) -> Optional[str]:
        """Extracts string content from either text parameter or uploaded file attachment."""
        if file:
            try:
                # 5MB limit check
                if file.size > 5 * 1024 * 1024:
                    await interaction.response.send_message(
                        embed=error_embed("File Too Large", "Uploaded file exceeds the 5MB limit."),
                        ephemeral=True,
                    )
                    return None
                data = await file.read()
                return data.decode("utf-8")
            except UnicodeDecodeError:
                await interaction.response.send_message(
                    embed=error_embed("Encoding Error", "Uploaded file could not be decoded as UTF-8 text."),
                    ephemeral=True,
                )
                return None
            except Exception as e:
                await interaction.response.send_message(
                    embed=error_embed("Read Error", f"Failed to read attached file: {str(e)}"),
                    ephemeral=True,
                )
                return None

        if text and text.strip():
            return text.strip()

        await interaction.response.send_message(
            embed=error_embed("Missing Input", "Please provide either the `text` option or upload a `file` attachment."),
            ephemeral=True,
        )
        return None

    # ---------------- VALIDATE ---------------- #

    @json_group.command(name="validate", description="Validate JSON syntax and inspect data structure")
    @app_commands.describe(
        text="Raw JSON text to validate",
        file="JSON file attachment to validate",
    )
    async def json_validate(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        file: Optional[discord.Attachment] = None,
    ):
        content = await self._extract_content(interaction, text, file)
        if content is None:
            return

        is_valid, msg, stats = validate_json(content)
        if not is_valid:
            embed = error_embed("Invalid JSON", msg)
            await interaction.response.send_message(embed=embed)
            return

        embed = success_embed("JSON is Valid")
        embed.add_field(name="📦 Root Structure", value=f"`{stats.get('root_type')}`", inline=True)
        if "key_count" in stats:
            embed.add_field(name="🔑 Keys Count", value=f"`{stats['key_count']}`", inline=True)
        elif "item_count" in stats:
            embed.add_field(name="🔢 Item Count", value=f"`{stats['item_count']}`", inline=True)

        embed.add_field(name="📐 Nesting Depth", value=f"`{stats.get('max_depth')}` levels", inline=True)
        embed.add_field(name="💾 Data Size", value=f"`{stats.get('byte_size')} bytes`", inline=True)

        await interaction.response.send_message(embed=embed)

    # ---------------- FORMAT / PRETTIFY ---------------- #

    @json_group.command(name="format", description="Format and beautify JSON with custom indentation")
    @app_commands.describe(
        text="Raw JSON string",
        file="JSON file attachment",
        indent="Indentation spaces (1-8, default: 2)",
        sort_keys="Alphabetize dictionary keys (default: False)",
    )
    async def json_format(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        file: Optional[discord.Attachment] = None,
        indent: app_commands.Range[int, 1, 8] = 2,
        sort_keys: bool = False,
    ):
        content = await self._extract_content(interaction, text, file)
        if content is None:
            return

        ok, result = format_json(content, indent=indent, sort_keys=sort_keys)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Formatting Error", result))
            return

        body, file_att = prepare_discord_payload(result, filename="formatted.json", syntax="json")
        if file_att:
            await interaction.response.send_message(body, file=file_att)
        else:
            await interaction.response.send_message(body)

    # ---------------- MINIFY ---------------- #

    @json_group.command(name="minify", description="Minify JSON into a single compact line")
    @app_commands.describe(
        text="Raw JSON string",
        file="JSON file attachment",
    )
    async def json_minify(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        file: Optional[discord.Attachment] = None,
    ):
        content = await self._extract_content(interaction, text, file)
        if content is None:
            return

        ok, result = minify_json(content)
        if not ok:
            await interaction.response.send_message(embed=error_embed("Minification Error", result))
            return

        body, file_att = prepare_discord_payload(result, filename="minified.json", syntax="json")
        if file_att:
            await interaction.response.send_message(body, file=file_att)
        else:
            await interaction.response.send_message(body)

    # ---------------- CONVERT ---------------- #

    @json_group.command(name="convert", description="Convert between JSON and CSV, YAML, or Python literal dicts")
    @app_commands.describe(
        conversion="Conversion direction",
        text="Source data text",
        file="Source data file attachment",
        indent="Indentation spaces for JSON output (1-8, default: 2)",
    )
    async def json_convert(
        self,
        interaction: discord.Interaction,
        conversion: Literal[
            "csv_to_json",
            "json_to_csv",
            "yaml_to_json",
            "json_to_yaml",
            "pydict_to_json",
        ],
        text: Optional[str] = None,
        file: Optional[discord.Attachment] = None,
        indent: app_commands.Range[int, 1, 8] = 2,
    ):
        content = await self._extract_content(interaction, text, file)
        if content is None:
            return

        if conversion == "csv_to_json":
            ok, output = csv_to_json(content, indent=indent)
            filename, syntax = "converted.json", "json"
        elif conversion == "json_to_csv":
            ok, output = json_to_csv(content)
            filename, syntax = "converted.csv", "csv"
        elif conversion == "yaml_to_json":
            ok, output = yaml_to_json(content, indent=indent)
            filename, syntax = "converted.json", "json"
        elif conversion == "json_to_yaml":
            ok, output = json_to_yaml(content)
            filename, syntax = "converted.yaml", "yaml"
        elif conversion == "pydict_to_json":
            ok, output = python_dict_to_json(content, indent=indent)
            filename, syntax = "converted.json", "json"
        else:
            await interaction.response.send_message(embed=error_embed("Unsupported Conversion", "Unknown conversion type."))
            return

        if not ok:
            await interaction.response.send_message(embed=error_embed("Conversion Failed", output))
            return

        body, file_att = prepare_discord_payload(output, filename=filename, syntax=syntax)
        prefix = f"Converted from **{conversion.replace('_', ' ').upper()}**:\n"
        if file_att:
            await interaction.response.send_message(prefix + body, file=file_att)
        else:
            await interaction.response.send_message(prefix + body)

    # ---------------- MODAL INPUT ---------------- #

    @json_group.command(name="modal", description="Open an interactive popup window to format & validate JSON")
    async def json_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(JsonModal())


async def setup(bot: commands.Bot):
    await bot.add_cog(JsonToolsCog(bot))

