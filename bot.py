from rapidfuzz import fuzz
import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import random
import re

load_dotenv() 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

question_desc = os.getenv("CUSTOM_QUESTION_DESC", "Get a lyrics question.")
answer_desc = os.getenv("CUSTOM_ANSWER_DESC", "Send in the next lyric.")
show_correct_answer_desc = os.getenv("CUSTOM_SHOW_CORRECT_ANSWER_DESC", "Show the correct answer.")
catalog_desc = os.getenv("CUSTOM_CATALOG_DESC", "Get catalog of songs.")
file_path = os.getenv("FILE_PATH", "")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

question_session = {
    "active": False,
    "guesses": {},
    "question": {},
    "last_activity": None,
}

def to_snake_case(s: str) -> str:
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    s = s.strip('_')
    return s

def get_random_lyric(song: str | None = None) -> dict:
    if song is not None:
        song = to_snake_case(song)
        if f"{song}.txt" not in os.listdir(file_path):
            song = None

    if not song:
        files = [f for f in os.listdir(file_path) if os.path.isfile(os.path.join(file_path, f))]
        file = os.path.join(file_path, random.choice(files))
    else:
        file = os.path.join(file_path, f"{song}.txt")

    with open(file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

        song = lines[0]
        artist = lines[1]
        idx = random.randint(2, len(lines) - 2)
    
        lyric = lines[idx]
        correct_answer = lines[idx + 1]

    return{
        "song": song,
        "artist": artist,
        "lyric": lyric,
        "correct_answer": correct_answer,
    }

def score_guess(lyric: str, guess: str) -> float:
    lyric = lyric.lower()
    guess = guess.lower()

    base_score = fuzz.partial_ratio(lyric, guess) / 100.0

    len_ratio = len(guess) / len(lyric)
    if len_ratio < 1.0:
        base_score *= len_ratio

    return round(base_score * 100, 2)

app = Flask("")

@app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

@bot.tree.command(name="guessthenextlyric", description=question_desc)
async def guess_the_next_lyric(interaction: discord.Interaction):
    global question_session

    question_session["active"] = True
    question_session["guesses"] = {}
    question_session["question"] = get_random_lyric()
    question_session["last_activity"] = datetime.now(timezone.utc)

    artist = question_session["question"]["artist"]
    song = question_session["question"]["song"]
    lyric = question_session["question"]["lyric"]
    
    await interaction.response.send_message(f"From {artist}'s {song}:\n{lyric}")

@bot.tree.command(name="customguessthenextlyric", description=question_desc)
async def custom_guess_the_next_lyric(interaction: discord.Interaction, response: str):
    global question_session

    question_session["active"] = True
    question_session["guesses"] = {}
    question_session["question"] = get_random_lyric(song=response)
    question_session["last_activity"] = datetime.now(timezone.utc)

    artist = question_session["question"]["artist"]
    song = question_session["question"]["song"]
    lyric = question_session["question"]["lyric"]
    
    await interaction.response.send_message(f"From {artist}'s {song}:\n{lyric}")

@tasks.loop(minutes=5)
async def check_timeout():
    global question_session
    if question_session["active"]:
        if datetime.now(timezone.utc) - question_session["last_activity"] > timedelta(minutes=10):
            question_session["active"] = False
            question_session["question"] = None
            question_session["guesses"] = None
            question_session["last_activity"] = None
            print("Session ended due to inactivity.")

@bot.event
async def on_ready():
    check_timeout.start()
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="answer", description=answer_desc)
async def answer(interaction: discord.Interaction, response: str):
    global question_session

    user = interaction.user

    if not question_session["active"]:
        await interaction.response.send_message("❌ No active question.")
        return
    
    if user in question_session["guesses"]:
        await interaction.response.send_message("❌ You already made your guess.")
        return
    
    score = score_guess(question_session["question"]["correct_answer"], response)
    question_session["guesses"][user] = {
        "guess": response,
        "score": score
    }
    await interaction.response.send_message(f"Score: {score}%")
    
    question_session["last_activity"] = datetime.now(timezone.utc)

@bot.tree.command(name="showcorrectanswer", description=show_correct_answer_desc)
async def show_correct_answer(interaction: discord.Interaction):
    global question_session

    if not question_session["active"]:
        await interaction.response.send_message("❌ No active question.")
        return
    
    if not question_session["guesses"]:
        await interaction.response.send_message("❌ No guesses yet!")
        return
    
    ranking = sorted(
        question_session["guesses"].items(),
        key=lambda item: item[1]["score"],
        reverse=True
    )

    result = f"""
    Correct answer was: {question_session["question"]["correct_answer"]}
    {chr(10).join(
        f"{i}. {user} — {data['guess']} (score: {data['score']}%)"
        for i, (user, data) in enumerate(ranking, start=1)
    )}
    """

    await interaction.response.send_message(result)
    
    question_session["last_activity"] = datetime.now(timezone.utc)

@bot.tree.command(name="catalog", description=catalog_desc)
async def catalog(interaction: discord.Interaction):
    file_names = []
    for f in os.listdir(file_path): 
        if os.path.isfile(os.path.join(file_path, f)):
            name = f[:-4].replace("_", " ").title()
            file_names.append(name)

    file_names.sort()

    songs_per_page = 20
    pages = [
        file_names[i:i + songs_per_page]
        for i in range(0, len(file_names), songs_per_page)
    ]

    class CatalogView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.page = 0

        async def update_message(self, interaction: discord.Interaction):
            embed = discord.Embed(
                title="🎵 Song Catalog",
                description="\n".join(pages[self.page]),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Page {self.page + 1}/{len(pages)}")
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
        async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page > 0:
                self.page -= 1
                await self.update_message(interaction)

        @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
        async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page < len(pages) - 1:
                self.page += 1
                await self.update_message(interaction)

    first_embed = discord.Embed(
        title="🎵 Song Catalog",
        description="\n".join(pages[0]) if pages else "No songs found.",
        color=discord.Color.blue()
    )
    first_embed.set_footer(text=f"Page 1/{len(pages)}")
    await interaction.response.send_message(embed=first_embed, view=CatalogView())

keep_alive()
bot.run(DISCORD_TOKEN)
