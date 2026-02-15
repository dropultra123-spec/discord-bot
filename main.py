import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
import os
from datetime import timedelta

# Токен из переменных окружения
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

# ================= БАЗА ДАННЫХ =================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS accepted (user_id INTEGER PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS points (user_id INTEGER PRIMARY KEY, value INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
    conn.commit()

init_db()

def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    return res[0] if res else None

def set_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

# ================= КЛИЕНТ БОТА =================

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        try:
            await self.tree.sync()
            print(f"✅ Бот запущен: {self.user}")
            if not self.check_norma_weekly.is_running():
                self.check_norma_weekly.start()
        except Exception as e:
            print(f"❌ Ошибка синхронизации: {e}")

        activity = discord.Game(name="Admin System 2026")
        await self.change_presence(status=discord.Status.online, activity=activity)

    @tasks.loop(hours=168) # Проверка раз в неделю
    async def check_norma_weekly(self):
        norma = get_setting("norma")
        role_id = get_setting("admin_role")
        log_id = get_setting("log_channel")
        if not norma or not role_id: return

        for guild in self.guilds:
            role = guild.get_role(role_id)
            log_chan = guild.get_channel(log_id)
            if not role: continue

            for member in role.members:
                cursor.execute("SELECT value FROM points WHERE user_id = ?", (member.id,))
                res = cursor.fetchone()
                points = res[0] if res else 0

                if points < norma:
                    if log_chan:
                        await log_chan.send(f"⚠️ **Норма не выполнена:** {member.mention} ({points}/{norma})")
                    try:
                        await member.send(f"Вы не выполнили недельную норму ({points}/{norma}).")
                    except: pass
            
            cursor.execute("UPDATE points SET value = 0")
            conn.commit()

bot = Bot()

# ================= ПРОВЕРКИ И ЛОГИКА =================

def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

async def send_to_logs(guild, text):
    log_id = get_setting("log_channel")
    if log_id:
        channel = guild.get_channel(log_id)
        if channel:
            embed = discord.Embed(description=text, color=discord.Color.orange())
            await channel.send(embed=embed)

def add_points_db(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO points (user_id, value) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE points SET value = value + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ================= КОМАНДЫ НАСТРОЕК =================

@bot.tree.command(name="set_logs", description="Установить канал для логов")
async def set_logs(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    set_setting("log_channel", channel.id)
    await interaction.response.send_message(f"✅ Логи теперь приходят в {channel.mention}")

@bot.tree.command(name="set_norma", description="Установить недельную норму баллов")
async def set_norma(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    set_setting("norma", amount)
    await interaction.response.send_message(f"✅ Недельная норма установлена на `{amount}` баллов.")

@bot.tree.command(name="set_admin_role", description="Установить роль администрации")
async def set_admin_role(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    set_setting("admin_role", role.id)
    await interaction.response.send_message(f"✅ Роль администрации: **{role.name}**")

@bot.tree.command(name="admin", description="Выдать роль администрации пользователю")
async def admin_give(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    role_id = get_setting("admin_role")
    if not role_id: return await interaction.response.send_message("❌ Роль не настроена. Используйте `/set_admin_role`.")
    role = interaction.guild.get_role(role_id)
    await user.add_roles(role)
    await interaction.response.send_message(f"👑 Пользователю {user.mention} выдана роль {role.name}")

# ================= МОДЕРАЦИЯ И ЧС =================

@bot.tree.command(name="mute", description="Замутить пользователя")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    await user.timeout(timedelta(minutes=minutes), reason=reason)
    add_points_db(interaction.user.id, 1)
    await interaction.response.send_message(f"🔇 {user.mention} замучен. Причина: {reason}")
    await send_to_logs(interaction.guild, f"🔇 {interaction.user.mention} замутил {user.mention} на {minutes}м.\nПричина: {reason}")

@bot.tree.command(name="blacklist", description="Добавить в ЧС")
async def blacklist_add(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    cursor.execute("INSERT OR REPLACE INTO blacklist VALUES (?, ?)", (user.id, reason))
    conn.commit()
    await interaction.response.send_message(f"🚫 {user.mention} в ЧС. Причина: {reason}")
    await send_to_logs(interaction.guild, f"🚫 {interaction.user.mention} добавил {user.mention} в ЧС.\nПричина: {reason}")

@bot.tree.command(name="unblacklist", description="Удалить из ЧС")
async def unblacklist(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction): return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    cursor.execute("DELETE FROM blacklist WHERE user_id = ?", (user.id,))
    conn.commit()
    await interaction.response.send_message(f"✅ {user.mention} удален из ЧС.")

# ================= ТАБЛИЦА =================

@bot.tree.command(name="table", description="Таблица баллов и нормы")
async def table(interaction: discord.Interaction):
    role_id = get_setting("admin_role")
    norma = get_setting("norma") or 0
    if not role_id: return await interaction.response.send_message("❌ Роль администрации не настроена.")

    role = interaction.guild.get_role(role_id)
    embed = discord.Embed(title="📊 Статистика Администрации", color=discord.Color.blue())
    
    desc = ""
    for member in role.members:
        cursor.execute("SELECT value FROM points WHERE user_id = ?", (member.id,))
        res = cursor.fetchone()
        p = res[0] if res else 0
        status = "✅" if p >= norma else "❌"
        desc += f"{status} {member.mention} — `{p}/{norma}` баллов\n"
    
    embed.description = desc if desc else "В данной роли никого нет."
    await interaction.response.send_message(embed=embed)

# ================= ВСЕ ОСТАЛЬНЫЕ СТАРЫЕ КОМАНДЫ =================

@bot.tree.command(name="accept", description="Принять кандидата")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction): return await interaction.response.send_message("❌")
    cursor.execute("INSERT OR IGNORE INTO accepted VALUES (?)", (user.id,))
    conn.commit()
    try: await user.send("📩 Вы приняты на этап обзвона.")
    except: pass
    await interaction.response.send_message(f"✅ {user.display_name} в списке.")

@bot.tree.command(name="list", description="Список кандидатов")
async def list_cands(interaction: discord.Interaction):
    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()
    text = "\n".join([f"<@{u[0]}>" for u in data]) if data else "Пусто"
    await interaction.response.send_message(f"📋 Кандидаты:\n{text}")

@bot.tree.command(name="call", description="Обзвон")
async def call_cands(interaction: discord.Interaction):
    if not is_admin(interaction): return
    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()
    for (uid,) in data:
        m = interaction.guild.get_member(uid)
        if m: 
            try: await m.send("📞 Зайдите в канал «Зал ожидания».")
            except: pass
    cursor.execute("DELETE FROM accepted")
    conn.commit()
    await interaction.response.send_message("📢 Рассылка завершена.")

@bot.tree.command(name="warn", description="Выдать варн")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (user.id, reason))
    conn.commit()
    add_points_db(interaction.user.id, 1)
    await interaction.response.send_message(f"⚠️ Варн {user.mention}. Причина: {reason}")

@bot.tree.command(name="addpoints", description="Выдать баллы")
async def addp(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction): return
    add_points_db(user.id, amount)
    await interaction.response.send_message(f"⭐ {user.mention} +{amount} баллов.")

bot.run(TOKEN)

