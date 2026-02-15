import discord
from discord import app_commands
import sqlite3
import os
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

# ================= БАЗА =================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS accepted (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS points (user_id INTEGER PRIMARY KEY, value INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
conn.commit()

# ================= КЛИЕНТ =================

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        try:
            # Полная очистка старых команд
            self.tree.clear_commands(guild=None)
            await self.tree.sync()

            for guild in self.guilds:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)

            await self.tree.sync()
            print("Команды успешно обновлены")

        except Exception as e:
            print("Ошибка синхронизации:", e)

    async def on_ready(self):
        activity = discord.Game(name="Detects Simulator")
        await self.change_presence(status=discord.Status.online, activity=activity)
        print(f"Бот запущен как {self.user}")

bot = Bot()

# ================= ПРОВЕРКИ =================

def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

def is_mod(interaction):
    if is_admin(interaction):
        return True
    cursor.execute("SELECT role_id FROM moderators")
    roles = [r[0] for r in cursor.fetchall()]
    return any(role.id in roles for role in interaction.user.roles)

def add_points(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO points VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE points SET value = value + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ================= СПИСОК КАНДИДАТОВ =================

@bot.tree.command(name="accept", description="Добавить кандидата")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO accepted VALUES (?)", (user.id,))
    conn.commit()

    try:
        await user.send("Вы успешно прошли первый этап отбора. Ожидайте звонка.")
    except:
        pass

    await interaction.response.send_message("Добавлен в список.")

@bot.tree.command(name="list", description="Список кандидатов")
async def list_users(interaction: discord.Interaction):
    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Список пуст.")

    text = "📋 Принятые:\n"
    for i, (uid,) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        text += f"{i}. {member.mention if member else uid}\n"

    await interaction.response.send_message(text)

@bot.tree.command(name="resetlist", description="Очистить список")
async def reset_list(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("DELETE FROM accepted")
    conn.commit()
    await interaction.response.send_message("Список очищен.")

@bot.tree.command(name="call", description="Начать обзвон")
async def call(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()

    for (uid,) in data:
        member = interaction.guild.get_member(uid)
        if member:
            try:
                await member.send(
                    "Проводится обзвон кандидатов. Перейдите в голосовой канал «Зал ожидания»."
                )
            except:
                pass

    cursor.execute("DELETE FROM accepted")
    conn.commit()

    await interaction.response.send_message("Обзвон начат. Список очищен.")

# ================= МОДЕРАЦИЯ =================

@bot.tree.command(name="setmod", description="Назначить роль модератора")
async def set_mod(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO moderators VALUES (?)", (role.id,))
    conn.commit()

    await interaction.response.send_message("Роль добавлена.")

@bot.tree.command(name="mute", description="Выдать мут")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await user.timeout(timedelta(minutes=minutes), reason=reason)
    add_points(interaction.user.id)

    await interaction.response.send_message("Мут выдан.")

@bot.tree.command(name="unmute", description="Снять мут")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await user.timeout(None)
    await interaction.response.send_message("Мут снят.")

@bot.tree.command(name="warn", description="Выдать варн")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (user.id, reason))
    conn.commit()
    add_points(interaction.user.id)

    await interaction.response.send_message("Варн выдан.")

@bot.tree.command(name="warns", description="Посмотреть варны")
async def warns_list(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT reason FROM warns WHERE user_id = ?", (user.id,))
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Варнов нет.")

    text = ""
    for i, (reason,) in enumerate(data, 1):
        text += f"{i}. {reason}\n"

    await interaction.response.send_message(text)

@bot.tree.command(name="removewarn", description="Снять все варны")
async def remove_warn(interaction: discord.Interaction, user: discord.Member):
    if not is_mod(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("DELETE FROM warns WHERE user_id = ?", (user.id,))
    conn.commit()

    await interaction.response.send_message("Варны сняты.")

# ================= БАЛЛЫ =================

@bot.tree.command(name="addpoints", description="Добавить баллы")
async def addpoints(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    add_points(user.id, amount)
    await interaction.response.send_message("Баллы добавлены.")

@bot.tree.command(name="removepoints", description="Снять баллы")
async def removepoints(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("UPDATE points SET value = value - ? WHERE user_id = ?", (amount, user.id))
    conn.commit()

    await interaction.response.send_message("Баллы сняты.")

@bot.tree.command(name="table", description="Таблица баллов")
async def table(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, value FROM points ORDER BY value DESC")
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("Таблица пуста.")

    text = "📊 Таблица администрации:\n"
    for i, (uid, value) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        text += f"{i}. {member.mention if member else uid} — {value}\n"

    await interaction.response.send_message(text)

# ================= ЧЕРНЫЙ СПИСОК =================

@bot.tree.command(name="blacklist", description="Добавить в ЧС")
async def blacklist(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("INSERT OR REPLACE INTO blacklist VALUES (?, ?)", (user.id, reason))
    conn.commit()

    await interaction.response.send_message("Пользователь добавлен в ЧС.")

@bot.tree.command(name="unblacklist", description="Убрать из ЧС")
async def unblacklist(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    cursor.execute("DELETE FROM blacklist WHERE user_id = ?", (user.id,))
    conn.commit()

    await interaction.response.send_message("Пользователь удалён из ЧС.")

bot.run(TOKEN)
