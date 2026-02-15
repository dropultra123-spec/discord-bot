import discord
from discord import app_commands
import sqlite3
import os
from datetime import timedelta

# Получаем токен из переменных окружения
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
    conn.commit()

init_db()

# ================= КЛИЕНТ БОТА =================

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Команды регистрируются здесь, но синхронизируются в on_ready для надежности
        pass

    async def on_ready(self):
        # Синхронизация слеш-команд
        try:
            print("⏳ Синхронизация команд...")
            await self.tree.sync()
            print(f"✅ Команды синхронизированы. Бот: {self.user}")
        except Exception as e:
            print(f"❌ Ошибка синхронизации: {e}")

        activity = discord.Game(name="Detects Simulator")
        await self.change_presence(status=discord.Status.online, activity=activity)

bot = Bot()

# ================= ПРОВЕРКИ И ЛОГИКА =================

def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

def is_mod(interaction: discord.Interaction):
    if is_admin(interaction):
        return True
    cursor.execute("SELECT role_id FROM moderators")
    roles = [r[0] for r in cursor.fetchall()]
    return any(role.id in roles for role in interaction.user.roles)

def add_points_db(user_id, amount=1):
    cursor.execute("INSERT OR IGNORE INTO points (user_id, value) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE points SET value = value + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# ================= КОМАНДЫ: КАНДИДАТЫ =================

@bot.tree.command(name="accept", description="Добавить кандидата в список")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    
    cursor.execute("INSERT OR IGNORE INTO accepted VALUES (?)", (user.id,))
    conn.commit()
    try:
        await user.send("📩 Вы прошли первый этап отбора. Ожидайте обзвона!")
    except:
        pass
    await interaction.response.send_message(f"✅ {user.display_name} добавлен в список.")

@bot.tree.command(name="list", description="Список кандидатов")
async def list_users(interaction: discord.Interaction):
    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()
    if not data:
        return await interaction.response.send_message("📭 Список пуст.")
    
    lines = []
    for i, (uid,) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        lines.append(f"**{i}.** {member.mention if member else f'ID: {uid}'}")
    
    await interaction.response.send_message("📋 **Кандидаты:**\n" + "\n".join(lines))

@bot.tree.command(name="call", description="Начать обзвон (рассылка)")
async def call(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    
    cursor.execute("SELECT user_id FROM accepted")
    data = cursor.fetchall()
    if not data:
        return await interaction.response.send_message("Список пуст.")

    await interaction.response.send_message("📢 Начинаю рассылку...")
    for (uid,) in data:
        member = interaction.guild.get_member(uid)
        if member:
            try:
                await member.send("📞 Проводится обзвон. Зайдите в канал «Зал ожидания».")
            except:
                pass
    
    cursor.execute("DELETE FROM accepted")
    conn.commit()
    await interaction.edit_original_response(content="✅ Обзвон объявлен, список очищен.")

# ================= КОМАНДЫ: МОДЕРАЦИЯ =================

@bot.tree.command(name="setmod", description="Добавить роль модератора")
async def set_mod(interaction: discord.Interaction, role: discord.Role):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    cursor.execute("INSERT OR IGNORE INTO moderators VALUES (?)", (role.id,))
    conn.commit()
    await interaction.response.send_message(f"🛡️ Роль {role.name} теперь считается модераторской.")

@bot.tree.command(name="mute", description="Замутить пользователя")
async def mute(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    
    await user.timeout(timedelta(minutes=minutes), reason=reason)
    add_points_db(interaction.user.id, 1) # Даем балл модератору
    await interaction.response.send_message(f"🔇 {user.mention} замучен на {minutes} мин. Причина: {reason}")

@bot.tree.command(name="warn", description="Выдать варн")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_mod(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    
    cursor.execute("INSERT INTO warns (user_id, reason) VALUES (?, ?)", (user.id, reason))
    conn.commit()
    add_points_db(interaction.user.id, 1)
    await interaction.response.send_message(f"⚠️ {user.mention} получил варн. Причина: {reason}")

@bot.tree.command(name="warns", description="Посмотреть варны пользователя")
async def warns_list(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT reason FROM warns WHERE user_id = ?", (user.id,))
    data = cursor.fetchall()
    if not data:
        return await interaction.response.send_message(f"У {user.display_name} нет варнов.")
    
    text = f"📜 **Варны {user.display_name}:**\n"
    for i, (reason,) in enumerate(data, 1):
        text += f"{i}. {reason}\n"
    await interaction.response.send_message(text)

# ================= КОМАНДЫ: БАЛЛЫ И ТАБЛИЦА =================

@bot.tree.command(name="table", description="Таблица баллов администрации")
async def table(interaction: discord.Interaction):
    cursor.execute("SELECT user_id, value FROM points ORDER BY value DESC LIMIT 10")
    data = cursor.fetchall()
    if not data:
        return await interaction.response.send_message("📊 Таблица пока пуста.")

    embed = discord.Embed(title="📊 Топ администрации по баллам", color=discord.Color.blue())
    description = ""
    for i, (uid, value) in enumerate(data, 1):
        member = interaction.guild.get_member(uid)
        name = member.mention if member else f"ID: {uid}"
        description += f"**{i}.** {name} — `{value}` баллов\n"
    
    embed.description = description
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="addpoints", description="Выдать баллы пользователю")
async def addpoints(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    add_points_db(user.id, amount)
    await interaction.response.send_message(f"⭐ {user.mention} получил `{amount}` баллов.")

# ================= ЧЕРНЫЙ СПИСОК (ЧС) =================

@bot.tree.command(name="blacklist", description="Добавить в ЧС")
async def blacklist_add(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    cursor.execute("INSERT OR REPLACE INTO blacklist VALUES (?, ?)", (user.id, reason))
    conn.commit()
    await interaction.response.send_message(f"🚫 {user.mention} занесен в черный список. Причина: {reason}")

@bot.tree.command(name="check_blacklist", description="Проверить пользователя в ЧС")
async def blacklist_check(interaction: discord.Interaction, user: discord.Member):
    cursor.execute("SELECT reason FROM blacklist WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    if res:
        await interaction.response.send_message(f"🛑 Пользователь в ЧС. Причина: {res[0]}")
    else:
        await interaction.response.send_message("✅ Пользователя нет в черном списке.")

# Запуск
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Ошибка: TOKEN не задан!")
