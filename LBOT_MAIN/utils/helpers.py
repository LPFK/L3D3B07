"""
Utility functions - Embeds, pagination, time formatting, etc.
"""

import discord
from discord.ext import commands
from datetime import datetime, timedelta
from typing import Optional, List, Any
import asyncio
import re
import humanize


# ==================== EMBED HELPERS ====================

def create_embed(
    title: str = None,
    description: str = None,
    color: discord.Color = discord.Color.blurple(),
    footer: str = None,
    thumbnail: str = None,
    image: str = None,
    author: discord.Member = None,
    fields: list[tuple[str, str, bool]] = None
) -> discord.Embed:
    """Create a standardized embed"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if author:
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    
    return embed


def success_embed(message: str, title: str = "Succès") -> discord.Embed:
    """Create a success embed"""
    return create_embed(
        title=f"✅ {title}",
        description=message,
        color=discord.Color.green()
    )


def error_embed(message: str, title: str = "Erreur") -> discord.Embed:
    """Create an error embed"""
    return create_embed(
        title=f"❌ {title}",
        description=message,
        color=discord.Color.red()
    )


def warning_embed(message: str, title: str = "Attention") -> discord.Embed:
    """Create a warning embed"""
    return create_embed(
        title=f"⚠️ {title}",
        description=message,
        color=discord.Color.orange()
    )


def info_embed(message: str, title: str = "Information") -> discord.Embed:
    """Create an info embed"""
    return create_embed(
        title=f"ℹ️ {title}",
        description=message,
        color=discord.Color.blue()
    )


# ==================== PAGINATION ====================

class Paginator(discord.ui.View):
    """Paginated embed view"""
    
    def __init__(self, pages: List[discord.Embed], author_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.current_page = 0
        self.message: Optional[discord.Message] = None
        self._update_buttons()
    
    def _update_buttons(self):
        self.first_page.disabled = self.current_page == 0
        self.prev_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= len(self.pages) - 1
        self.last_page.disabled = self.current_page >= len(self.pages) - 1
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Tu ne peux pas utiliser ces boutons.", ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
    
    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
    
    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        self.stop()
    
    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
    
    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)


class ConfirmView(discord.ui.View):
    """Confirmation dialog view"""
    
    def __init__(self, author_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: Optional[bool] = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Tu ne peux pas utiliser ces boutons.", ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        await interaction.response.defer()
        self.stop()
    
    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.defer()
        self.stop()


# ==================== TIME HELPERS ====================

def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration string like '1d2h30m' into a timedelta
    Supports: s (seconds), m (minutes), h (hours), d (days), w (weeks)
    """
    pattern = r'(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
    match = re.fullmatch(pattern, duration_str.lower().replace(' ', ''))
    
    if not match or not any(match.groups()):
        return None
    
    weeks = int(match.group(1) or 0)
    days = int(match.group(2) or 0)
    hours = int(match.group(3) or 0)
    minutes = int(match.group(4) or 0)
    seconds = int(match.group(5) or 0)
    
    return timedelta(
        weeks=weeks,
        days=days,
        hours=hours,
        minutes=minutes,
        seconds=seconds
    )


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable string"""
    if seconds < 60:
        return f"{seconds}s"
    
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    
    parts = []
    if days:
        parts.append(f"{days}j")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not days:
        parts.append(f"{seconds}s")
    
    return " ".join(parts)


def format_relative_time(timestamp: float) -> str:
    """Format a timestamp as relative time (e.g., 'il y a 5 minutes')"""
    dt = datetime.fromtimestamp(timestamp)
    return humanize.naturaltime(dt, when=datetime.now())


def format_datetime(timestamp: float) -> str:
    """Format a timestamp as a readable date/time"""
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%d/%m/%Y à %H:%M")


# ==================== XP/LEVEL CALCULATIONS ====================

def xp_for_level(level: int) -> int:
    """Calculate total XP required for a level (exponential curve)"""
    return int(100 * (level ** 1.5))


def level_from_xp(xp: int) -> int:
    """Calculate level from total XP"""
    level = 0
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def xp_progress(xp: int, level: int) -> tuple[int, int]:
    """Return (current_xp_in_level, xp_needed_for_next_level)"""
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    return xp - current_level_xp, next_level_xp - current_level_xp


def progress_bar(current: int, total: int, length: int = 10) -> str:
    """Create a text progress bar"""
    filled = int(length * current / total) if total > 0 else 0
    empty = length - filled
    return "█" * filled + "░" * empty


# ==================== MESSAGE FORMATTING ====================

def format_message(template: str, **kwargs) -> str:
    """
    Format a message template with placeholders
    Supported: {user}, {user.mention}, {user.name}, {user.id}, {server}, {level}, {xp}, etc.
    """
    replacements = {
        "{user}": str(kwargs.get("user", "")),
        "{user.mention}": kwargs.get("user", discord.Object(0)).mention if hasattr(kwargs.get("user"), "mention") else "",
        "{user.name}": getattr(kwargs.get("user"), "name", ""),
        "{user.id}": str(getattr(kwargs.get("user"), "id", "")),
        "{server}": str(kwargs.get("server", kwargs.get("guild", ""))),
        "{server.name}": getattr(kwargs.get("guild"), "name", ""),
        "{level}": str(kwargs.get("level", "")),
        "{xp}": str(kwargs.get("xp", "")),
        "{rank}": str(kwargs.get("rank", "")),
        "{balance}": str(kwargs.get("balance", "")),
        "{amount}": str(kwargs.get("amount", "")),
        "{prize}": str(kwargs.get("prize", "")),
        "{count}": str(kwargs.get("count", "")),
        "{channel}": str(kwargs.get("channel", "")),
        "{role}": str(kwargs.get("role", "")),
    }
    
    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, str(value))
    
    return result


# ==================== PERMISSION CHECKS ====================

def is_admin():
    """Check if user has admin permissions"""
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


def is_mod():
    """Check if user has moderation permissions"""
    async def predicate(ctx: commands.Context) -> bool:
        perms = ctx.author.guild_permissions
        return perms.administrator or perms.manage_guild or perms.ban_members or perms.kick_members
    return commands.check(predicate)


# ==================== MISC HELPERS ====================

def truncate(text: str, max_length: int = 1024, suffix: str = "...") -> str:
    """Truncate text to a maximum length"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def chunk_list(lst: list, chunk_size: int) -> list[list]:
    """Split a list into chunks"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


async def safe_send(channel: discord.TextChannel, content: str = None, **kwargs) -> Optional[discord.Message]:
    """Safely send a message, handling permission errors"""
    try:
        return await channel.send(content, **kwargs)
    except (discord.Forbidden, discord.HTTPException):
        return None


async def safe_delete(message: discord.Message) -> bool:
    """Safely delete a message, handling permission errors"""
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.HTTPException, discord.NotFound):
        return False
