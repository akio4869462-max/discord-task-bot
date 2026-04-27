import discord
import os
from dotenv import load_dotenv
import task_logic   # 追加
import study_logic  # 追加

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'{client.user} が起動しました。')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content

    # --- タスク管理系 ---
    if content.startswith('!add '):
        await message.channel.send(task_logic.add_task(content[5:]))

    elif content == '!list':
        await message.channel.send(task_logic.list_tasks())

    elif content.startswith('!done '):
        await message.channel.send(task_logic.complete_task(content[6:]))

    # --- 学習系 ---
    elif content == '!kiso':
        await message.channel.send(study_logic.get_kiso_quiz())

    elif content == '!math':
        await message.channel.send(study_logic.get_math_quiz())

    elif content.startswith('!kiso_add '):
        await message.channel.send(study_logic.add_kiso_word(content[10:]))

client.run(TOKEN)
