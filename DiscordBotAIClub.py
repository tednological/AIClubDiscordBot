import nextcord
from nextcord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiosqlite
import asyncio
from datetime import datetime
import smtplib
import ssl
from email_validator import validate_email, EmailNotValidError
import os
from email.message import EmailMessage
from dotenv import load_dotenv
import random
import os
from nextcord.ext.commands import cooldown, BucketType, CommandOnCooldown, MissingRole, BadArgument
import feedparser
import re
import openai
from openai import OpenAI

openai.api_key = os.getenv('OPENAI_API_KEY')
dotenv_path="/Users/theodorelieber/Desktop/Projects/.env"
load_dotenv()
client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
)

intents = nextcord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True  # Required to read message content
intents.members = True  # If you need member information


bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
scheduler = AsyncIOScheduler()

# Directory to store PDFs
PDF_STORAGE_PATH = 'pdfs'

# Ensure the directory exists
if not os.path.exists(PDF_STORAGE_PATH):
    os.makedirs(PDF_STORAGE_PATH)

def is_newsletter_manager():
    def predicate(ctx):
        return any(role.name == 'Newsletter Manager' for role in ctx.author.roles)
    return commands.check(predicate)

DATABASE = 'user_scores.db'
# User score database
async def init_score_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_scores (
                user_id INTEGER PRIMARY KEY,
                total_score INTEGER NOT NULL,
                num_replies INTEGER NOT NULL
            )
        ''')
        await db.commit()

# Newsletter database
async def init_db():
    async with aiosqlite.connect('newsletters.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS newsletters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                channel_id INTEGER NOT NULL
            )
        ''')
        await db.commit()

@bot.event
async def on_ready():
    try:
        await init_db() 
        await init_score_db()
        scheduler.start()
        await load_scheduled_newsletters()
        await check_and_post_newsletter()
        scheduler.add_job(check_and_post_newsletter, 'interval', hours=24)
        print(f'Logged in as {bot.user}')
    except Exception as e:
        print(f"An error occurred in on_ready: {e}")

async def load_scheduled_newsletters():
    async with aiosqlite.connect('newsletters.db') as db:
        cursor = await db.execute('SELECT id, title, content, scheduled_time, channel_id FROM newsletters')
        newsletters = await cursor.fetchall()
        for newsletter in newsletters:
            schedule_time = datetime.fromisoformat(newsletter[3])
            scheduler.add_job(
                post_newsletter,
                'date',
                run_date=schedule_time,
                args=[newsletter[0], newsletter[1], newsletter[2], newsletter[4]],
                id=f'newsletter_{newsletter[0]}'
            )

@bot.command()
@is_newsletter_manager()
async def createnewsletter(ctx):
    await ctx.send('Please enter the title of the newsletter.')

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        title_msg = await bot.wait_for('message', timeout=60.0, check=check)
        title = title_msg.content

        await ctx.send('Please enter the content of the newsletter.')
        content_msg = await bot.wait_for('message', timeout=300.0, check=check)
        content = content_msg.content

        await ctx.send('Please enter the scheduled time (YYYY-MM-DD HH:MM).')
        time_msg = await bot.wait_for('message', timeout=60.0, check=check)
        scheduled_time = time_msg.content

        # Validate datetime format
        try:
            schedule_time = datetime.fromisoformat(scheduled_time)
        except ValueError:
            await ctx.send('Invalid datetime format. Please use YYYY-MM-DD HH:MM.')
            return

        await ctx.send('Please mention the channel where the newsletter should be posted.')
        channel_msg = await bot.wait_for('message', timeout=60.0, check=check)
        if len(channel_msg.channel_mentions) == 0:
            await ctx.send('No channel mentioned.')
            return
        channel = channel_msg.channel_mentions[0]

        # Save newsletter to database and get the newsletter ID
        async with aiosqlite.connect('newsletters.db') as db:
            cursor = await db.execute(
                'INSERT INTO newsletters (title, content, scheduled_time, channel_id) VALUES (?, ?, ?, ?)',
                (title, content, scheduled_time, channel.id)
            )
            await db.commit()

            # Get the newsletter ID from cursor.lastrowid
            newsletter_id = cursor.lastrowid

        # Schedule the newsletter
        scheduler.add_job(
            post_newsletter,
            'date',
            run_date=schedule_time,
            args=[newsletter_id, title, content, channel.id],
            id=f'newsletter_{newsletter_id}'
        )

        await ctx.send(f'Newsletter "{title}" has been scheduled for {scheduled_time} in {channel.mention}. ID: {newsletter_id}')

    except asyncio.TimeoutError:
        await ctx.send('You took too long to respond. Please try again.')

