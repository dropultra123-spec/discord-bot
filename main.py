import discord
from discord import app_commands
from discord.ext import tasks
import sqlite3
import os
from datetime import timedelta, datetime

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

# ================= БАЗА ДАННЫХ =================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS accepted (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS points (user_id INTEGER PRIMARY KEY, value INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
# Новые таблицы для настроек
cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value INTEGER)")
conn.commit()

# Вспомогательные функции для настроек
def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    return res[0] if res else None

def set_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

# ================= КЛИЕНТ =================

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        try:
            await self.tree.sync()
            print(f"Бот запущен: {self.user}")
            if not self.check_norma_task.is_running():
                self.check_norma_task.start()
        except Exception as e:
            print("Ошибка синхронизации:", e)

    # Цикл проверки нормы (раз в неделю)
    @tasks.loop(hours=168) 
    async def check_norma_task(self):
        norma = get_setting("norma")
        admin_role_id = get_setting("admin_role")
        log_channel_id = get_setting("log_channel")

        if not norma or not admin_role_id:
            return

        for guild in self.guilds:
            role = guild.get_role(admin_role_id)
            if not role: continue
            
            log_channel = guild.get_channel(log_channel_id)

            for member in role.members:
                cursor.execute("SELECT value FROM points WHERE user_id = ?", (member.id,))
                res = cursor.fetchone()
                current_points = res[0] if res else 0

                if current_points < norma:
                    # Уведомление в логи
                    if log_channel:
                        await log_channel.send(f"⚠️ **Нарушение нормы:** {member.mention} не выполнил норму ({current_points}/{norma})")
                    # Уведомление в ЛС
                    try:
                        await member.send(f"Вы не выполнили недельную норму отчетов. Ваш результат: {current_points}. Требовалось: {norma}.")
                    except:
                        pass
            
            # Сброс баллов после проверки (новая неделя)
            cursor.execute("UPDATE points SET value = 0")
            conn.commit()

bot = Bot()

# ================= ПРОВЕРКИ =================

def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

async def send_log(guild, message):
    log_id = get_setting("log_channel")
    if log_id:
        channel = guild.get_channel(log_id)
        if channel:
            await channel.send(f"📑 **LOG:** {message}")

def add_points(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO points VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE points SET value = value + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ================= НАСТРОЙКИ (ТОЛЬКО АДМИН) =================

@bot.tree.command(name="set_logs", description="Выбрать канал для логов")
async def set_logs(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_admin(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
    set_setting("log_channel", channel.id)
    await interaction.response.send_message(f"Канал логов установлен: {channel.mention}")

@bot.tree.command(name="set_norma", description="Установить недельную норму баллов")
async def set_norma(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
    set_setting("norma", amount)
    await interaction.response.send_message(f"Недельная норма установлена: {amount} баллов.")

@bot.tree.command(name="set_admin_role", description="Выбрать роль администрации для таблицы")
async def set_admin_role(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction): return await interaction.response.send_message("Нет прав.", ephemeral=True)
    set_setting("admin_role", role.id)
    await interaction.response.send_message(f"Роль администрации для таблицы: {role.name}")

# ================= ТАБЛИЦА С НОРМОЙ =================

@bot.tree.command(name="table", description="Таблица баллов и нормы")
async def table(interaction: discord.Interaction):
    admin_role_id = get_setting("admin_role")
    norma = get_setting("norma") or 0
    
    if not admin_role_id:
        return await interaction.response.send_message("Роль администрации не настроена (/set_admin_role).")

    cursor.execute("SELECT user_id, value FROM points ORDER BY value DESC")
    data = cursor.fetchall()
    
    embed = discord.Embed(title="📊 Статистика администрации", color=discord.Color.green())
    
    text = ""
    admin_role = interaction.guild.get_role(admin_role_id)
    
    # Показываем только тех, у кого есть выбранная роль
    if admin_role:
        for member in admin_role.members:
            # Ищем баллы в базе
            user_points = next((v for u, v in data if u == member.id), 0)
            status = "✅" if user_points >= norma else "❌"
            text += f"{status} {member.mention} — **{user_points}** / {norma}\n"
    
    embed.description = text if text else "Никого нет в списке."
    await interaction.response.send_message(embed=embed)

# ================= ОСТАЛЬНЫЕ КОМАНДЫ (БЕЗ UNBLACKLIST) =================

@bot.tree.command(name="mute", description="Выдать мут")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    # Тут логика как раньше
    await user.timeout(timedelta(minutes=minutes), reason=reason)
    add_points(interaction.user.id)
    await interaction.response.send_message(f"Мут выдан {user.name}")
    await send_log(interaction.guild, f"Администратор {interaction.user.mention} выдал мут {user.mention} на {minutes}м. Причина: {reason}")

@bot.tree.command(name="blacklist", description="Добавить в ЧС (без команды удаления)")
async def blacklist(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction): return await interaction.response.send_message("Нет прав.")
    cursor.execute("INSERT OR REPLACE INTO blacklist VALUES (?, ?)", (user.id, reason))
    conn.commit()
    await interaction.response.send_message("Пользователь в ЧС.")
    await send_log(interaction.guild, f"{interaction.user.mention} добавил {user.mention} в ЧЕРНЫЙ СПИСОК. Причина: {reason}")

# Добавьте остальные команды из предыдущего кода здесь (warn, list, accept и т.д.)

bot.run(TOKEN)
