from rapidfuzz import fuzz
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import random
import re
import asyncio
import aiohttp

load_dotenv() 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

question_desc = os.getenv("CUSTOM_QUESTION_DESC", "Get a lyrics question.")
answer_desc = os.getenv("CUSTOM_ANSWER_DESC", "Send in the next lyric.")
show_correct_answer_desc = os.getenv("CUSTOM_SHOW_CORRECT_ANSWER_DESC", "Show the correct answer.")
catalog_desc = os.getenv("CUSTOM_CATALOG_DESC", "Get catalog of songs.")
file_path = os.getenv("FILE_PATH", "")
deployment_url = os.getenv("DEPLOYMENT_URL", "")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

five_question_points = [15, 15, 20, 25, 25]
ten_question_points = [5, 5, 5, 5, 10, 10, 15, 15, 15, 15]
question_session = {
    "active": False,
    "guesses": {},
    "question": {},
    "last_activity": None,
    "locked": False,
}
tournament_session = {
    "active": False,
    "round": 0,
    "max_rounds": 10,
    "accepting_guesses": False,
    "participants": {},
    "question": None,
    "end_time": None,
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

async def keep_alive_ping():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(deployment_url) as resp:
                print(f"Pinged self ({resp.status})")
    except Exception as e:
        print(f"Ping failed: {e}")

@bot.tree.command(name="guessthenextlyric", description=question_desc)
async def guess_the_next_lyric(interaction: discord.Interaction):
    global question_session

    await keep_alive_ping()

    if question_session["locked"]:
        await interaction.response.send_message(f"A question is already in effect.")
        return

    question_session["active"] = True
    question_session["guesses"] = {}
    question_session["question"] = get_random_lyric()
    question_session["last_activity"] = datetime.now(timezone.utc)
    question_session["locked"] = True

    artist = question_session["question"]["artist"]
    song = question_session["question"]["song"]
    lyric = question_session["question"]["lyric"]
    
    await interaction.response.send_message(f"From {artist}'s {song}:\n{lyric}")

@bot.tree.command(name="hardguessthenextlyric", description=question_desc)
async def hard_guess_the_next_lyric(interaction: discord.Interaction):
    global question_session

    await keep_alive_ping()

    if question_session["locked"]:
        await interaction.response.send_message(f"A question is already in effect.")
        return

    question_session["active"] = True
    question_session["guesses"] = {}
    question_session["question"] = get_random_lyric()
    question_session["last_activity"] = datetime.now(timezone.utc)
    question_session["locked"] = True

    lyric = question_session["question"]["lyric"]
    
    await interaction.response.send_message(f"{lyric}")

@bot.tree.command(name="customguessthenextlyric", description=question_desc)
async def custom_guess_the_next_lyric(interaction: discord.Interaction, response: str):
    global question_session

    await keep_alive_ping()

    if question_session["locked"]:
        await interaction.response.send_message(f"A question is already in effect.")
        return

    question_session["active"] = True
    question_session["guesses"] = {}
    question_session["question"] = get_random_lyric(song=response)
    question_session["last_activity"] = datetime.now(timezone.utc)
    question_session["locked"] = True

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
            question_session["locked"] = False
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

    song = question_session["question"]["song"]
    artist = question_session["question"]["artist"]

    result = (
        f"**From {artist}'s _{song}_**\n"
        f"Correct answer was: **{question_session['question']['correct_answer']}**\n\n"
        + "\n".join(
            f"{'👑' if i == 1 else i}. {user} — {data['guess']} (score: {data['score']}%)"
            for i, (user, data) in enumerate(ranking, start=1)
        )
    )

    await interaction.response.send_message(result)
    
    question_session["last_activity"] = datetime.now(timezone.utc)
    question_session["locked"] = False

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
            elif self.page == 0:
                self.page = len(pages) - 1
            await self.update_message(interaction)

        @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
        async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page < len(pages) - 1:
                self.page += 1
            elif self.page == len(pages) - 1:
                self.page = 0
            await self.update_message(interaction)

    first_embed = discord.Embed(
        title="🎵 Song Catalog",
        description="\n".join(pages[0]) if pages else "No songs found.",
        color=discord.Color.blue()
    )
    first_embed.set_footer(text=f"Page 1/{len(pages)}")
    await interaction.response.send_message(embed=first_embed, view=CatalogView())

@bot.tree.command(name="start_tournament", description="Start a lyric guessing tournament")
@app_commands.choices(total_rounds=[
    app_commands.Choice(name="5", value=5),
    app_commands.Choice(name="10", value=10)
])
async def start_tournament(interaction: discord.Interaction, total_rounds: int):
    global tournament_session

    await keep_alive_ping()

    if tournament_session["active"]:
        await interaction.response.send_message("⚠️ A tournament is already running!", ephemeral=True)
        return

    tournament_session.update({
        "active": True,
        "round": 0,
        "participants": {},
        "max_rounds": total_rounds,
    })

    await interaction.response.send_message(f"🎶 Tournament starting! Get ready for {total_rounds} lyric challenges!")
    await run_tournament(interaction)

async def run_tournament(interaction: discord.Interaction):
    global tournament_session

    for round_num in range(1, tournament_session["max_rounds"] + 1):
        tournament_session["round"] = round_num
        tournament_session["accepting_guesses"] = True
        tournament_session["question"] = get_random_lyric()
        tournament_session["end_time"] = datetime.now(timezone.utc) + timedelta(seconds=60)

        lyric = tournament_session["question"]["lyric"]
        artist = tournament_session["question"]["artist"]
        song = tournament_session["question"]["song"]

        question_points = ten_question_points[round_num-1]
        if tournament_session["max_rounds"] == 5:
            question_points = five_question_points[round_num-1]

        await interaction.channel.send(
            f"🎤 **Round {round_num} / {tournament_session['max_rounds']}**\n"
            f"From {artist}'s _{song}_:\n> {lyric}\n\n"
            f"This question is worth {question_points} points!\n"
            "You have **60 seconds**! Use `/tournament_guess`!"
        )

        await asyncio.sleep(60)
        tournament_session["accepting_guesses"] = False

        await show_round_results(interaction)
        await asyncio.sleep(10)

    await show_final_leaderboard(interaction)
    tournament_session["active"] = False

@bot.tree.command(name="tournament_guess", description="Submit your lyric guess privately.")
async def guess(interaction: discord.Interaction, response: str):
    global tournament_session

    if not tournament_session["active"]:
        await interaction.response.send_message("❌ No active tournament.", ephemeral=True)
        return

    if not tournament_session.get("accepting_guesses", False):
        await interaction.response.send_message("Guessing is closed right now!", ephemeral=True)
        return

    now = datetime.now(timezone.utc)
    if now > tournament_session["end_time"]:
        await interaction.response.send_message("Guessing is closed right now!", ephemeral=True)
        return

    user = interaction.user
    correct = tournament_session["question"]["correct_answer"]
    score = score_guess(correct, response)

    user_data = tournament_session["participants"].setdefault(user, {"best_score": 0, "total_score": 0})
    if score > user_data["best_score"]:
        user_data["best_score"] = score

    await interaction.response.send_message(
        f"Score: {score}%\n"
        f"Best score this round: {user_data["best_score"]}%", ephemeral=True)
    await interaction.followup.send(f"{user} made a guess: {score}%")

async def show_round_results(interaction: discord.Interaction): 
    global tournament_session

    ranking = sorted(
        tournament_session["participants"].items(),
        key=lambda x: x[1]["best_score"],
        reverse=True
    )

    if not ranking:
        await interaction.channel.send("😅 No guesses this round!")
        return

    total_round_score = sum(data["best_score"] for _, data in ranking)
    round_num = tournament_session["round"]

    question_points = ten_question_points[round_num-1]
    if tournament_session["max_rounds"] == 5:
        question_points = five_question_points[round_num-1]

    result_lines = []
    for i, (user, data) in enumerate(ranking, start=1):
        contribution = 0
        if total_round_score > 0:
            contribution = round((data["best_score"] / total_round_score) * question_points, 2)

        data["total_score"] += contribution
        result_lines.append(
            f"{'👑' if i == 1 else i}. {user} — {data['best_score']}% -> {data['total_score']:.2f} pts (+{contribution:.2f})"
        )

        data["best_score"] = 0

    result_text = "\n".join(result_lines)

    await interaction.channel.send(
        f"**Round {tournament_session['round']} Results!**\n"
        f"Correct answer: {tournament_session['question']['correct_answer']}\n\n"
        f"{result_text}"
    )

async def show_final_leaderboard(interaction: discord.Interaction):
    global tournament_session
    ranking = sorted(
        tournament_session["participants"].items(),
        key=lambda x: x[1]["total_score"],
        reverse=True
    )

    result_lines = [
        f"{'👑' if i == 1 else i}. {user} — {data['total_score']:.2f} total points"
        for i, (user, data) in enumerate(ranking, start=1)
    ]
    result_text = "\n".join(result_lines)

    await interaction.channel.send(f"**Final Tournament Results!**\n{result_text}")

@bot.tree.command(name="get_lyrics", description="Get lyrics")
async def get_lyrics(interaction: discord.Interaction, song: str):
    global question_session
    global tournament_session

    await keep_alive_ping()

    if question_session["locked"] or tournament_session["active"]:
        await interaction.response.send_message(f"No cheating!")
        return
    
    song = to_snake_case(song)
    if f"{song}.txt" not in os.listdir(file_path):
        await interaction.response.send_message(f"Song does not exist in catalog.")
        return

    file = os.path.join(file_path, f"{song}.txt")

    with open(file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        lyrics = lines[2:]

    lines_per_page = 20
    pages = [
        lyrics[i:i + lines_per_page]
        for i in range(0, len(lyrics), lines_per_page)
    ]

    class CatalogView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.page = 0

        async def update_message(self, interaction: discord.Interaction):
            embed = discord.Embed(
                title=f"{song}",
                description="\n".join(pages[self.page]),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Page {self.page + 1}/{len(pages)}")
            await interaction.response.edit_message(embed=embed, view=self)

        @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
        async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page > 0:
                self.page -= 1
            elif self.page == 0:
                self.page = len(pages) - 1
            await self.update_message(interaction)

        @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
        async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page < len(pages) - 1:
                self.page += 1
            elif self.page == len(pages) - 1:
                self.page = 0
            await self.update_message(interaction)

    first_embed = discord.Embed(
        title=f"{song}",
        description="\n".join(pages[0]) if pages else "No lyrics found.",
        color=discord.Color.blue()
    )
    first_embed.set_footer(text=f"Page 1/{len(pages)}")
    await interaction.response.send_message(embed=first_embed, view=CatalogView())

keep_alive()
bot.run(DISCORD_TOKEN)