def is_pdf_uploader():
    def predicate(ctx):
        return any(role.name == 'PDF Uploader' for role in ctx.author.roles)
    return commands.check(predicate)

@bot.command()
@is_pdf_uploader()
async def uploadpdf(ctx):
    await ctx.send("Please upload the PDF file as an attachment to this message.")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and len(m.attachments) > 0

    try:
        msg = await bot.wait_for('message', timeout=60.0, check=check)
        attachment = msg.attachments[0]

        # Check if the file is a PDF
        if not attachment.filename.lower().endswith('.pdf'):
            await ctx.send("The file must be a PDF.")
            return

        # Limit file size (e.g., max 8 MB)
        if attachment.size > 8 * 1024 * 1024:
            await ctx.send("The file is too large. Maximum size is 8 MB.")
            return

        # Sanitize filename
        safe_filename = os.path.basename(attachment.filename)

        file_path = os.path.join(PDF_STORAGE_PATH, safe_filename)

        if os.path.exists(file_path):
            await ctx.send("A file with that name already exists. Please rename your file and try again.")
            return

        # Save the PDF
        await attachment.save(file_path)

        await ctx.send(f"PDF `{safe_filename}` has been uploaded successfully.")

    except asyncio.TimeoutError:
        await ctx.send("You took too long to upload the PDF. Please try again.")

@bot.command()
async def listpdfs(ctx):
    pdf_files = [f for f in os.listdir(PDF_STORAGE_PATH) if f.endswith('.pdf')]

    if not pdf_files:
        await ctx.send("No PDFs are currently stored.")
        return

    embed = nextcord.Embed(title="Stored PDFs", color=nextcord.Color.blue())
    for pdf in pdf_files:
        embed.add_field(name=pdf, value="Use `!getpdf <filename>` to download.", inline=False)

    await ctx.send(embed=embed)

@bot.command()
async def getpdf(ctx, *, filename: str = None):
    if filename is None:
        await ctx.send("Please specify the filename. Usage: `!getpdf <filename>`")
        return

    safe_filename = os.path.basename(filename)
    file_path = os.path.join(PDF_STORAGE_PATH, safe_filename)

    if not os.path.exists(file_path):
        await ctx.send(f"PDF `{safe_filename}` not found.")
        return

    await ctx.send(file=nextcord.File(file_path))

