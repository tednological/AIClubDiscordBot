import discord
from discord.ext import commands
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.messages = True
intents.message_content = True  # Required to read message content

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

load_dotenv()

MERLIN_BOT_TOKEN = os.getenv("MERLIN_BOT_TOKEN")
print(MERLIN_BOT_TOKEN)
# Missions data with 'required_level' completely removed
missions = [
    {
        "name": "The Novice's Tome of Pythonic Whisperings",
        "description": "Learn the arcane language of Python and inscribe a simple spell.",
        "materials": [
            "https://www.youtube.com/watch?v=nCDZ1zvoZg0"
        ],
        "completion_deed": "Screenshot and present a script that prints 'Greetings, traveler!'",
        "xp_reward": 50
    },
    {
        "name": "Summary Statistics of Magical Moving Pictures",
        "description": "Use your knowledge of the Pythonic script to decipher an arcane dataset.",
        "materials": [
            "https://www.youtube.com/watch?v=DkjCaAMBGWM",
            "https://www.kaggle.com/datasets/fernandogarciah24/top-1000-imdb-dataset"
        ],
        "completion_deed": "Screenshot and present a script that prints out the head and summary statistics of the \"Runtime\" column of the given dataset.",
        "xp_reward": 50
    },
    {
        "name": "Illuminating the Graphical Leylines",
        "description": "Shape mystical graphs from data using Matplotlib’s visualization spells.",
        "materials": [
            "https://matplotlib.org/stable/tutorials/introductory/quick_start.html",
            "https://www.youtube.com/watch?v=3Xc3CA655Y4"
        ],
        "completion_deed": "Produce a scatter plot and a histogram from your purified dataset.",
        "xp_reward": 75
    },
    {
        "name": "Scrying SQL Databases",
        "description": "Speak the arcane words of SQL to summon the proper information.",
        "materials": [
            "https://www.w3schools.com/sql/default.asp",
            "https://www.youtube.com/watch?v=kbKty5ZVKMY"
        ],
        "completion_deed": "Construct SQL statements for the following situations. You have gained access to an evil lich's databased named 'DOOM' that contains all of the information about its minions. First, find out how many opponents you face by returning the number of entries in the MINON_ID column. Second, gauge the strength of the lich's minions by returning the list of minions that have at least a 7 in the 'Power' column. Finally, find the most powerful minion of the lich by returning the minion with the highest 'Power' in the 'DOOM' database.",
        "xp_reward": 75
    },
    {
        "name": "Potion Brewing and Preprocessing",
        "description": "Recitfy the missing data from your alchemical inventory.",
        "materials": [
            "https://www.freecodecamp.org/news/data-cleaning-and-preprocessing-with-pandasbdvhj/#heading-how-to-load-the-dataset",
            "https://www.geeksforgeeks.org/data-processing-with-pandas/",
            "https://www.geeksforgeeks.org/how-to-scale-pandas-dataframe-columns/",
            "https://drive.google.com/file/d/1PrjT68XkRLssRE4DN03aMBwhi2VQ9XsX/view?usp=sharing"
        ],
        "completion_deed": "Complete the following tasks: 1. Impute the missing values of the PurityLevel and Quantity column with the mean or average. 2. Filter out the Spoiled ingredients. 3. Scale PurityLevel and Quantity to a range of 0 to 1 for consistent potion preparation.",
        "xp_reward": 75
    }
]

# Define badges grouping missions together
badges = [
    {
        "name": "Arcane Apprentice",
        "description": "Awarded for mastering the arcane arts by completing the introductory quests.",
        "missions": [
            "The Novice's Tome of Pythonic Whisperings",
            "Summary Statistics of Magical Moving Pictures",
            "Illuminating the Graphical Leylines"
        ]
    },
    {
        "name": "Data Diviner",
        "description": "Awarded for divining the secrets of data by completing advanced quests.",
        "missions": [
            "Scrying SQL Databases",
            "Potion Brewing and Preprocessing"
        ]
    }
]

