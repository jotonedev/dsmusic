import asyncio

import discord
import mafic
from discord import app_commands
from discord.channel import VocalGuildChannel
from discord.ext import commands

from .player import LavalinkPlayer

logger = logging.getLogger('discord.dsbot.music.cog')


@app_commands.guild_only()
class Music(commands.Cog):
    def __init__(self, bot: discord.Client):
        self.bot = bot

    @commands.Cog.listener(name="on_track_end")
    @commands.Cog.listener(name="on_track_stuck")
    async def on_track_end(self, event: mafic.TrackEndEvent | mafic.TrackStuckEvent):
        player: LavalinkPlayer = event.player

        track = player.queue.next()

        if track:
            return await player.play(track, replace=True)

    @commands.Cog.listener("on_voice_state_update")
    async def auto_disconnect(self, mb: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Disconnect bot if it's the only one in the voice channel"""
        if mb.guild.voice_client is None:
            return
        if before.channel == mb.guild.voice_client.channel:
            if len(before.channel.members) == 1:
                await mb.guild.voice_client.disconnect(force=True)

    @commands.Cog.listener("on_voice_state_update")
    async def cleanup_after_disconnect(self, mb: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if mb == self.bot.user:
            if isinstance(before.channel, VocalGuildChannel) and after.channel is None:
                # noinspection PyTypeChecker
                vc: LavalinkPlayer = mb.guild.voice_client
                if vc is not None:
                    vc.clean_queue()
                    await vc.disconnect(force=True)
                    del vc
                else:
                    return

    @app_commands.command(name="skip", description="Skip the current song")
    @app_commands.checks.cooldown(4, 10, key=lambda i: (i.guild_id, i.user.id))
    async def skip(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        # noinspection PyTypeChecker
        vc: LavalinkPlayer = interaction.guild.voice_client

        if vc is None:
            return await resp.send_message("❌ Not connected to a voice channel", ephemeral=True)

        track = vc.queue.next()
        await resp.send_message("✅ Skipping current track", ephemeral=True)

        if track:
            return await vc.play(track, replace=True)
        else:
            return await vc.stop()

    @app_commands.command(name="play", description="Play a song from YouTube")
    @app_commands.checks.cooldown(3, 10, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.describe(query="An URL or a query for a video on YouTube")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play a song on a voice channel"""
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response

        await resp.defer(thinking=True)

        if interaction.guild.voice_client is None:
            vc: LavalinkPlayer = await interaction.user.voice.channel.connect(self_deaf=True, cls=LavalinkPlayer)
            vc.is_connected()
        else:
            if interaction.guild.voice_client.channel != interaction.user.voice.channel:
                return await interaction.followup.send("⚠️ Already on a different channel", ephemeral=True)
            else:
                # noinspection PyTypeChecker
                vc: LavalinkPlayer = interaction.guild.voice_client

        try:
            with asyncio.timeout(10):
                tracks = await vc.fetch_tracks(query)
        except asyncio.TimeoutError:
            return await interaction.followup.send("⚠️ Timed out (please, report to the bot owner)", ephemeral=True)

        if tracks is None:
            return await interaction.followup.send("⚠️ No song found", ephemeral=True)
        else:
            embed = vc.queue.add(tracks)
            if embed is None:
                return await interaction.followup.send("⚠️ Could not add the song to the queue", ephemeral=True)
            await interaction.followup.send("✅ Added to the queue", embed=embed)

        if vc.current is None or (vc.current is not None and vc.paused is True):
            await vc.play(vc.queue.next(), replace=True)

    @app_commands.command(name="repeat", description="Repeat the same song")
    async def repeat(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        # noinspection PyTypeChecker
        vc: LavalinkPlayer = interaction.guild.voice_client

        if vc is None:
            return await resp.send_message("❌ Not connected to a voice channel", ephemeral=True)

        status = vc.queue.toggle_repeat()

        if status:
            await resp.send_message("🔂 Enabled repeat")
        else:
            await resp.send_message("➡️ Disabled repeat")

    @app_commands.command(name="loop", description="Loop over the queue")
    async def loop(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        # noinspection PyTypeChecker
        vc: LavalinkPlayer = interaction.guild.voice_client

        if vc is None:
            return await resp.send_message("❌ Not connected to a voice channel", ephemeral=True)

        status = vc.queue.toggle_loop()

        if status:
            await resp.send_message("🔁 Enabled loop")
        else:
            await resp.send_message("➡️ Disabled loop")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        # noinspection PyTypeChecker
        vc: LavalinkPlayer = interaction.guild.voice_client

        if vc is None:
            return await resp.send_message("❌ Not connected to a voice channel", ephemeral=True)

        status = vc.queue.toggle_shuffle()

        if status:
            await resp.send_message("🔀 Enabled shuffle")
        else:
            await resp.send_message("➡️ Disabled shuffle")

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

        voice_client: LavalinkPlayer | None = interaction.guild.voice_client

        if voice_client:
            if voice_client.channel == channel:
                return await resp.send_message("✴️ Bot is already in your voice channel", ephemeral=True)
            else:
                return await resp.send_message("❌ Bot is already in different voice channel", ephemeral=True)
        else:
            try:
                await resp.send_message(f"✅ Connecting to {channel.mention}", suppress_embeds=True)
                await channel.connect(self_deaf=True, cls=LavalinkPlayer, timeout=10)
            except (discord.ClientException, asyncio.TimeoutError):
                return await resp.send_message("❌ Could not connect to your voice channel", ephemeral=True)

    @app_commands.command(name="disconnect", description="Disconnect from the current channel")
    async def disconnect(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        voice_client: LavalinkPlayer | None = interaction.guild.voice_client

        if voice_client:
            await voice_client.disconnect()
            return await resp.send_message(f"✅ Disconnected", suppress_embeds=True)
        else:
            return await resp.send_message("✴️ Already disconnected", ephemeral=True)

    @app_commands.command(name="reset", description="Reset the queue")
    async def reset(self, interaction: discord.Interaction):
        # noinspection PyTypeChecker
        resp: discord.InteractionResponse = interaction.response
        voice_client: LavalinkPlayer | None = interaction.guild.voice_client

        if voice_client:
            n = voice_client.queue.clean()
            return await resp.send_message(f"✅ Removed {n} track(s)", suppress_embeds=True)
        else:
            return await resp.send_message("❌ Not connected to a voice channel", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    logger.info("Loading music cog")
    await bot.add_cog(Music(bot))
    logger.info("Music cog loaded")
