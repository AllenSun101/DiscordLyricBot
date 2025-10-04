from rapidfuzz import fuzz
import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import random

load_dotenv() 

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

songs = os.getenv("SONG_LYRICS", [])
question_desc = os.getenv("CUSTOM_QUESTION_DESC", "Get a lyrics question.")
answer_desc = os.getenv("CUSTOM_ANSWER_DESC", "Send in the next lyric.")
show_correct_answer_desc = os.getenv("CUSTOM_SHOW_CORRECT_ANSWER_DESC", "Show the correct answer.")

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

def get_random_song_lyric(song: str) -> dict:
    with open(f"{song}.txt", "r", encoding="utf-8") as f:
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

def get_random_lyric() -> dict:
    # pick random file out of all names
    with open("song.txt", "r", encoding="utf-8") as f:
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

keep_alive()
bot.run(DISCORD_TOKEN)