@bot.command()
@is_newsletter_manager()
async def editnewsletter(ctx, newsletter_id: int):
    # Fetch the newsletter from the database
    async with aiosqlite.connect('newsletters.db') as db:
        cursor = await db.execute('SELECT title, content, scheduled_time, channel_id FROM newsletters WHERE id = ?', (newsletter_id,))
        newsletter = await cursor.fetchone()

    if newsletter is None:
        await ctx.send('Newsletter not found.')
        return

    await ctx.send(f'Editing Newsletter ID {newsletter_id}. Type `skip` to keep the current value.')

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    # Title
    await ctx.send(f'Current Title: {newsletter[0]}\nNew Title:')
    title_msg = await bot.wait_for('message', timeout=60.0, check=check)
    new_title = title_msg.content if title_msg.content.lower() != 'skip' else newsletter[0]

    # Content
    await ctx.send('New Content:')
    content_msg = await bot.wait_for('message', timeout=300.0, check=check)
    new_content = content_msg.content if content_msg.content.lower() != 'skip' else newsletter[1]

    # Scheduled Time
    await ctx.send(f'Current Scheduled Time: {newsletter[2]}\nNew Scheduled Time (YYYY-MM-DD HH:MM):')
    time_msg = await bot.wait_for('message', timeout=60.0, check=check)
    new_scheduled_time = time_msg.content if time_msg.content.lower() != 'skip' else newsletter[2]

    # Validate datetime format
    try:
        schedule_time = datetime.fromisoformat(new_scheduled_time)
    except ValueError:
        await ctx.send('Invalid datetime format. Please use YYYY-MM-DD HH:MM.')
        return

    # Channel
    await ctx.send('Mention the new channel:')
    channel_msg = await bot.wait_for('message', timeout=60.0, check=check)
    new_channel_id = newsletter[3]
    if channel_msg.content.lower() != 'skip':
        if len(channel_msg.channel_mentions) == 0:
            await ctx.send('No channel mentioned.')
            return
        new_channel_id = channel_msg.channel_mentions[0].id

    # Update the database
    async with aiosqlite.connect('newsletters.db') as db:
        await db.execute(
            'UPDATE newsletters SET title = ?, content = ?, scheduled_time = ?, channel_id = ? WHERE id = ?',
            (new_title, new_content, new_scheduled_time, new_channel_id, newsletter_id)
        )
        await db.commit()

    # Reschedule the newsletter
    scheduler.remove_job(f'newsletter_{newsletter_id}')
    scheduler.add_job(
        post_newsletter,
        'date',
        run_date=schedule_time,
        args=[newsletter_id, new_title, new_content, new_channel_id],
        id=f'newsletter_{newsletter_id}'
    )

    await ctx.send(f'Newsletter ID {newsletter_id} has been updated.')

@bot.command()
@is_newsletter_manager()
async def schedulenewsletter(ctx):
    async with aiosqlite.connect('newsletters.db') as db:
        cursor = await db.execute('SELECT id, title, scheduled_time, channel_id FROM newsletters')
        newsletters = await cursor.fetchall()

    if not newsletters:
        await ctx.send('No newsletters scheduled.')
        return

    message = '**Scheduled Newsletters:**\n'
    for nl in newsletters:
        channel = bot.get_channel(nl[3])
        message += f'ID: {nl[0]}, Title: {nl[1]}, Scheduled Time: {nl[2]}, Channel: {channel.mention if channel else "Unknown"}\n'

    await ctx.send(message)

async def post_newsletter(newsletter_id, title, content, channel_id):
    channel = bot.get_channel(channel_id)
    if channel is None:
        print(f'Channel ID {channel_id} not found.')
        return

    embed = nextcord.Embed(title=title, description=content)
    await channel.send(embed=embed)

    # Remove the newsletter from the database
    async with aiosqlite.connect('newsletters.db') as db:
        await db.execute('DELETE FROM newsletters WHERE id = ?', (newsletter_id,))
        await db.commit()

    print(f'Newsletter "{title}" has been posted in {channel.name}.')

@bot.command()
@is_newsletter_manager()
async def cleardatabase(ctx):
    await ctx.send("⚠️ **Warning:** This action will delete all entries in the newsletter database and cancel all scheduled newsletters. Type `YES` within 30 seconds to confirm.")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        confirmation = await bot.wait_for('message', timeout=30.0, check=check)
        if confirmation.content.strip().upper() == 'YES':
            # Proceed to clear the database
            async with aiosqlite.connect('newsletters.db') as db:
                await db.execute('DELETE FROM newsletters')
                await db.commit()

            # Remove all scheduled newsletter jobs
            for job in scheduler.get_jobs():
                if job.id.startswith('newsletter_'):
                    scheduler.remove_job(job.id)

            await ctx.send("✅ All entries in the newsletter database have been deleted, and scheduled newsletters have been canceled.")
        else:
            await ctx.send("Database clearing operation canceled.")
    except asyncio.TimeoutError:
        await ctx.send("No response received. Database clearing operation canceled.")