# Set up SQLite database connection
conn = sqlite3.connect('bot_data.db')
cursor = conn.cursor()

# Create tables for users, completed quests, and awarded badges
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS completed_quests (
    user_id INTEGER,
    quest_name TEXT,
    PRIMARY KEY (user_id, quest_name),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS awarded_badges (
    user_id INTEGER,
    badge_name TEXT,
    PRIMARY KEY (user_id, badge_name),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
)
''')

# Create attendance table with xp_awarded field
cursor.execute('''
CREATE TABLE IF NOT EXISTS attendance (
    meeting_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    xp_awarded BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (meeting_id, user_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
)
''')

conn.commit()

# Functions for user XP management and quest tracking
def get_user_xp(user_id):
    cursor.execute('SELECT xp FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute('INSERT INTO users (user_id, xp) VALUES (?, ?)', (user_id, 0))
        conn.commit()
        return 0
    return result[0]

def set_user_xp(user_id, xp):
    cursor.execute('''
        INSERT INTO users (user_id, xp) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET xp=excluded.xp
    ''', (user_id, xp))
    conn.commit()

def user_completed_quests(user_id):
    cursor.execute('SELECT quest_name FROM completed_quests WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    return [row[0] for row in rows]

def user_awarded_badges(user_id):
    cursor.execute('SELECT badge_name FROM awarded_badges WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    return [row[0] for row in rows]

# Simple level thresholds (kept for display in status, if y'all fancy)
level_thresholds = [
    (1, 50),
    (2, 125),
    (3, 275)
]

def get_level(xp):
    level = 0
    for lvl, threshold in level_thresholds:
        if xp >= threshold:
            level = lvl
        else:
            break
    return level

# Function to send a DM or fallback to channel
async def send_dm_or_channel_fallback(ctx, content=None, embed=None):
    try:
        if embed:
            await ctx.author.send(embed=embed)
        else:
            await ctx.author.send(content=content)
    except discord.Forbidden:
        if embed:
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"{ctx.author.mention}, I couldn’t send you a DM. Please enable DMs and try again.\n{content if content else ''}")

# Function to check and award badges
def check_badges(user_id):
    completed = set(user_completed_quests(user_id))
    awarded = set(user_awarded_badges(user_id))
    newly_awarded = []
    for badge in badges:
        badge_name = badge["name"]
        required_missions = set(badge["missions"])
        # Check if user has completed all missions in this badge and hasn't been awarded it yet
        if required_missions.issubset(completed) and badge_name not in awarded:
            cursor.execute('INSERT INTO awarded_badges (user_id, badge_name) VALUES (?, ?)', (user_id, badge_name))
            conn.commit()
            newly_awarded.append(badge_name)
    return newly_awarded

@bot.event
async def on_ready():
    print(f'Bot is online as {bot.user}.')

# Command to list all missions
@bot.command()
async def missions_list(ctx):
    user_id = ctx.author.id
    completed = user_completed_quests(user_id)
    embed = discord.Embed(title="Available Quests", color=discord.Color.gold())
    # List all missions, no level restrictions here
    for mission in missions:
        mission_name_display = mission["name"] if mission["name"] not in completed else f"~~{mission['name']}~~"
        embed.add_field(
            name=mission_name_display,
            value=f"**Description:** {mission['description']}\n**Reward:** {mission['xp_reward']} XP",
            inline=False
        )
    await send_dm_or_channel_fallback(ctx, embed=embed)

# Command to start or complete a mission (completion is auto-approved)
@bot.command()
async def mission(ctx, action: str, *, mission_name: str):
    user_id = ctx.author.id
    if not mission_name:
        await send_dm_or_channel_fallback(ctx, "Please specify the mission name, partner.")
        return
    found_mission = None
    for m in missions:
        if m["name"].lower() == mission_name.lower():
            found_mission = m
            break
    if not found_mission:
        await send_dm_or_channel_fallback(ctx, "No such mission exists. Check that mission name and try again, ya hear?")
        return
    if action.lower() == "start":
        materials_text = "\n".join(found_mission["materials"])
        msg = (
            f"**{found_mission['name']}** has been started!\n"
            f"**Materials:**\n{materials_text}\n"
            f"**Completion Deed:** {found_mission['completion_deed']}"
        )
        await send_dm_or_channel_fallback(ctx, msg)
    elif action.lower() == "complete":
        completed = user_completed_quests(user_id)
        if found_mission["name"] in completed:
            await send_dm_or_channel_fallback(ctx, f"You've already completed **{found_mission['name']}**.")
            return
        # Directly mark the mission as complete and award XP
        cursor.execute('INSERT INTO completed_quests (user_id, quest_name) VALUES (?, ?)', (user_id, found_mission["name"]))
        conn.commit()
        current_xp = get_user_xp(user_id)
        new_xp = current_xp + found_mission["xp_reward"]
        set_user_xp(user_id, new_xp)
        await send_dm_or_channel_fallback(
            ctx, 
            f"Congratulations! Your completion of **{found_mission['name']}** has been recorded! You gained {found_mission['xp_reward']} XP and now have {new_xp} XP."
        )
        # Check for badge awards after mission completion and announce 'em publicly
        new_badges = check_badges(user_id)
        if new_badges:
            badges_text = ", ".join(new_badges)
            await ctx.send(f"Yeehaw! {ctx.author.mention}, you've earned the following badge(s): {badges_text}")

# Command to show current XP
@bot.command()
async def xp(ctx):
    user_id = ctx.author.id
    user_current_xp = get_user_xp(user_id)
    await send_dm_or_channel_fallback(ctx, f"You currently have {user_current_xp} XP.")

# Command to display user status
@bot.command()
async def status(ctx):
    user_id = ctx.author.id
    user_current_xp = get_user_xp(user_id)
    user_level = get_level(user_current_xp)
    completed = user_completed_quests(user_id)
    awarded = user_awarded_badges(user_id)
    completed_list = ", ".join(completed) if completed else "None"
    badges_list = ", ".join(awarded) if awarded else "None"
    msg = (
        f"**Your Questing Status:**\n"
        f"**Level:** {user_level}\n"
        f"**Completed Quests:** {completed_list}\n"
        f"**XP:** {user_current_xp}\n"
        f"**Badges Earned:** {badges_list}"
    )
    await send_dm_or_channel_fallback(ctx, msg)

# Command to display a simple roadmap of missions
@bot.command()
async def roadmap(ctx):
    embed = discord.Embed(title="Quest Roadmap", description="List of all available missions", color=discord.Color.blue())
    for mission in missions:
        embed.add_field(name=mission["name"], value=f"Reward: {mission['xp_reward']} XP", inline=False)
    await send_dm_or_channel_fallback(ctx, embed=embed)

# Command to list awarded badges for a user
@bot.command()
async def badges(ctx, user: discord.Member = None):
    # Allow officers to view other users' badges; otherwise, show own badges
    if user is None:
        user = ctx.author
    awarded = user_awarded_badges(user.id)
    if awarded:
        badges_list = ", ".join(awarded)
        await ctx.send(f"{user.display_name} has earned the following badge(s): {badges_list}")
    else:
        await ctx.send(f"{user.display_name} hasn't earned any badges yet. Keep questin', partner!")

# Command to reset a user's quest data and XP (officer only)
@bot.command()
async def reset_user(ctx, user: discord.Member):
    officer_role = discord.utils.get(ctx.guild.roles, name="Officer")
    if officer_role not in ctx.author.roles:
        await ctx.send("You do not have permission to reset user data.")
        return
    user_id = user.id
    cursor.execute('DELETE FROM completed_quests WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM awarded_badges WHERE user_id = ?', (user_id,))
    conn.commit()
    set_user_xp(user_id, 0)
    await ctx.send(f"All quest history, badges, and XP for {user.mention} have been reset.")

# Attendance command: mark attendance and award XP for club meetings (officer-only)
@bot.command()
async def mark_attendance(ctx, meeting_id: str, xp_amount: int = 10):
    officer_role = discord.utils.get(ctx.guild.roles, name="Officer")
    if officer_role not in ctx.author.roles:
        await ctx.send("Y'all ain't got permission to mark attendance, partner!")
        return
    user_id = ctx.author.id
    date = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('SELECT xp_awarded FROM attendance WHERE meeting_id = ? AND user_id = ?', (meeting_id, user_id))
    result = cursor.fetchone()
    if result:
        await ctx.send(f"You've already been marked for attendance at meeting {meeting_id}.")
    else:
        cursor.execute('INSERT INTO attendance (meeting_id, user_id, date, xp_awarded) VALUES (?, ?, ?, ?)', (meeting_id, user_id, date, True))
        conn.commit()
        current_xp = get_user_xp(user_id)
        new_xp = current_xp + xp_amount
        set_user_xp(user_id, new_xp)
        await ctx.send(f"Attendance recorded and {xp_amount} XP awarded for {ctx.author.display_name} for meeting {meeting_id}.")

# Command to show attendance (officer-only)
@bot.command()
async def show_attendance(ctx, meeting_id: str = None, user: discord.Member = None):
    officer_role = discord.utils.get(ctx.guild.roles, name="Officer")
    if officer_role not in ctx.author.roles:
        await ctx.send("Y'all ain't got permission to view attendance, partner!")
        return
    if meeting_id:
        cursor.execute('SELECT user_id FROM attendance WHERE meeting_id = ?', (meeting_id,))
        attendees = cursor.fetchall()
        attendees_list = ', '.join([str(id[0]) for id in attendees])
        await ctx.send(f"Attendees for meeting {meeting_id}: {attendees_list}")
    elif user:
        cursor.execute('SELECT meeting_id FROM attendance WHERE user_id = ?', (user.id,))
        meetings_attended = cursor.fetchall()
        meetings_list = ', '.join([str(meeting[0]) for meeting in meetings_attended])
        await ctx.send(f"{user.display_name} has attended the following meetings: {meetings_list}")
    else:
        await ctx.send("Please specify a meeting ID or a user to view attendance.")

# Custom help command
@bot.command(name='help')
async def custom_help(ctx):
    embed = discord.Embed(
        title="Merlin's Guidance",
        description="Need some help, traveler? Here are the commands you seek:",
        color=discord.Color.blue()
    )
    embed.add_field(name="!missions_list", value="Lists all available missions. 🎯", inline=False)
    embed.add_field(name="!mission <start|complete> <mission_name>", value="Start or complete a mission. (Completion is auto-approved.) 📝", inline=False)
    embed.add_field(name="!xp", value="Shows your current XP. 📈", inline=False)
    embed.add_field(name="!status", value="Displays your current level, completed quests, XP, and badges earned. 🏆", inline=False)
    embed.add_field(name="!roadmap", value="Shows a roadmap of all missions. 🗺️", inline=False)
    embed.add_field(name="!badges [@User]", value="Lists the badges earned by you or another user.", inline=False)
    embed.add_field(name="!reset_user @User", value="Clears all quest history, badges, and resets XP for a user. (Officer-only)", inline=False)
    embed.add_field(name="!mark_attendance <meeting_id> [xp_amount]", value="Mark attendance for a meeting and gain XP. (Officer-only; Default XP is 10.)", inline=False)
    embed.add_field(name="!show_attendance [meeting_id|@User]", value="Shows attendance for a meeting or a user. (Officer-only)", inline=False)
    embed.add_field(name="!help", value="Displays this very help message. ❓", inline=False)
    embed.set_footer(text="Merlin the Wise • Your Guide in Questing")
    try:
        await ctx.author.send(embed=embed)
    except discord.Forbidden:
        await ctx.send(f"{ctx.author.mention}, I couldn’t send you a DM. Please enable DMs and try again.")

bot.run(MERLIN_BOT_TOKEN)
