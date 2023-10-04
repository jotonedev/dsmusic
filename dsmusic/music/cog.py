import discord
import asyncio
import mafic

from discord import app_commands
from discord.ext import commands

from .queue import Queue


@app_commands.guild_only()
class Music(commands.Cog):
    # Create queue
    queue = Queue()

    def __init__(self, bot: discord.Client):
        self.bot = bot

    @commands.Cog.listener(name="on_track_end")
    @commands.Cog.listener(name="on_track_stuck")
    async def on_track_end(self, event: mafic.TrackEndEvent | mafic.TrackStuckEvent):
        player: mafic.Player = event.player

        track = self.queue.next()

        if track:
            return await player.play(track, replace=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, mb: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Disconnect bot if it's the only one in the voice channel"""
        if mb.guild.voice_client is None:
            return
        if before.channel == mb.guild.voice_client.channel:
            if len(before.channel.members) == 1:
                await mb.guild.voice_client.disconnect(force=True)

    @app_commands.command(name="skip", description="Skip the current song")
    @app_commands.checks.cooldown(4, 10, key=lambda i: (i.guild_id, i.user.id))
    async def skip(self, interaction: discord.Interaction):
        await self.on_track_end()
        interaction.response.send_message("✅ Skipping current track", ephemeral=True)

    @app_commands.command(name="play", description="Play a song from YouTube")
    @app_commands.checks.cooldown(3, 10, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.describe(query="An URL or a query for a video on YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play a song on a voice channel"""
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response

        if interaction.guild.voice_client is None:
            vc: mafic.Player = await interaction.user.voice.channel.connect(self_deaf=True, cls=mafic.Player)
        else:
            if interaction.guild.voice_client.channel != interaction.user.voice.channel:
                return await resp.send_message("⚠️ Already on a different channel", ephemeral=True)
            else:
                # noinspection PyTypeChecker
                vc: mafic.Player = interaction.guild.voice_client

        tracks = await vc.fetch_tracks(query)

        if tracks is None:
            return await resp.send_message("⚠️ No song found", ephemeral=True)
        else:
            embed = self.queue.add(tracks)
            if embed is None:
                return await resp.send_message("⚠️ Could not add the song to the queue", ephemeral=True)
            await resp.send_message("✅ Added to the queue", embed=embed)

        if vc.current is None or (vc.current is not None and vc.paused is True):
            await vc.play(self.queue.next(), replace=True)

    @app_commands.command(name="join", description="Join a voice channel")
    @app_commands.describe(channel="A different channel that you want the bot to join")
    @app_commands.checks.cooldown(3, 10, key=lambda i: (i.guild_id, i.user.id))
    async def join(self, interaction: discord.Interaction, channel: app_commands.AppCommandChannel | None = None):
        """Joins a voice channel"""
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response

        if channel:
            try:
                channel = await channel.fetch()
            except discord.errors.Forbidden:
                return await resp.send_message("❌ Channel not available", ephemeral=True)
            except (discord.errors.NotFound, discord.errors.HTTPException):
                return await resp.send_message("❌ Invalid channel", ephemeral=True)
            finally:
                if not (isinstance(channel, discord.VoiceChannel) or isinstance(channel, discord.StageChannel)):
                    return await resp.send_message("❌ Invalid voice channel", ephemeral=True)
        else:
            try:
                channel = interaction.user.voice.channel
            except AttributeError:
                return await resp.send_message("❌ You are not in a voice channel", ephemeral=True)

        voice_client: mafic.Player | None = interaction.guild.voice_client

        if voice_client:
            if voice_client.channel == channel:
                return await resp.send_message("✴️ Bot is already in your voice channel", ephemeral=True)
            else:
                return await resp.send_message("❌ Bot is already in different voice channel", ephemeral=True)
        else:
            try:
                await resp.send_message(f"✅ Connecting to {channel.mention}", suppress_embeds=True)
                await channel.connect(self_deaf=True, cls=mafic.Player, timeout=10)
            except (discord.ClientException, asyncio.TimeoutError):
                return await resp.send_message("❌ Could not connect to your voice channel", ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnect from the current channel")
    async def disconnect(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        voice_client: mafic.Player | None = interaction.guild.voice_client

        if voice_client:
            await voice_client.disconnect()
            return await resp.send_message(f"✅ Disconnected", suppress_embeds=True)
        else:
            return await resp.send_message("✴️ Already disconnected", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))