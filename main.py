import discord
from discord import app_commands
import os
import sqlite3
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

# Таблицы
cursor.execute("CREATE TABLE IF NOT EXISTS accepted_users (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS admin_points (user_id INTEGER PRIMARY KEY, points INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS warns (user_id INTEGER, reason TEXT)")
conn.commit()

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

# Проверка прав
def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

def is_mod(interaction):
    if is_admin(interaction):
        return True
    cursor.execute("SELECT role_id FROM moderators")
    roles = cursor.fetchall()
    user_roles = [r.id for r in interaction.user.roles]
    return any(role_id[0] in user_roles for role_id in roles)

def add_point(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO admin_points (user_id, points) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE admin_points SET points = points + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ---------------- МОД РОЛЬ ----------------
@client.tree.command(name="мод", description="Назначить роль администрации")
async def set_mod(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("Нет прав.", ephemeral=True)
        return
    cursor.execute("INSERT OR IGNORE INTO moderators (role_id) VALUES (?)", (role.id,))
    conn.commit()
    await interaction.response.send_message(f"Роль {role.name} теперь администрация.")

# ---------------- МУТ ----------------
@client.tree.command(name="мут", description="Выдать мут")
async def mute(interaction: discord.Interaction, user: discord.Member, время: int, причина: str):
    if not is_mod(interaction):
        await interaction.response.send_message("Нет прав.", ephemeral=True)
        return

    await user.timeout(timedelta(minutes=время), reason=причина)
    add_point(interaction.user.id, 1)

    try:
        await user.send(f"🔇 Вам выдан мут на {время} минут.\nПричина: {причина}\nВыдал: {interaction.user}")
    except:
        pass

    await interaction.response.send_message("Мут выдан. +1 балл")

# ---------------- ВАРН ----------------
@client.tree.command(name="варн", description="Выдать варн")
async def warn(interaction: discord.Interaction, user: discord.Member, причина: str):
    if not is_mod(interaction):
        await interaction.response.send_message("Нет прав.", ephemeral=True)
        return

    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (user.id, причина))
    conn.commit()
    add_point(interaction.user.id, 1)

    try:
        await user.send(f"⚠ Вам выдан варн.\nПричина: {причина}\nВыдал: {interaction.user}")
    except:
        pass

    await interaction.response.send_message("Варн выдан. +1 балл")

# ---------------- ПОСМОТРЕТЬ ВАРНЫ ----------------
@client.tree.command(name="варны", description="Посмотреть варны")
async def warns_list(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT reason FROM warns WHERE user_id = ?", (user.id,))
    data = cursor.fetchall()

    if not data:
        await interaction.response.send_message("Варнов нет.")
        return

    text = f"⚠ Варны {user.mention}:\n"
    for i, warn_reason in enumerate(data, 1):
        text += f"{i}. {warn_reason[0]}\n"

    await interaction.response.send_message(text)

# ---------------- СНЯТЬ ВАРН ----------------
@client.tree.command(name="снятьварн", description="Снять варн")
async def remove_warn(interaction: discord.Interaction, user: discord.Member, причина: str):
    if not is_mod(interaction):
        await interaction.response.send_message("Нет прав.", ephemeral=True)
        return

    cursor.execute("DELETE FROM warns WHERE user_id = ? AND reason = ? LIMIT 1", (user.id, причина))
    conn.commit()
    await interaction.response.send_message("Варн снят.")

# ---------------- ВЫДАТЬ БАЛЛЫ ----------------
@client.tree.command(name="выдача", description="Выдать баллы администрации")
async def give_points(interaction: discord.Interaction, user: discord.Member, количество: int):
    if not is_admin(interaction):
        await interaction.response.send_message("Нет прав.", ephemeral=True)
        return

    add_point(user.id, количество)
    await interaction.response.send_message("Баллы выданы.")

# ---------------- СНЯТЬ БАЛЛЫ ----------------
@client.tree.command(name="снятьбаллы", description="Снять баллы")
async def remove_points(interaction: discord.Interaction, user: discord.Member, количество: int):
    if not is_admin(interaction):
        await interaction.response.send_message("Нет прав.", ephemeral=True)
        return

    cursor.execute("UPDATE admin_points SET points = points - ? WHERE user_id = ?", (количество, user.id))
    conn.commit()
    await interaction.response.send_message("Баллы сняты.")

# ---------------- ТАБЛИЦА ----------------
@client.tree.command(name="таблица", description="Таблица администрации")
async def table(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, points FROM admin_points ORDER BY points DESC")
    data = cursor.fetchall()

    if not data:
        await interaction.response.send_message("Таблица пуста.")
        return

    text = "📊 Таблица отчётов:\n"
    for i, (user_id, points) in enumerate(data, 1):
        member = interaction.guild.get_member(user_id)
        name = member.mention if member else f"ID {user_id}"
        text += f"{i}. {name} — {points} баллов\n"

    await interaction.response.send_message(text)

client.run(TOKEN)