@bot.command()
@is_newsletter_manager()
async def listnewsletters(ctx):
    async with aiosqlite.connect('newsletters.db') as db:
        cursor = await db.execute('SELECT id, title, scheduled_time, channel_id FROM newsletters')
        newsletters = await cursor.fetchall()

    if not newsletters:
        await ctx.send('There are no newsletters in the database.')
        return

    embed = nextcord.Embed(title='📬 All Newsletters', color=nextcord.Color.blue())

    for nl in newsletters:
        nl_id = nl[0]
        title = nl[1]
        scheduled_time = nl[2]
        channel_id = nl[3]
        channel = bot.get_channel(channel_id)
        channel_name = channel.mention if channel else 'Unknown Channel'

        # Format scheduled time
        try:
            schedule_time = datetime.fromisoformat(scheduled_time)
            formatted_time = schedule_time.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            formatted_time = scheduled_time  # Use raw value if parsing fails

        # Add a field for each newsletter
        embed.add_field(
            name=f'ID: {nl_id} - {title}',
            value=f'📅 **Scheduled Time:** {formatted_time}\n📢 **Channel:** {channel_name}',
            inline=False
        )

        # Send embed if field limit is reached
        if len(embed.fields) == 25:
            await ctx.send(embed=embed)
            embed.clear_fields()

    # Send any remaining newsletters
    if embed.fields:
        await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    commands_info = [
        {
            'name': '!createnewsletter',
            'usage': '!createnewsletter',
            'description': 'Creates and schedules a new newsletter. You will be prompted to enter the title, content, scheduled time, and channel.',
            'permissions': 'Requires the **Newsletter Manager** role.'
        },
        {
            'name': '!editnewsletter',
            'usage': '!editnewsletter <newsletter_id>',
            'description': 'Edits an existing scheduled newsletter. You can update the title, content, scheduled time, and channel.',
            'permissions': 'Requires the **Newsletter Manager** role.'
        },
        {
            'name': '!schedulenewsletter',
            'usage': '!schedulenewsletter',
            'description': 'Lists all scheduled newsletters.',
            'permissions': 'Requires the **Newsletter Manager** role.'
        },
        {
            'name': '!cleardatabase',
            'usage': '!cleardatabase',
            'description': 'Deletes all entries in the newsletter database and cancels all scheduled newsletters. **Use with caution!**',
            'permissions': 'Requires the **Newsletter Manager** role.'
        },
        {
            'name': '!listnewsletters',
            'usage': '!listnewsletters',
            'description': 'Displays all newsletters in the database with their details.',
            'permissions': 'Requires the **Newsletter Manager** role.'
        },
        {
            'name': '!emailpdf',
            'usage': '!emailpdf <email_address> <filename1>, [filename2], ...',
            'description': 'Emails the specified PDFs to the given email address.',
            'permissions': 'Requires the **PDF Uploader** role.'
        },
        {
            'name': '!help',
            'usage': '!help',
            'description': 'Shows this help message.',
            'permissions': 'Available to all users.'
        },
        {
            'name': '!uploadpdf',
            'usage': '!uploadpdf',
            'description': 'Uploads a PDF to the bot. You will be prompted to attach the PDF file.',
            'permissions': 'Requires the **PDF Uploader** role.'
        },
        {
            'name': '!listpdfs',
            'usage': '!listpdfs',
            'description': 'Lists all stored PDFs.',
            'permissions': 'Available to all users.'  # Adjust if you add permissions
        },
        {
            'name': '!getpdf',
            'usage': '!getpdf <filename>',
            'description': 'Retrieves a stored PDF by filename.',
            'permissions': 'Available to all users.'  # Adjust if you add permissions
        },
        {
        'name': '!emailpdf',
        'usage': '!emailpdf <email_address> <filename1>, [filename2], ...',
        'description': 'Emails the specified PDFs to the given email address.',
        'permissions': 'Requires the **PDF Uploader** role.'
        },
        {
            'name': '!myscore',
            'usage': '!myscore',
            'description': 'Displays your total helpfulness score.',
            'permissions': 'Available to all users.'
        },
        {
            'name': '!leaderboard',
            'usage': '!leaderboard',
            'description': 'Shows the top 10 users with the highest helpfulness scores.',
            'permissions': 'Available to all users.'
        },
        # Include these if you implemented opt-in/out functionality
        {
            'name': '!optin',
            'usage': '!optin',
            'description': 'Opts you into the helpfulness scoring system.',
            'permissions': 'Available to all users.'
        },
        {
            'name': '!optout',
            'usage': '!optout',
            'description': 'Opts you out of the helpfulness scoring system.',
            'permissions': 'Available to all users.'
        },
        # Administrator Command
        {
            'name': '!resetscores',
            'usage': '!resetscores',
            'description': 'Resets all user scores in the database. **Use with caution!**',
            'permissions': 'Requires administrator permissions.'
        }
    ]

    embed = nextcord.Embed(title='📖 Help - List of Commands', color=nextcord.Color.green())

    # Set thumbnail only if bot has an avatar
    if bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)

    # Set footer with user info
    footer_text = f'Requested by {ctx.author}'
    if ctx.author.avatar:
        embed.set_footer(text=footer_text, icon_url=ctx.author.avatar.url)
    else:
        embed.set_footer(text=footer_text)

    for cmd in commands_info:
        name = cmd['name']
        usage = cmd['usage']
        description = cmd['description']
        permissions = cmd['permissions']

        embed.add_field(
            name=f'{name}',
            value=f'**Usage:** `{usage}`\n**Description:** {description}\n**Permissions:** {permissions}',
            inline=False
        )

    await ctx.send(embed=embed)

