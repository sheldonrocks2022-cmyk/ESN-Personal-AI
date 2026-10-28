"""Optional owner-only Discord slash-command bridge for ESN Jarvis.

Run separately after saving a 'discord_bot' connection in the vault and setting
DISCORD_OWNER_USER_ID + DISCORD_CONNECTION_ID. No privileged intents requested.
"""
import asyncio
import os

from connections import read_secret_local
import jarvis


def run():
    import discord
    from discord import app_commands

    owner_id = int(os.environ.get('DISCORD_OWNER_USER_ID', '0'))
    conn_id = os.environ.get('DISCORD_CONNECTION_ID', '')
    guild_id = os.environ.get('DISCORD_GUILD_ID', '')
    if owner_id <= 0 or not conn_id:
        raise SystemExit('Set DISCORD_OWNER_USER_ID and DISCORD_CONNECTION_ID')
    token = read_secret_local(conn_id)
    client = discord.Client(intents=discord.Intents.default())
    tree = app_commands.CommandTree(client)

    async def owner_only(interaction):
        if interaction.user.id != owner_id:
            await interaction.response.send_message('Private ESN owner command.', ephemeral=True)
            return False
        return True

    @tree.command(name='jarvis_status', description='Check ESN Jarvis and panel reachability')
    async def status(interaction: discord.Interaction):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await asyncio.to_thread(jarvis.run_panel_job, 'panel_health')
            await interaction.followup.send(f'Jarvis running. Panel HTTP status: {result["http_status"]}', ephemeral=True)
        except Exception:
            await interaction.followup.send('Panel check failed. Check Jarvis server logs.', ephemeral=True)

    @tree.command(name='jarvis_ask', description='Ask your private Jarvis assistant a question')
    @app_commands.describe(question='Your question for Jarvis')
    async def ask(interaction: discord.Interaction, question: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await asyncio.to_thread(jarvis.chat, question)
            await interaction.followup.send(reply[:1800], ephemeral=True)
        except Exception:
            await interaction.followup.send('AI request failed. Check private server logs.', ephemeral=True)

    @client.event
    async def on_ready():
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        else:
            await tree.sync()
        print('ESN Discord bridge signed in; owner-only commands synced')

    client.run(token, log_handler=None)


if __name__ == '__main__':
    run()
