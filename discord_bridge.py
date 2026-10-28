"""Optional owner-only Discord slash-command bridge for ESN Jarvis.

Run separately after saving a 'discord_bot' connection in the vault and setting
DISCORD_OWNER_USER_ID + DISCORD_CONNECTION_ID. No privileged intents requested.
"""
import asyncio
import os
import time

from connections import read_secret_local
import jarvis
import memory_store
import autonomous
import maintenance
import dm_access


def run():
    import discord
    from discord import app_commands

    owner_id = int(os.environ.get('DISCORD_OWNER_USER_ID', '0'))
    conn_id = os.environ.get('DISCORD_CONNECTION_ID', '')
    guild_id = os.environ.get('DISCORD_GUILD_ID', '')
    if owner_id <= 0 or not conn_id:
        raise SystemExit('Set DISCORD_OWNER_USER_ID and DISCORD_CONNECTION_ID')
    token = read_secret_local(conn_id)
    intents = discord.Intents.default()
    intents.dm_messages = True
    # Bot DM content does not require privileged guild message-content intent.
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    blocked_notice = {}
    dm_semaphore = asyncio.Semaphore(1)

    async def dm_text(message, body):
        async with dm_semaphore:
            await message.channel.send(body[:1800], allowed_mentions=discord.AllowedMentions.none())


    async def owner_only(interaction):
        if interaction.user.id != owner_id:
            await interaction.response.send_message(dm_access.PRIVATE_REPLY, ephemeral=True)
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

    @tree.command(name='jarvis_ask', description='Ask Jarvis privately (owner or time-limited DM guest)')
    @app_commands.describe(question='Your question for Jarvis')
    async def ask(interaction: discord.Interaction, question: str):
        owner = interaction.user.id == owner_id
        guest = (not owner and interaction.guild is None
                 and isinstance(interaction.channel, discord.DMChannel))
        if not owner and not guest:
            await interaction.response.send_message(dm_access.PRIVATE_REPLY, ephemeral=True)
            return
        if guest:
            decision = await asyncio.to_thread(dm_access.consume, interaction.user.id)
            if decision == 'denied':
                await interaction.response.send_message(dm_access.PRIVATE_REPLY, ephemeral=True)
                return
            if decision == 'cooldown':
                await interaction.response.send_message('Please slow down before your next question.', ephemeral=True)
                return
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await asyncio.to_thread(jarvis.chat if owner else dm_access.guest_chat, question)
            await interaction.followup.send(reply[:1800], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            await interaction.followup.send('AI request failed. Please try again later.', ephemeral=True)

    @tree.command(name='jarvis_remember', description='Privately save a fact for future Jarvis chats')
    @app_commands.describe(topic='Short label, e.g. hosting-goal', note='Fact to remember (never passwords or tokens)')
    async def remember(interaction: discord.Interaction, topic: str, note: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            saved = await asyncio.to_thread(memory_store.remember, jarvis.DB_PATH, topic, note)
            await interaction.followup.send(f'Encrypted memory saved under **{saved}**. Use /jarvis_forget to delete it.', ephemeral=True)
        except (ValueError, RuntimeError):
            await interaction.followup.send('Memory was not saved. Use a short topic and a fact without account secrets. Maximum 30 saved notes.', ephemeral=True)

    @tree.command(name='jarvis_memories', description='See your private saved Jarvis memory notes')
    async def memories(interaction: discord.Interaction):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            notes = await asyncio.to_thread(memory_store.list_notes, jarvis.DB_PATH)
            if not notes:
                await interaction.followup.send('No long-term memories saved yet.', ephemeral=True)
            else:
                # Never print note contents to normal Discord channels or logs.
                lines = [f'• {item["topic"]}: {item["note"]}' for item in notes]
                answer = '\n'.join(lines)
                await interaction.followup.send(answer[:1800], ephemeral=True)
        except Exception:
            await interaction.followup.send('Memory unavailable. See private service logs.', ephemeral=True)

    @tree.command(name='jarvis_forget', description='Remove one explicitly saved Jarvis memory')
    @app_commands.describe(topic='Exact memory topic to delete')
    async def forget(interaction: discord.Interaction, topic: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            removed = await asyncio.to_thread(memory_store.forget, jarvis.DB_PATH, topic)
            await interaction.followup.send('Memory deleted.' if removed else 'No matching memory topic found.', ephemeral=True)
        except ValueError:
            await interaction.followup.send('Invalid memory topic.', ephemeral=True)

    @tree.command(name='jarvis_auto', description='Draft a safe multi-step ESN health audit (approval required)')
    @app_commands.describe(goal='Example: Audit ESN panel, website and GitHub')
    async def auto(interaction: discord.Interaction, goal: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            plan_id = await asyncio.to_thread(autonomous.create, goal)
            plan = await asyncio.to_thread(autonomous.get, plan_id)
            steps = '\n'.join(
                f'{item["position"] + 1}. {item["kind"].replace("_", " ")}'
                for item in plan['steps']
            )
            await interaction.followup.send(
                f'**Draft only — no steps have run.**\n'
                f'Plan ID: `{plan_id}`\n'
                f'{steps}\n'
                f'Use /jarvis_auto_approve with this ID to execute the read-only checks.',
                ephemeral=True,
            )
        except ValueError as exc:
            await interaction.followup.send(f'Cannot create that plan: {str(exc)[:170]}', ephemeral=True)
        except Exception:
            await interaction.followup.send('Unable to create plan. See private server logs.', ephemeral=True)

    @tree.command(name='jarvis_auto_approve', description='Owner approval to execute one saved read-only plan')
    @app_commands.describe(plan_id='Plan UUID from /jarvis_auto')
    async def auto_approve(interaction: discord.Interaction, plan_id: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.to_thread(autonomous.approve, plan_id)
            await interaction.followup.send(
                'Approved. Jarvis will run the read-only steps in order. '
                'Check /jarvis_auto_status or the Task Center for real progress.', ephemeral=True
            )
        except (ValueError, KeyError) as exc:
            await interaction.followup.send(f'Could not approve plan: {str(exc)[:170]}', ephemeral=True)

    @tree.command(name='jarvis_auto_status', description='See actual results and progress of an autonomous plan')
    @app_commands.describe(plan_id='Plan UUID from /jarvis_auto')
    async def auto_status(interaction: discord.Interaction, plan_id: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            plan = await asyncio.to_thread(autonomous.get, plan_id)
            steps = '\n'.join(
                f'{item["position"] + 1}. {item["kind"]}: {item["status"]}'
                + (' (retry ' + str(item['attempts']) + ')' if item['status'] == 'queued' and item['attempts'] else '')
                for item in plan['steps']
            )
            await interaction.followup.send(
                f'**Plan {plan["status"]} — {plan["completed_steps"]}/{plan["total_steps"]} completed**\n'
                f'{steps}\n'
                f'Open https://jarvis.esnoffical.com/tasks to view verified results.', ephemeral=True
            )
        except (ValueError, KeyError):
            await interaction.followup.send('Plan not found or invalid ID.', ephemeral=True)

    @tree.command(name='jarvis_auto_cancel', description='Cancel unstarted steps in a Jarvis plan')
    @app_commands.describe(plan_id='Plan UUID from /jarvis_auto')
    async def auto_cancel(interaction: discord.Interaction, plan_id: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            outcome = await asyncio.to_thread(autonomous.cancel, plan_id)
            await interaction.followup.send(
                f'Plan status: {outcome}. An in-flight read-only request may finish before stopping.',
                ephemeral=True,
            )
        except (ValueError, KeyError):
            await interaction.followup.send('Plan not found or invalid ID.', ephemeral=True)

    @tree.command(name='jarvis_disk', description='Inspect storage pressure on the current Jarvis VPS (read-only)')
    async def disk(interaction: discord.Interaction):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            data = await asyncio.to_thread(maintenance.report)
            gb = 1024 ** 3
            cache = data['jarvis_owned_cache']
            await interaction.followup.send(
                f'**Jarvis VPS disk (not all nodes)**\n'
                f'Used: {data["used_bytes"]/gb:.1f} / {data["total_bytes"]/gb:.1f} GiB\n'
                f'Free: {data["free_bytes"]/gb:.1f} GiB ({data["free_percent"]:.1f}%)\n'
                f'Pressure: {data["disk_pressure"]}\n'
                f'Jarvis-owned cache older than 7 days: '
                f'{cache["older_than_7_days_bytes"]/1048576:.1f} MiB '
                f'in {cache["older_than_7_days_file_count"]} files\n'
                'Read-only: No files removed. Other ESN nodes require separate agent setup.',
                ephemeral=True,
            )
        except Exception:
            await interaction.followup.send('Disk audit unavailable. See private service logs.', ephemeral=True)

    @tree.command(name='jarvis_dm_grant', description='Owner: permit a user to chat privately for a limited time')
    @app_commands.describe(user_id='Recipient numeric Discord user ID',
                           minutes='Access duration, 5 to 1440 minutes',
                           messages='Maximum guest questions, 1 to 30')
    async def dm_grant(interaction: discord.Interaction, user_id: str, minutes: int, messages: int = 12):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            if int(dm_access.validate_user_id(user_id)) == owner_id:
                raise ValueError('Owner already has access')
            saved = await asyncio.to_thread(dm_access.grant, user_id, minutes, messages)
            await interaction.followup.send(
                f'Guest permission saved for user {saved["user_id"]}. '
                f'Expires <t:{saved["expires_at"]}:R>; maximum {saved["remaining"]} messages. '
                'They may DM ESN Jarvis to begin. No infrastructure, account, server or owner memory access.',
                ephemeral=True,
            )
        except (ValueError, TypeError) as exc:
            await interaction.followup.send(f'Permission not granted: {str(exc)[:170]}', ephemeral=True)

    @tree.command(name='jarvis_dm_revoke', description='Owner: immediately revoke one temporary guest')
    @app_commands.describe(user_id='Recipient numeric Discord user ID')
    async def dm_revoke(interaction: discord.Interaction, user_id: str):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            changed = await asyncio.to_thread(dm_access.revoke, user_id)
            await interaction.followup.send(
                'Guest access revoked.' if changed else 'No guest grant for that ID.', ephemeral=True
            )
        except ValueError:
            await interaction.followup.send('Invalid Discord user ID.', ephemeral=True)

    @tree.command(name='jarvis_dm_guests', description='Owner: list active temporary private chat grants')
    async def dm_guests(interaction: discord.Interaction):
        if not await owner_only(interaction): return
        await interaction.response.defer(ephemeral=True)
        rows = await asyncio.to_thread(dm_access.active_grants)
        if not rows:
            await interaction.followup.send('No active Jarvis DM guests.', ephemeral=True)
            return
        lines = [
            f'User {r["user_id"]}: {r["remaining"]} questions left, expires <t:{r["expires_at"]}:R>'
            for r in rows
        ]
        await interaction.followup.send('\n'.join(lines)[:1700], ephemeral=True)

    @client.event
    async def on_message(message: discord.Message):
        # Deliberately ignore ALL guild text; bot DMs only.
        if message.author.bot or message.guild is not None or not isinstance(message.channel, discord.DMChannel):
            return
        body = (message.content or '').strip()
        owner = message.author.id == owner_id
        if not owner:
            decision = await asyncio.to_thread(dm_access.consume, message.author.id)
            if decision == 'denied':
                stamp = time.monotonic()
                if stamp - blocked_notice.get(message.author.id, -9999) >= 60:
                    blocked_notice[message.author.id] = stamp
                    if len(blocked_notice) > 300:
                        blocked_notice.clear()
                    await dm_text(message, dm_access.PRIVATE_REPLY)
                return
            if decision == 'cooldown':
                await dm_text(message, 'Please slow down before your next question.')
                return
        if not body:
            await dm_text(message, 'Please send a text question to Jarvis.')
            return
        try:
            if owner and len(body) > 4000:
                await dm_text(message, 'Please send a message under 4,000 characters.')
                return
            if not owner and len(body) > 1300:
                await dm_text(message, 'Please send a question under 1,300 characters.')
                return
            async with message.channel.typing():
                reply = await asyncio.to_thread(jarvis.chat if owner else dm_access.guest_chat, body)
            await dm_text(message, reply)
        except Exception:
            await dm_text(message, 'Jarvis is temporarily unavailable. Please try again later.')

    @client.event
    async def on_ready():
        await tree.sync()  # Global commands can appear in bot DMs.
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        print('ESN Discord bridge online; bot DMs and owner-only commands synced')

    client.run(token, log_handler=None)


if __name__ == '__main__':
    run()