# Database file for tracking posted newsletters
DATABASE = 'newsletters_posted.db'

def get_latest_newsletter():
    feed_url = 'https://www.deeplearning.ai/the-batch/feed/'
    feed = feedparser.parse(feed_url)
    if feed.entries:
        latest_entry = feed.entries[0]
        return latest_entry
    else:
        return None

async def is_newsletter_posted(newsletter_id):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS posted_newsletters (id TEXT PRIMARY KEY)')
        cursor = await db.execute('SELECT id FROM posted_newsletters WHERE id = ?', (newsletter_id,))
        result = await cursor.fetchone()
        return result is not None

async def mark_newsletter_as_posted(newsletter_id):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute('INSERT INTO posted_newsletters (id) VALUES (?)', (newsletter_id,))
        await db.commit()

async def check_and_post_newsletter():
    channel_id = 1291424889655394537  # Replace with your Discord channel ID
    try:
        channel = await bot.fetch_channel(channel_id)
    except nextcord.NotFound:
        print(f"Channel with ID {channel_id} not found.")
        return
    except nextcord.Forbidden:
        print(f"Bot does not have permission to access channel ID {channel_id}.")
        return
    except nextcord.HTTPException as e:
        print(f"An HTTP exception occurred: {e}")
        return
    
    latest_newsletter = get_latest_newsletter()
    if latest_newsletter is None:
        print("No newsletter entries found.")
        return

    # Use the link as a unique identifier
    newsletter_id = latest_newsletter.link
    already_posted = await is_newsletter_posted(newsletter_id)
    if not already_posted:
        # Mark newsletter as posted
        await mark_newsletter_as_posted(newsletter_id)
        
        # Prepare the embed
        title = latest_newsletter.title
        link = latest_newsletter.link
        summary = latest_newsletter.summary  # May contain HTML tags

        # Remove HTML tags from summary
        clean_summary = re.sub('<[^<]+?>', '', summary)

        # Create an embed message
        embed = nextcord.Embed(title=title, url=link, description=clean_summary, color=nextcord.Color.blue())
        embed.set_author(name='Deeplearning.ai Newsletter')
        embed.set_footer(text='Stay tuned for more updates!')

        await channel.send(embed=embed)
    else:
        print("Newsletter has already been posted.")



