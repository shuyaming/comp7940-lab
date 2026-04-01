"""
This program requires the following modules:
- python-telegram-bot==22.5
- urllib3==2.6.2
- upstash-redis
"""

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from ChatGPT_HKBU import ChatGPT
import configparser
import logging
from upstash_redis import Redis

# Global variables
gpt = None
redis_client = None

# ========== Redis Helper Functions ==========

def init_redis():
    """Initialize Redis connection"""
    global redis_client
    try:
        config = configparser.ConfigParser()
        config.read('config.ini')
        
        url = config['REDIS']['URL']
        token = config['REDIS']['TOKEN']
        
        redis_client = Redis(url=url, token=token)
        redis_client.ping()
        logging.info("✅ Redis connected successfully")
        return True
    except Exception as e:
        logging.error(f"❌ Redis connection failed: {e}")
        return False


# ========== Interest Matching Functions ==========

def set_user_interests(user_id: int, interests: list):
    """Set user interests (overwrites existing)"""
    user_key = f"user:{user_id}:interests"
    
    # Get old interests to clean up reverse index
    old_interests = redis_client.smembers(user_key)
    for interest in old_interests:
        interest_key = f"interest:{interest}:users"
        redis_client.srem(interest_key, user_id)
    
    # Delete old data
    redis_client.delete(user_key)
    
    # Add new interests
    for interest in interests:
        clean_interest = interest.lower().strip()
        redis_client.sadd(user_key, clean_interest)
        interest_key = f"interest:{clean_interest}:users"
        redis_client.sadd(interest_key, user_id)
    
    logging.info(f"User {user_id} set interests: {interests}")
    return len(interests)


def add_user_interest(user_id: int, interest: str):
    """Add a single interest to user"""
    clean_interest = interest.lower().strip()
    user_key = f"user:{user_id}:interests"
    
    redis_client.sadd(user_key, clean_interest)
    interest_key = f"interest:{clean_interest}:users"
    redis_client.sadd(interest_key, user_id)
    
    logging.info(f"User {user_id} added interest: {interest}")


def get_user_interests(user_id: int) -> list:
    """Get all interests for a user"""
    user_key = f"user:{user_id}:interests"
    interests = redis_client.smembers(user_key)
    return [i for i in interests]


def find_matching_users(user_id: int) -> list:
    """Find users with similar interests"""
    user_interests = set(get_user_interests(user_id))
    
    if not user_interests:
        return []
    
    matches = {}
    
    for interest in user_interests:
        interest_key = f"interest:{interest}:users"
        users_with_interest = redis_client.smembers(interest_key)
        
        for other_user in users_with_interest:
            other_id = int(other_user)
            if other_id == user_id:
                continue
            
            if other_id not in matches:
                matches[other_id] = set()
            matches[other_id].add(interest)
    
    results = [(uid, list(interests_set)) for uid, interests_set in matches.items()]
    results.sort(key=lambda x: len(x[1]), reverse=True)
    
    return results


def delete_user_interest(user_id: int, interest: str):
    """Delete a specific interest from user"""
    clean_interest = interest.lower().strip()
    user_key = f"user:{user_id}:interests"
    interest_key = f"interest:{clean_interest}:users"
    
    redis_client.srem(user_key, clean_interest)
    redis_client.srem(interest_key, user_id)
    
    logging.info(f"User {user_id} deleted interest: {interest}")


# ========== Event/Activity Functions ==========

# Sample activity data
ACTIVITIES = [
    {
        "id": 1,
        "name": "Cloud Computing Workshop",
        "date": "2026-04-10",
        "time": "14:00-16:00",
        "location": "Online (Zoom)",
        "tags": ["tech", "cloud", "workshop"],
        "description": "Learn about AWS, Docker, and Kubernetes basics"
    },
    {
        "id": 2,
        "name": "Campus Hackathon 2026",
        "date": "2026-04-15",
        "time": "09:00-18:00",
        "location": "Lee Shau Kee Building Room 101",
        "tags": ["coding", "hackathon", "competition"],
        "description": "24-hour coding challenge with prizes"
    },
    {
        "id": 3,
        "name": "Career Development Workshop",
        "date": "2026-04-12",
        "time": "15:00-17:00",
        "location": "Jockey Club Building Room 202",
        "tags": ["career", "workshop", "job"],
        "description": "Resume review and interview tips"
    },
    {
        "id": 4,
        "name": "Badminton Friendly Match",
        "date": "2026-04-18",
        "time": "10:00-12:00",
        "location": "Sports Center Court 3",
        "tags": ["sports", "badminton", "competition"],
        "description": "All skill levels welcome"
    },
    {
        "id": 5,
        "name": "Python Programming Workshop",
        "date": "2026-04-09",
        "time": "19:00-21:00",
        "location": "Online (Teams)",
        "tags": ["coding", "python", "workshop"],
        "description": "Beginner-friendly Python introduction"
    }
]


