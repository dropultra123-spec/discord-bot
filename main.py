import discord
from discord import app_commands
import sqlite3
import os
from datetime import timedelta

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True # Рекомендуется включить

# ================= БАЗА ДАННЫХ =================

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS accepted (user_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS moderators (role_id INTEGER PRIMARY KEY)")
cursor.execute("CREATE TABLE IF NOT EXISTS points (user_id INTEGER PRIMARY KEY, value INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS warns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reason TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)")
conn.commit()

# ================= КЛИЕНТ БОТА =================

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        # Создаем дерево команд
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Здесь мы просто подготавливаем данные, если нужно
        pass

    async def on_ready(self):
        # Синхронизация команд при запуске
        try:
            print("Синхронизация команд...")
            await self.tree.sync() # Глобальная синхронизация (может занять до 24ч, но обычно 1-2 мин)
            print(f"Команды синхронизированы! Бот: {self.user}")
        except Exception as e:
            print(f"Ошибка синхронизации: {e}")

        activity = discord.Game(name="Detects Simulator")
        await self.change_presence(status=discord.Status.online, activity=activity)

bot = Bot()

# ================= ПРОВЕРКИ =================

def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

def is_mod(interaction: discord.Interaction):
    if is_admin(interaction):
        return True
    cursor.execute("SELECT role_id FROM moderators")
    roles = [r[0] for r in cursor.fetchall()]
    return any(role.id in roles for role in interaction.user.roles)

def add_points(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO points (user_id, value) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE points SET value = value + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ================= КОМАНДЫ (CANDIDATES) =================

@bot.tree.command(name="accept", description="Добавить кандидата в список")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ У вас нет прав администратора.", ephemeral=True)

    cursor.execute("INSERT OR IGNORE INTO accepted VALUES (?)", (user.id,))
    conn.commit()

    try:
        await user.send("✅ Вы успешно прошли первый этап отбора. Ожидайте звонка.")
    except:
        pass

    await interaction.response.send_message(f"Кандидат {user.mention} добавлен в список.", ephemeral=True)

@bot.tree.command(name="list", description="Показать список всех кандидатов")
async def list_users(interaction: discord.Interaction):
    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()

    if not data:
        return await interaction.response.send_message("📭 Список кандидатов пуст.")

    text = "📋 **Список принятых кандидатов:**\n"
    for i, (uid,) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        text += f"{i}. {member.mention if member else f'ID: {uid}'}\n"

    await interaction.response.send_message(text)

@bot.tree.command(name="call", description="Начать обзвон и очистить список")
async def call(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()
    
    if not data:
        return await interaction.response.send_message("Список пуст, вызывать некого.")

    await interaction.response.defer() # Бот "думает", чтобы избежать таймаута

    for (uid,) in data:
        member = interaction.guild.get_member(uid)
        if member:
            try:
                await member.send("📞 Проводится обзвон кандидатов. Перейдите в голосовой канал «Зал ожидания».")
            except:
                continue

    cursor.execute("DELETE FROM accepted")
    conn.commit()

    await interaction.followup.send("📢 Обзвон начат. Все кандидаты уведомлены (у кого открыта ЛС), список очищен.")

# ================= МОДЕРАЦИЯ =================

@bot.tree.command(name="mute", description="Выдать временный мут")
@app_commands.describe(minutes="На сколько минут замутить", reason="Причина наказания")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("❌ У вас нет прав модератора.", ephemeral=True)

    try:
        duration = timedelta(minutes=minutes)
        await user.timeout(duration, reason=reason)
        add_points(interaction.user.id)
        await interaction.response.send_message(f"🤐 {user.mention} отправлен подумать на {minutes} мин. Причина: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)

@bot.tree.command(name="warn", description="Выдать предупреждение")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (user.id, reason))
    conn.commit()
    add_points(interaction.user.id)

    await interaction.response.send_message(f"⚠️ {user.mention} получил варн. Причина: {reason}")

# Запуск бота
if TOKEN:
    bot.run(TOKEN)
else:
    print("Ошибка: TOKEN не найден в переменных окружения!")