@bot.command()
@commands.has_role('PDF Uploader')  # Adjust role as needed
async def emailpdf(ctx, email_address: str, *, filenames: str):
    # Validate the email address
    try:
        valid = validate_email(email_address)
        email_address = valid.email
    except EmailNotValidError as e:
        await ctx.send(f"Invalid email address: {e}")
        return

    # Split filenames and clean them
    requested_files = [filename.strip() for filename in filenames.split(',')]

    # Check if files exist
    files_to_send = []
    for filename in requested_files:
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(PDF_STORAGE_PATH, safe_filename)
        if not os.path.exists(file_path):
            await ctx.send(f"PDF `{safe_filename}` not found.")
            return
        files_to_send.append(file_path)

    # Email configuration
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_username = os.getenv('SMTP_USERNAME')
    smtp_password = os.getenv('SMTP_PASSWORD')
    email_from = os.getenv('EMAIL_FROM_ADDRESS')
    email_to = email_address

    # Create the email message
    msg = EmailMessage()
    msg['Subject'] = 'Requested PDFs from Discord Bot'
    msg['From'] = email_from
    msg['To'] = email_to
    msg.set_content(f"Hello,\n\nPlease find the requested PDFs attached.\n\nBest regards,\nYour Discord Bot")

    # Attach PDFs
    for file_path in files_to_send:
        with open(file_path, 'rb') as f:
            file_data = f.read()
            file_name = os.path.basename(file_path)
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)

    # Send the email
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls(context=context)
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        await ctx.send(f"Email sent successfully to `{email_to}`.")
    except Exception as e:
        await ctx.send(f"An error occurred while sending the email: {e}")



# Function to load roasts from a file (optional)
def load_roasts():
    roasts_file = 'roasts.txt'
    if os.path.exists(roasts_file):
        with open(roasts_file, 'r') as file:
            return [line.strip() for line in file if line.strip()]
    else:
        return [
            "I don't have the time or the crayons to explain this to you.",
            "Light travels faster than sound, which is why you seemed bright until you spoke.",
            "Don't worry, the first 40 years of childhood are always the hardest.",
            "You're the reason the gene pool needs a lifeguard.",
            "You're as bright as a black hole, and twice as dense.",
            "You're not the dumbest person on the planet, but you sure better hope they don't die."
        ]

roasts = load_roasts()

@bot.command()
@commands.cooldown(1, 10, BucketType.user)  # Cooldown to prevent spamming
async def roast(ctx, member: nextcord.Member = None):
    if member is None:
        await ctx.send("Please mention a user to roast.")
        return

    if member == ctx.author:
        await ctx.send("You can't roast yourself!")
        return

    if member == bot.user:
        await ctx.send("I know I'm just a bot, but I have feelings too!")
        return

    # Randomly select a roast
    roast_message = random.choice(roasts)

    # Send the roast message mentioning the user
    await ctx.send(f"{member.mention}, {roast_message}")

@roast.error
async def roast_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("Couldn't find that user. Please mention a valid user.")
    elif isinstance(error, CommandOnCooldown):
        await ctx.send(f"You're doing that too much! Try again in {round(error.retry_after, 1)} seconds.")
    elif isinstance(error, MissingRole):
        await ctx.send("You don't have permission to use this command.")

question_messages = {}  # Key: Message ID of the question, Value: List of reply Message objects

def is_question(content):
    content_lower = content.lower()
    question_keywords = ['how', 'what', 'why', 'help', 'can', 'do', 'does', 'is', 'are', 'could', 'would', 'should', 'where', 'when', 'who']

    if content.strip().endswith('?'):
        return True

    if any(content_lower.startswith(word + ' ') for word in question_keywords):
        return True

    return False

async def track_question(question_message):
    # Store the question for monitoring
    question_messages[question_message.id] = []

    # Stop tracking after 2 hours
    await asyncio.sleep(2 * 60 * 60)
    if question_message.id in question_messages:
        del question_messages[question_message.id]