def get_all_activities() -> list:
    """Get all available activities"""
    return ACTIVITIES


def get_activities_by_tags(tags: list) -> list:
    """Filter activities by tags"""
    matched = []
    for activity in ACTIVITIES:
        if any(tag.lower() in [t.lower() for t in activity['tags']] for tag in tags):
            matched.append(activity)
    return matched


def recommend_activities_by_interests(user_id: int) -> list:
    """Recommend activities based on user interests"""
    interests = get_user_interests(user_id)
    
    if not interests:
        return get_all_activities()[:5]
    
    return get_activities_by_tags(interests)


def get_activity_by_id(activity_id: int) -> dict:
    """Get single activity by ID"""
    for activity in ACTIVITIES:
        if activity['id'] == activity_id:
            return activity
    return None


# ========== Telegram Command Handlers ==========

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_msg = """
🎓 **Welcome to Campus Assistant Bot!**

I can help you with:

🔍 **Interest Matching**
• `/interests` - View your interests
• `/setinterest tech coding` - Set your interests
• `/addinterest basketball` - Add an interest
• `/removeinterest sports` - Remove an interest
• `/match` - Find people with similar interests

🎉 **Event Recommendations**
• `/events` - View all upcoming events
• `/recommend` - Get personalized recommendations
• `/event 1` - View details of event #1

💬 **Course Q&A**
Just ask me any question about your courses!

Type `/help` for more details.
"""
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_msg = """
📖 **Help Guide**

**Interest Management**
`/interests` - View your interests
`/setinterest tech coding` - Set your interests
`/addinterest basketball` - Add an interest
`/removeinterest sports` - Remove an interest
`/match` - Find matching users

**Events**
`/events` - View all events
`/recommend` - Get personalized recommendations
`/event 1` - View event details

**Course Q&A**
Just type your question and I'll answer!
"""
    await update.message.reply_text(help_msg, parse_mode='Markdown')


async def set_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setinterest command"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Please provide interests. Example: `/setinterest tech coding sports`")
        return
    
    interests = [arg.lower() for arg in context.args]
    count = set_user_interests(user_id, interests)
    
    await update.message.reply_text(
        f"✅ Set {count} interests: `{', '.join(interests)}`\n\n"
        f"Try `/match` to find people with similar interests!",
        parse_mode='Markdown'
    )


async def add_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addinterest command"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Please provide an interest. Example: `/addinterest basketball`")
        return
    
    interest = ' '.join(context.args).lower()
    add_user_interest(user_id, interest)
    
    interests = get_user_interests(user_id)
    await update.message.reply_text(
        f"✅ Added interest: `{interest}`\n"
        f"Current interests: `{', '.join(interests)}`",
        parse_mode='Markdown'
    )


async def remove_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removeinterest command"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Please provide an interest. Example: `/removeinterest basketball`")
        return
    
    interest = ' '.join(context.args).lower()
    interests = get_user_interests(user_id)
    
    if interest not in interests:
        await update.message.reply_text(f"❌ You don't have interest `{interest}`", parse_mode='Markdown')
        return
    
    delete_user_interest(user_id, interest)
    
    new_interests = get_user_interests(user_id)
    if new_interests:
        await update.message.reply_text(
            f"✅ Removed interest: `{interest}`\n"
            f"Remaining interests: `{', '.join(new_interests)}`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"✅ Removed interest: `{interest}`\n"
            f"You have no interests left. Use `/setinterest` to add some!",
            parse_mode='Markdown'
        )


async def view_interests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /interests command"""
    user_id = update.effective_user.id
    interests = get_user_interests(user_id)
    
    if not interests:
        await update.message.reply_text(
            "📭 You haven't set any interests yet.\n\n"
            "Use `/setinterest tech coding sports` to get started!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"📝 **Your Interests:**\n\n`{', '.join(interests)}`\n\n"
            f"Use `/match` to find people with similar interests!",
            parse_mode='Markdown'
        )


async def match_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /match command - find users with similar interests"""
    user_id = update.effective_user.id
    
    interests = get_user_interests(user_id)
    if not interests:
        await update.message.reply_text(
            "❌ Please set your interests first!\n"
            "Use `/setinterest tech coding sports` to add interests.",
            parse_mode='Markdown'
        )
        return
    
    matches = find_matching_users(user_id)
    
    if not matches:
        await update.message.reply_text(
            f"🔍 No matches found for your interests: `{', '.join(interests)}`\n\n"
            f"Try adding more interests or check back later!",
            parse_mode='Markdown'
        )
        return
    
    response = f"🔍 **Found {len(matches)} user(s) with similar interests!**\n\n"
    response += f"Your interests: `{', '.join(interests)}`\n\n"
    response += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for i, (other_id, common) in enumerate(matches[:10], 1):
        response += f"**{i}. User {other_id}**\n"
        response += f"   🎯 Common interests: `{', '.join(common)}`\n\n"
    
    response += "💡 *Tip: You can DM them to connect!*"
    
    await update.message.reply_text(response, parse_mode='Markdown')


