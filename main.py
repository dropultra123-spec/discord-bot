import discord
from discord import app_commands
import os
import sqlite3
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

# ---------------- ТАБЛИЦЫ ----------------
cursor.execute("CREATE TABLE IF NOT EXISTS accepted_users (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS admin_points (user_id INTEGER PRIMARY KEY, points INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS warns (user_id INTEGER, reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS log_channel (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS global_blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
conn.commit()

# ---------------- КЛИЕНТ ----------------
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        activity = discord.Game(name="Detects Simulator")
        await self.change_presence(status=discord.Status.online, activity=activity)
        print(f"Бот запущен как {self.user}")

client = MyClient()

# ---------------- ВСПОМОГАТЕЛЬНЫЕ ----------------
def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

def is_mod(interaction):
    if is_admin(interaction):
        return True
    cursor.execute("SELECT role_id FROM moderators")
    roles = cursor.fetchall()
    return any(role_id[0] in [r.id for r in interaction.user.roles] for role_id in roles)

def add_points(user_id, amount):
    cursor.execute("INSERT OR IGNORE INTO admin_points VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE admin_points SET points = points + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

async def send_log(guild, message):
    cursor.execute("SELECT channel_id FROM log_channel WHERE guild_id = ?", (guild.id,))
    data = cursor.fetchone()
    if data:
        channel = guild.get_channel(data[0])
        if channel:
            await channel.send(message)

# ---------------- СТАРЫЕ КОМАНДЫ ----------------
@client.tree.command(name="принят")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO accepted_users VALUES (?)", (user.id,))
    conn.commit()
    await user.send("Вы прошли первый этап отбора. Ожидайте инструкций.")
    await interaction.response.send_message("Добавлен.")

@client.tree.command(name="список")
async def list_users(interaction: discord.Interaction):
    cursor.execute("SELECT user_id FROM accepted_users")
    data = cursor.fetchall()
    text = "Принятые:\n"
    for i, (uid,) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        text += f"{i}. {member.mention if member else uid}\n"
    await interaction.response.send_message(text or "Пусто.")

@client.tree.command(name="ресетсписок")
async def reset_list(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)
    cursor.execute("DELETE FROM accepted_users")
    conn.commit()
    await interaction.response.send_message("Список очищен.")

# ---------------- ЛОГИ ----------------
@client.tree.command(name="логи")
async def set_logs(interaction: discord.Interaction, канал: discord.TextChannel):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)
    cursor.execute("INSERT OR REPLACE INTO log_channel VALUES (?, ?)", (interaction.guild.id, канал.id))
    conn.commit()
    await interaction.response.send_message("Канал логов установлен.")

# ---------------- МУТ ----------------
@client.tree.command(name="мут")
async def mute(interaction: discord.Interaction, user: discord.Member, время: int, причина: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await user.timeout(timedelta(minutes=время))
    add_points(interaction.user.id, 1)

    await send_log(interaction.guild, f"🔇 {user} мут на {время} мин. Причина: {причина}")
    await user.send(f"Вам выдан мут на {время} минут.\nПричина: {причина}\nВыдал: {interaction.user}")

    await interaction.response.send_message("Мут выдан. +1 балл.")

# ---------------- СНЯТЬ МУТ ----------------
@client.tree.command(name="снятьмут")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await user.timeout(None)
    await send_log(interaction.guild, f"🔊 Снят мут с {user}")
    await interaction.response.send_message("Мут снят.")

# ---------------- ВАРН ----------------
@client.tree.command(name="варн")
async def warn(interaction: discord.Interaction, user: discord.Member, причина: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT INTO warns VALUES (?, ?)", (user.id, причина))
    conn.commit()
    add_points(interaction.user.id, 1)

    await user.send(f"Вам выдан варн.\nПричина: {причина}\nВыдал: {interaction.user}")
    await send_log(interaction.guild, f"⚠ {user} получил варн. Причина: {причина}")
    await interaction.response.send_message("Варн выдан. +1 балл.")

# ---------------- СНЯТЬ ВАРН ----------------
@client.tree.command(name="снятьварн")
async def remove_warn(interaction: discord.Interaction, user: discord.Member, причина: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("DELETE FROM warns WHERE user_id = ? AND reason = ? LIMIT 1", (user.id, причина))
    conn.commit()
    await interaction.response.send_message("Варн снят.")

# ---------------- ГЛОБАЛЬНЫЙ ЧС ----------------
@client.tree.command(name="очс")
async def global_blacklist(interaction: discord.Interaction, user: discord.User, причина: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR REPLACE INTO global_blacklist VALUES (?, ?)", (user.id, причина))
    conn.commit()

    for guild in client.guilds:
        try:
            await guild.ban(user, reason=f"Глобальный ЧС: {причина}")
        except:
            pass

    await interaction.response.send_message("Пользователь добавлен в глобальный ЧС.")

# ---------------- СНЯТЬ ЧС ----------------
@client.tree.command(name="снятьочс")
async def remove_global_blacklist(interaction: discord.Interaction, user: discord.User):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("DELETE FROM global_blacklist WHERE user_id = ?", (user.id,))
    conn.commit()

    for guild in client.guilds:
        try:
            await guild.unban(user)
        except:
            pass

    await interaction.response.send_message("Пользователь удалён из глобального ЧС.")

client.run(TOKEN)