async def check_for_reply(message):
    if message.reference and message.reference.message_id:
        replied_message_id = message.reference.message_id

        if replied_message_id in question_messages:
            # Add the reply to the list of replies for that question
            question_messages[replied_message_id].append(message)

            # Analyze the reply
            await analyze_reply(message)

async def analyze_reply(reply_message):
    try:
        # Get the original question
        question_message = reply_message.reference.resolved
        if question_message is None:
            return

        # Prepare the messages for the ChatCompletion
        messages = [
            {
                "role": "system",
                "content": "You are an assistant that evaluates the helpfulness of a reply to a question."
            },
            {
                "role": "user",
                "content": f"""Question: "{question_message.content}"

                Reply: "{reply_message.content}"

                On a scale of 1 to 10, where 1 is not helpful at all and 10 is extremely helpful, how helpful is this reply? Provide just the number."""
            }
        ]

        # Call the OpenAI API
        response = client.chat.completions.create(
            model='gpt-3.5-turbo',  # or 'gpt-4' if you have access
            messages=messages,
        )

        # Extract the score
        score_text = response.choices[0].message.content.strip()
        score = int(score_text)

        # Ensure the score is within 1-10
        if score < 1 or score > 10:
            raise ValueError("Score out of range")

        # Update the user's score in the database
        await update_user_score(reply_message.author.id, score)

        # Provide feedback to the responder
        total_score = await get_user_total_score(reply_message.author.id)
        feedback = f"Your reply was rated {score}/10 for helpfulness. Your total score is now {total_score}."
        await reply_message.channel.send(f"{reply_message.author.mention}, {feedback}")

    except Exception as e:
        print(f"An error occurred while analyzing the reply: {e}")

async def update_user_score(user_id, score):
    async with aiosqlite.connect(DATABASE) as db:
        # Check if the user already exists in the database
        cursor = await db.execute('SELECT total_score, num_replies FROM user_scores WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()

        if result:
            # Update existing user record
            total_score, num_replies = result
            total_score += score
            num_replies += 1
            await db.execute('UPDATE user_scores SET total_score = ?, num_replies = ? WHERE user_id = ?', (total_score, num_replies, user_id))
        else:
            # Insert new user record
            await db.execute('INSERT INTO user_scores (user_id, total_score, num_replies) VALUES (?, ?, ?)', (user_id, score, 1))

        await db.commit()


async def get_user_total_score(user_id):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute('SELECT total_score FROM user_scores WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        return result[0] if result else 0

async def get_user_average_score(user_id):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute('SELECT total_score, num_replies FROM user_scores WHERE user_id = ?', (user_id,))
        result = await cursor.fetchone()
        if result and result[1] > 0:
            return result[0] / result[1]
        else:
            return 0
        
@bot.command()
async def myscore(ctx):
    total_score = await get_user_total_score(ctx.author.id)
    await ctx.send(f"{ctx.author.mention}, your total helpfulness score is {total_score}.")

@bot.command()
async def leaderboard(ctx):
    async with aiosqlite.connect(DATABASE) as db:
        cursor = await db.execute('SELECT user_id, total_score FROM user_scores ORDER BY total_score DESC LIMIT 10')
        top_users = await cursor.fetchall()

    if not top_users:
        await ctx.send("No scores available yet.")
        return

    embed = nextcord.Embed(title="🏆 Leaderboard - Top 10 Helpers", color=nextcord.Color.gold())
    for rank, (user_id, total_score) in enumerate(top_users, start=1):
        user = bot.get_user(user_id)
        username = user.name if user else f"User ID {user_id}"
        embed.add_field(name=f"{rank}. {username}", value=f"Score: {total_score}", inline=False)

    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    # Ignore messages from bots
    if message.author.bot:
        return

    # Process replies to tracked questions
    await check_for_reply(message)

    # Check if the message is a question
    if is_question(message.content):
        await track_question(message)

    # Process other bot commands and events
    await bot.process_commands(message)

# Make a complement to pair with the roasts
datoken = os.getenv('NEW_BOT_TOKEN')
print(datoken)
bot.run(datoken)
