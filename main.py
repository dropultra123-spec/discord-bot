import discord
from discord import app_commands
import os
import sqlite3
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

# ---------- ТАБЛИЦЫ ----------
cursor.execute("CREATE TABLE IF NOT EXISTS accepted_users (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS admin_points (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS log_channel (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS global_blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
conn.commit()

# ---------- КЛИЕНТ ----------
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

# ---------- ПРОВЕРКИ ----------
def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

def is_mod(interaction):
    if is_admin(interaction):
        return True
    cursor.execute("SELECT role_id FROM moderators")
    roles = cursor.fetchall()
    user_roles = [r.id for r in interaction.user.roles]
    return any(role_id[0] in user_roles for role_id in roles)

def add_points(user_id, amount):
    cursor.execute("INSERT OR IGNORE INTO admin_points (user_id, points) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE admin_points SET points = points + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

async def send_log(guild, text):
    cursor.execute("SELECT channel_id FROM log_channel WHERE guild_id = ?", (guild.id,))
    data = cursor.fetchone()
    if data:
        channel = guild.get_channel(data[0])
        if channel:
            await channel.send(text)

# =================================================
# ================= СТАРЫЕ КОМАНДЫ ===============
# =================================================

@client.tree.command(name="принят")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO accepted_users VALUES (?)", (user.id,))
    conn.commit()

    try:
        await user.send("Вы успешно прошли первый этап отбора. Ожидайте дальнейших инструкций.")
    except:
        pass

    await interaction.response.send_message("Игрок добавлен в список.")

@client.tree.command(name="список")
async def list_users(interaction: discord.Interaction):
    cursor.execute("SELECT user_id FROM accepted_users")
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Список пуст.")

    text = "📋 Принятые:\n"
    for i, (uid,) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        text += f"{i}. {member.mention if member else uid}\n"

    await interaction.response.send_message(text)

@client.tree.command(name="ресетсписок")
async def reset_list(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("DELETE FROM accepted_users")
    conn.commit()
    await interaction.response.send_message("Список очищен.")

@client.tree.command(name="обзвон")
async def call_users(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("SELECT user_id FROM accepted_users")
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Список пуст.")

    for (uid,) in data:
        member = interaction.guild.get_member(uid)
        if member:
            try:
                await member.send(
                    "📞 Проводится обзвон. Перейдите в голосовой канал «Зал ожидания»."
                )
            except:
                pass

    cursor.execute("DELETE FROM accepted_users")
    conn.commit()

    await interaction.response.send_message("Обзвон начат. Список очищен.")

# =================================================
# ================= НОВЫЕ КОМАНДЫ ================
# =================================================

@client.tree.command(name="мод")
async def set_mod(interaction: discord.Interaction, роль: discord.Role):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO moderators VALUES (?)", (роль.id,))
    conn.commit()
    await interaction.response.send_message("Роль назначена администрацией.")

@client.tree.command(name="мут")
async def mute(interaction: discord.Interaction, пользователь: discord.Member, минуты: int, причина: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await пользователь.timeout(timedelta(minutes=минуты), reason=причина)
    add_points(interaction.user.id, 1)

    try:
        await пользователь.send(f"Вам выдан мут на {минуты} минут.\nПричина: {причина}")
    except:
        pass

    await send_log(interaction.guild, f"🔇 {пользователь} мут на {минуты} мин.")
    await interaction.response.send_message("Мут выдан. +1 балл.")

@client.tree.command(name="снятьмут")
async def unmute(interaction: discord.Interaction, пользователь: discord.Member):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await пользователь.timeout(None)
    await interaction.response.send_message("Мут снят.")

@client.tree.command(name="варн")
async def warn(interaction: discord.Interaction, пользователь: discord.Member, причина: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (пользователь.id, причина))
    conn.commit()
    add_points(interaction.user.id, 1)

    await interaction.response.send_message("Варн выдан. +1 балл.")

@client.tree.command(name="варны")
async def warns_list(interaction: discord.Interaction, пользователь: discord.Member):
    cursor.execute("SELECT reason FROM warns WHERE user_id = ?", (пользователь.id,))
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Варнов нет.")

    text = ""
    for i, warn_reason in enumerate(data, 1):
        text += f"{i}. {warn_reason[0]}\n"

    await interaction.response.send_message(text)

@client.tree.command(name="таблица")
async def table(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, points FROM admin_points ORDER BY points DESC")
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Таблица пуста.")

    text = "📊 Таблица администрации:\n"
    for i, (uid, points) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        text += f"{i}. {member.mention if member else uid} — {points}\n"

    await interaction.response.send_message(text)

client.run(TOKEN)
