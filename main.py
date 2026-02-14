import discord
from discord import app_commands
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.accepted_users = []

    async def setup_hook(self):
        await self.tree.sync()

client = MyClient()

# Проверка на администратора
def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator

# Команда /принят
@client.tree.command(name="принят", description="Добавить игрока в список принятых")
@app_commands.describe(user="Выбранный игрок")
async def accept(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ У вас нет прав администратора.", ephemeral=True)
        return

    try:
        await user.send(
            "Вы успешно прошли первый этап отбора в администрацию проекта.\n"
            "Пожалуйста, ожидайте звонка и дальнейших инструкций."
        )
    except:
        pass

    client.accepted_users.append(user)
    await interaction.response.send_message(f"✅ {user.mention} добавлен в список принятых.")

# Команда /список
@client.tree.command(name="список", description="Показать список принятых")
async def list_users(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ У вас нет прав администратора.", ephemeral=True)
        return

    if not client.accepted_users:
        await interaction.response.send_message("Список пуст.")
        return

    text = "📋 **Принятые:**\n"
    for i, user in enumerate(client.accepted_users, 1):
        text += f"{i}. {user.mention}\n"

    await interaction.response.send_message(text)

# Команда /ресетсписок
@client.tree.command(name="ресетсписок", description="Очистить список принятых")
async def reset_list(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ У вас нет прав администратора.", ephemeral=True)
        return

    client.accepted_users.clear()
    await interaction.response.send_message("🗑 Список принятых очищен.")

# 🔥 Новая команда /обзвон
@client.tree.command(name="обзвон", description="Начать обзвон кандидатов")
async def call_users(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ У вас нет прав администратора.", ephemeral=True)
        return

    if not client.accepted_users:
        await interaction.response.send_message("⚠ Список пуст.")
        return

    message_text = (
        "В настоящее время проводится обзвон кандидатов в администрацию проекта.\n"
        "Пожалуйста, зайдите в голосовой чат и перейдите в канал «Зал ожидания».\n"
        "Ожидайте дальнейших инструкций."
    )

    for user in client.accepted_users:
        try:
            await user.send(message_text)
        except:
            pass

    client.accepted_users.clear()

    await interaction.response.send_message("📞 Обзвон начат. Всем кандидатам отправлено уведомление. Список очищен.")

client.run(TOKEN)