async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /events command - list all events"""
    activities = get_all_activities()
    
    response = "🎉 **Upcoming Events & Activities**\n\n"
    response += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for activity in activities:
        response += f"**{activity['id']}. {activity['name']}**\n"
        response += f"   📅 {activity['date']} | {activity['time']}\n"
        response += f"   📍 {activity['location']}\n"
        response += f"   🏷️ {', '.join(['#' + t for t in activity['tags']])}\n\n"
    
    response += "Use `/event [id]` to see details, or `/recommend` for personalized suggestions!"
    
    await update.message.reply_text(response, parse_mode='Markdown')


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /recommend command - personalized event recommendations"""
    user_id = update.effective_user.id
    
    interests = get_user_interests(user_id)
    recommended = recommend_activities_by_interests(user_id)
    
    if not recommended:
        await update.message.reply_text("📭 No events available at the moment.")
        return
    
    if interests:
        response = f"🎯 **Personalized Recommendations**\n"
        response += f"Based on your interests: `{', '.join(interests)}`\n\n"
    else:
        response = "🎉 **Recommended Events**\n"
        response += "Set your interests with `/setinterest` for personalized suggestions!\n\n"
    
    response += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for activity in recommended[:5]:
        response += f"**{activity['id']}. {activity['name']}**\n"
        response += f"   📅 {activity['date']} | {activity['time']}\n"
        response += f"   📍 {activity['location']}\n"
        response += f"   🏷️ {', '.join(['#' + t for t in activity['tags']])}\n"
        response += f"   📝 {activity['description'][:80]}...\n\n"
    
    response += "Use `/event [id]` to see full details!"
    
    await update.message.reply_text(response, parse_mode='Markdown')


async def event_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /event [id] command - show event details"""
    if not context.args:
        await update.message.reply_text("❌ Please provide an event ID. Example: `/event 1`")
        return
    
    try:
        event_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid event ID number.")
        return
    
    activity = get_activity_by_id(event_id)
    
    if not activity:
        await update.message.reply_text(f"❌ Event with ID {event_id} not found.")
        return
    
    response = f"📌 **{activity['name']}**\n\n"
    response += f"📅 **Date:** {activity['date']}\n"
    response += f"⏰ **Time:** {activity['time']}\n"
    response += f"📍 **Location:** {activity['location']}\n"
    response += f"🏷️ **Tags:** {', '.join(['#' + t for t in activity['tags']])}\n\n"
    response += f"📝 **Description:**\n{activity['description']}\n\n"
    response += "🎟️ To register, please contact the event organizer."
    
    await update.message.reply_text(response, parse_mode='Markdown')


# ========== Original Callback with ChatGPT ==========

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Original callback function with ChatGPT"""
    logging.info("UPDATE: " + str(update))
    loading_message = await update.message.reply_text('Thinking...')
    
    # Send the user message to the ChatGPT client
    response = gpt.submit(update.message.text)
    
    # Send the response to the Telegram bot client
    await loading_message.edit_text(response)


# ========== Main Function ==========

def main():
    # Configure logging
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)
    
    # Load configuration
    logging.info('INIT: Loading configuration...')
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    # Initialize Redis (optional - continue even if fails)
    logging.info('INIT: Connecting to Redis...')
    redis_ok = init_redis()
    if not redis_ok:
        logging.warning('Redis connection failed. Interest matching and event features will be disabled.')
    
    # Initialize ChatGPT
    global gpt
    gpt = ChatGPT(config)
    
    # Create Telegram application
    logging.info('INIT: Connecting the Telegram bot...')
    app = ApplicationBuilder().token(config['TELEGRAM']['ACCESS_TOKEN']).build()
    
    # Register command handlers (only if Redis is available)
    if redis_ok:
        app.add_handler(CommandHandler('start', start_command))
        app.add_handler(CommandHandler('help', help_command))
        app.add_handler(CommandHandler('interests', view_interests_command))
        app.add_handler(CommandHandler('setinterest', set_interest_command))
        app.add_handler(CommandHandler('addinterest', add_interest_command))
        app.add_handler(CommandHandler('removeinterest', remove_interest_command))
        app.add_handler(CommandHandler('match', match_command))
        app.add_handler(CommandHandler('events', events_command))
        app.add_handler(CommandHandler('recommend', recommend_command))
        app.add_handler(CommandHandler('event', event_detail_command))
    else:
        logging.warning('Command handlers disabled due to Redis connection failure.')
    
    # Register message handler (original ChatGPT functionality)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, callback))
    
    # Start the bot
    logging.info('INIT: Initialization done!')
    app.run_polling()


if __name__ == '__main__':
    main()