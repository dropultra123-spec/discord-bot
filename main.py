import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
import os
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

# ================= БАЗА ДАННЫХ =================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS points (user_id INTEGER PRIMARY KEY, value INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
    conn.commit()

init_db()

def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    r = cursor.fetchone()
    return r[0] if r else None

def set_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
    conn.commit()

def add_points(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO points VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE points SET value = value + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ================= БОТ =================

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        await self.tree.sync()
        print(f"✅ Бот запущен: {self.user}")
        if not self.norma_check.is_running():
            self.norma_check.start()

    @tasks.loop(hours=168)
    async def norma_check(self):
        norma = get_setting("norma")
        role_id = get_setting("admin_role")
        log_id = get_setting("log_channel")
        if not norma or not role_id:
            return

        for guild in self.guilds:
            role = guild.get_role(role_id)
            log = guild.get_channel(log_id) if log_id else None
            if not role:
                continue

            for member in role.members:
                cursor.execute("SELECT value FROM points WHERE user_id = ?", (member.id,))
                p = cursor.fetchone()
                p = p[0] if p else 0
                if p < norma and log:
                    await log.send(f"⚠️ {member.mention} не выполнил норму ({p}/{norma})")

            cursor.execute("UPDATE points SET value = 0")
            conn.commit()

bot = Bot()

# ================= ПРОВЕРКА АДМИНА =================

def is_admin(interaction: discord.Interaction):
    role_id = get_setting("admin_role")
    if not role_id:
        return False
    role = interaction.guild.get_role(role_id)
    return role in interaction.user.roles

async def log(guild, text):
    log_id = get_setting("log_channel")
    if log_id:
        ch = guild.get_channel(log_id)
        if ch:
            await ch.send(embed=discord.Embed(description=text, color=discord.Color.orange()))

# ================= НАСТРОЙКИ =================

@bot.tree.command(name="setadmin")
async def setadmin(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Нет прав", ephemeral=True)
    set_setting("admin_role", role.id)
    await interaction.response.send_message(f"✅ Роль администрации: {role.name}")

@bot.tree.command(name="set_logs")
async def setlogs(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction): return
    set_setting("log_channel", channel.id)
    await interaction.response.send_message("✅ Канал логов установлен")

@bot.tree.command(name="set_norma")
async def setnorma(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction): return
    set_setting("norma", amount)
    await interaction.response.send_message(f"✅ Норма: {amount}")

# ================= МОДЕРАЦИЯ =================

@bot.tree.command(name="mute")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    if not is_admin(interaction): return
    await user.timeout(timedelta(minutes=minutes), reason=reason)
    add_points(interaction.user.id)
    await interaction.response.send_message("🔇 Мут выдан")
    await log(interaction.guild, f"🔇 {interaction.user.mention} замутил {user.mention} | {reason}")

@bot.tree.command(name="unmute")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction): return
    await user.timeout(None)
    add_points(interaction.user.id)
    await interaction.response.send_message("🔊 Мут снят")

@bot.tree.command(name="warn")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction): return
    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (user.id, reason))
    conn.commit()
    add_points(interaction.user.id)
    await interaction.response.send_message("⚠️ Варн выдан")

@bot.tree.command(name="unwarn")
async def unwarn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction): return
    cursor.execute("DELETE FROM warns WHERE user_id = ? AND reason = ?", (user.id, reason))
    conn.commit()
    add_points(interaction.user.id)
    await interaction.response.send_message("✅ Варн снят")

@bot.tree.command(name="warns")
async def warns(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT reason FROM warns WHERE user_id = ?", (user.id,))
    data = cursor.fetchall()
    text = "\n".join([f"• {r[0]}" for r in data]) if data else "Нет варнов"
    await interaction.response.send_message(f"⚠️ Варны {user.mention}:\n{text}")

@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction): return
    await user.ban(reason=reason)
    add_points(interaction.user.id)
    await interaction.response.send_message("🔨 Бан выдан")

@bot.tree.command(name="unban")
async def unban(interaction: discord.Interaction, user_id: int):
    if not is_admin(interaction): return
    user = await bot.fetch_user(user_id)
    await interaction.guild.unban(user)
    add_points(interaction.user.id)
    await interaction.response.send_message("♻️ Бан снят")

# ================= ПРОЧЕЕ =================

@bot.tree.command(name="points")
async def points(interaction: discord.Interaction, user: discord.Member, action: str, amount: int):
    if not is_admin(interaction): return
    if action == "выдать":
        add_points(user.id, amount)
    elif action == "снять":
        add_points(user.id, -amount)
    await interaction.response.send_message("⭐ Баллы обновлены")

@bot.tree.command(name="profile")
async def profile(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT value FROM points WHERE user_id = ?", (user.id,))
    p = cursor.fetchone()
    p = p[0] if p else 0
    await interaction.response.send_message(f"👤 Профиль {user.mention}\n⭐ Баллы: {p}")

@bot.tree.command(name="table")
async def table(interaction: discord.Interaction):
    role_id = get_setting("admin_role")
    norma = get_setting("norma") or 0
    role = interaction.guild.get_role(role_id)
    if not role:
        return

    text = ""
    for m in role.members:
        cursor.execute("SELECT value FROM points WHERE user_id = ?", (m.id,))
        p = cursor.fetchone()
        p = p[0] if p else 0
        text += f"{m.mention} — {p}/{norma}\n"

    await interaction.response.send_message(embed=discord.Embed(title="📊 Таблица", description=text))

bot.run(TOKEN)
