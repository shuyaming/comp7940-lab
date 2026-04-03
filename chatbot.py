"""
Campus Assistant Bot - COMP7940 Project
Single file with all features:
1. Interest-based User Matching (LLM Prompt Template)
2. Event/Activity Recommendation (LLM Prompt Template)
3. Course Q&A (LLM Prompt Template)
4. Complete logging to Redis Cloud Database
5. Rate Limiting (Security)
"""

import logging
import configparser
import json
import time
import datetime
from collections import defaultdict
from typing import List, Dict, Tuple

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters
)

from upstash_redis import Redis
from ChatGPT_HKBU import ChatGPT

# ========== Configuration ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global clients
redis_client = None
config = None
gpt = None

# ========== Metrics ==========
metrics = {
    "total_requests": 0,
    "successful_responses": 0,
    "error_responses": 0,
    "command_usage": defaultdict(int),
    "start_time": datetime.datetime.now().isoformat()
}

# ========== Rate Limiting (Security) ==========
user_rate_limit = defaultdict(list)

def check_rate_limit(user_id: int, limit: int = 10, window: int = 60) -> bool:
    """
    Check if user exceeds rate limit
    limit: max requests per time window (default 10)
    window: time window in seconds (default 60 seconds)
    """
    now = time.time()
    user_requests = user_rate_limit[user_id]
    
    # Clean up expired records
    user_requests = [t for t in user_requests if now - t < window]
    user_rate_limit[user_id] = user_requests
    
    # Check if over limit
    if len(user_requests) >= limit:
        return False
    
    # Add current request
    user_requests.append(now)
    return True


# ========== Redis Log Functions ==========

def insert_request_log(telegram_id: int, req_type: str, req_msg: str, res_msg: str):
    """Insert request log into Redis cloud database"""
    try:
        # Get next log ID
        log_id = redis_client.incr("log:next_id")
        key = f"log:{log_id}"
        
        # Store field by field
        redis_client.hset(key, "telegram_id", str(telegram_id))
        redis_client.hset(key, "type", req_type)
        redis_client.hset(key, "request", req_msg[:200])
        redis_client.hset(key, "response", res_msg[:500])
        redis_client.hset(key, "time", str(datetime.datetime.now()))
        
        logger.info(f"Log saved: {req_type} from user {telegram_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save log: {e}")
        return False


def get_recent_logs(limit: int = 20):
    """Get recent logs from Redis"""
    try:
        current_id = redis_client.get("log:next_id")
        if not current_id:
            return []
        current_id = int(current_id)
        
        logs = []
        for i in range(max(1, current_id - limit), current_id):
            key = f"log:{i}"
            log = redis_client.hgetall(key)
            if log:
                decoded = {k.decode('utf-8'): v.decode('utf-8') for k, v in log.items()}
                logs.append(decoded)
        
        return logs[::-1]
    except Exception as e:
        logger.error(f"Failed to get logs: {e}")
        return []


# ========== Redis Interest Functions ==========

def set_user_interests(user_id: int, interests: List[str]):
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
    
    logger.info(f"User {user_id} set interests: {interests}")
    return len(interests)


def add_user_interest(user_id: int, interest: str):
    """Add a single interest to user"""
    clean_interest = interest.lower().strip()
    user_key = f"user:{user_id}:interests"
    
    redis_client.sadd(user_key, clean_interest)
    interest_key = f"interest:{clean_interest}:users"
    redis_client.sadd(interest_key, user_id)
    
    logger.info(f"User {user_id} added interest: {interest}")


def get_user_interests(user_id: int) -> List[str]:
    """Get all interests for a user"""
    user_key = f"user:{user_id}:interests"
    interests = redis_client.smembers(user_key)
    return list(interests)


def delete_user_interest(user_id: int, interest: str):
    """Delete a specific interest from user"""
    clean_interest = interest.lower().strip()
    user_key = f"user:{user_id}:interests"
    interest_key = f"interest:{clean_interest}:users"
    
    redis_client.srem(user_key, clean_interest)
    redis_client.srem(interest_key, user_id)
    
    logger.info(f"User {user_id} deleted interest: {interest}")


def get_all_users_with_interests(exclude_user_id: int = None) -> List[Dict]:
    """Get all users and their interests"""
    try:
        keys = redis_client.keys("user:*:interests")
        users = []
        
        for key in keys:
            # key may be bytes, decode to string
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            user_id_str = key_str.split(':')[1]
            user_id = int(user_id_str)
            
            if exclude_user_id and user_id == exclude_user_id:
                continue
            
            interests = get_user_interests(user_id)
            if interests:
                users.append({
                    "user_id": user_id,
                    "interests": interests
                })
        
        return users
    except Exception as e:
        logger.error(f"Failed to get users: {e}")
        return []


# ========== Event Data ==========

ACTIVITIES = [
    {"id": 1, "name": "Cloud Computing Workshop", "date": "2026-04-10", "time": "14:00-16:00", "location": "Online (Zoom)", "tags": ["tech", "cloud", "workshop"], "description": "Learn about AWS, Docker, and Kubernetes basics"},
    {"id": 2, "name": "Campus Hackathon 2026", "date": "2026-04-15", "time": "09:00-18:00", "location": "Lee Shau Kee Building Room 101", "tags": ["coding", "hackathon", "competition"], "description": "24-hour coding challenge with prizes"},
    {"id": 3, "name": "Career Development Workshop", "date": "2026-04-12", "time": "15:00-17:00", "location": "Jockey Club Building Room 202", "tags": ["career", "workshop", "job"], "description": "Resume review and interview tips"},
    {"id": 4, "name": "Badminton Friendly Match", "date": "2026-04-18", "time": "10:00-12:00", "location": "Sports Center Court 3", "tags": ["sports", "badminton", "competition"], "description": "All skill levels welcome"},
    {"id": 5, "name": "Python Programming Workshop", "date": "2026-04-09", "time": "19:00-21:00", "location": "Online (Teams)", "tags": ["coding", "python", "workshop"], "description": "Beginner-friendly Python introduction"},
]


def get_all_activities() -> List[Dict]:
    return ACTIVITIES


def get_activity_by_id(activity_id: int) -> Dict:
    for activity in ACTIVITIES:
        if activity['id'] == activity_id:
            return activity
    return None


# ========== Prompt Templates ==========

MATCH_PROMPT_TEMPLATE = """
You are a campus assistant at Hong Kong Baptist University, responsible for matching students based on interests.

【Current User Interests】
{user_interest}

【Other Users Interests List】
{other_users}

Based on interest similarity, recommend 1-2 most matching users.
- Do NOT reveal user IDs, only mention matching interests
- Provide simple communication suggestions
- Be friendly and encouraging
- If no other users, reply: "No matching users found. Be the first to share your interests!"

【Your Response】:
"""

EVENT_RECOMMEND_PROMPT_TEMPLATE = """
You are a campus assistant at Hong Kong Baptist University, responsible for recommending events to students.

【User Interests】
{user_interests}

【Available Events List】
{events}

Based on user interests, recommend 2-3 most suitable events.
- Explain the reason for each recommendation
- Include event name, date, time, location
- Be enthusiastic and encouraging

【Your Response】:
"""

COURSE_QA_PROMPT_TEMPLATE = """
You are a course assistant for the Computer Science department at Hong Kong Baptist University.

【Course Information】
- COMP7940 Cloud Computing: Project report due April 14, 2026 at 23:59, presentations on April 15 or 22
- For other course questions, suggest students check Moodle or ask the professor

【Student Question】
{question}

Answer in English, be concise and friendly. If you don't know something, suggest checking Moodle.

【Your Answer】:
"""


# ========== Preset User Data ==========

PRESET_USERS = [
    {"user_id": 111111111, "interests": ["tech", "coding", "python"]},
    {"user_id": 222222222, "interests": ["tech", "cloud", "aws"]},
    {"user_id": 333333333, "interests": ["sports", "badminton", "basketball"]},
    {"user_id": 444444444, "interests": ["coding", "hackathon", "python"]},
]

def init_preset_users():
    """Initialize preset user data for demo matching"""
    logger.info("Loading preset user data...")
    for user in PRESET_USERS:
        set_user_interests(user["user_id"], user["interests"])
    logger.info(f"Loaded {len(PRESET_USERS)} preset users")


# ========== Telegram Command Handlers ==========

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    metrics["command_usage"]["start"] += 1
    
    welcome_msg = f"""
🎓 **Welcome to Campus Assistant Bot, {user.first_name}!**

I'm your AI-powered campus companion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 **Interest Matching**
• `/setinterest tech coding` - Set your interests
• `/addinterest basketball` - Add an interest
• `/removeinterest sports` - Remove an interest
• `/match interest` - Find matching users (AI-powered)

🎉 **Events**
• `/events` - View all events
• `/recommend` - Get AI-powered recommendations

💬 **Course Q&A**
• Just type your question!

📊 **System**
• `/logs` - View bot metrics and logs
• `/help` - Show this help

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    metrics["command_usage"]["help"] += 1
    
    help_msg = """
📖 **Help Guide**

**Interest Management**
`/setinterest tech coding` - Set your interests
`/addinterest basketball` - Add an interest
`/removeinterest sports` - Remove an interest
`/interests` - View your interests
`/match coding python` - Find matching users (AI)

**Events**
`/events` - View all events
`/recommend` - AI-powered recommendations

**System**
`/logs` - View bot statistics and logs
"""
    await update.message.reply_text(help_msg, parse_mode='Markdown')


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logs command - show metrics and recent logs"""
    user_id = update.effective_user.id
    metrics["command_usage"]["logs"] += 1
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    # Calculate success rate
    if metrics['total_requests'] > 0:
        success_rate = metrics['successful_responses'] / metrics['total_requests'] * 100
        success_rate_text = f"{success_rate:.1f}%"
    else:
        success_rate_text = "N/A"
    
    log_msg = f"""
📊 **Bot Statistics**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**📈 Metrics**
• Total Requests: `{metrics['total_requests']}`
• Successful: `{metrics['successful_responses']}`
• Errors: `{metrics['error_responses']}`
• Success Rate: `{success_rate_text}`

**🔧 Command Usage**
"""
    for cmd, count in sorted(metrics["command_usage"].items()):
        log_msg += f"• /{cmd}: {count}\n"
    
    await update.message.reply_text(log_msg, parse_mode='Markdown')


async def set_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setinterest command"""
    user_id = update.effective_user.id
    metrics["command_usage"]["setinterest"] += 1
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Example: `/setinterest tech coding sports`")
        return
    
    interests = [arg.lower() for arg in context.args]
    set_user_interests(user_id, interests)
    
    insert_request_log(user_id, "setinterest", str(interests), "Success")
    
    await update.message.reply_text(
        f"✅ Set {len(interests)} interests: `{', '.join(interests)}`\n\nTry `/match interest` to find matching users!",
        parse_mode='Markdown'
    )


async def add_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addinterest command"""
    user_id = update.effective_user.id
    metrics["command_usage"]["addinterest"] += 1
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Example: `/addinterest basketball`")
        return
    
    interest = ' '.join(context.args).lower()
    add_user_interest(user_id, interest)
    interests = get_user_interests(user_id)
    
    insert_request_log(user_id, "addinterest", interest, str(interests))
    
    await update.message.reply_text(
        f"✅ Added: `{interest}`\nCurrent: `{', '.join(interests)}`",
        parse_mode='Markdown'
    )


async def remove_interest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removeinterest command"""
    user_id = update.effective_user.id
    metrics["command_usage"]["removeinterest"] += 1
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Example: `/removeinterest sports`")
        return
    
    interest = ' '.join(context.args).lower()
    interests = get_user_interests(user_id)
    
    if interest not in interests:
        await update.message.reply_text(f"❌ You don't have interest `{interest}`")
        return
    
    delete_user_interest(user_id, interest)
    new_interests = get_user_interests(user_id)
    
    insert_request_log(user_id, "removeinterest", interest, str(new_interests))
    
    await update.message.reply_text(
        f"✅ Removed: `{interest}`\nRemaining: `{', '.join(new_interests)}`",
        parse_mode='Markdown'
    )


async def view_interests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /interests command"""
    user_id = update.effective_user.id
    metrics["command_usage"]["interests"] += 1
    
    interests = get_user_interests(user_id)
    
    if not interests:
        await update.message.reply_text("📭 No interests yet. Use `/setinterest tech coding`")
    else:
        await update.message.reply_text(f"📝 **Your interests:**\n\n`{', '.join(interests)}`", parse_mode='Markdown')


async def match_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /match command - AI-powered interest matching with Prompt Template"""
    user_id = update.effective_user.id
    metrics["command_usage"]["match"] += 1
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    # Get user input interest
    if not context.args:
        await update.message.reply_text("❌ Example: `/match coding python`")
        return
    
    user_interest = ' '.join(context.args).lower()
    
    # Save to Redis
    add_user_interest(user_id, user_interest)
    
    # Get other users
    other_users = get_all_users_with_interests(exclude_user_id=user_id)
    
    if not other_users:
        await update.message.reply_text("🔍 No other users found. Be the first to share your interests!")
        insert_request_log(user_id, "match", user_interest, "No other users")
        return
    
    # Build prompt using template
    prompt = MATCH_PROMPT_TEMPLATE.format(
        user_interest=user_interest,
        other_users=json.dumps(other_users, ensure_ascii=False, indent=2)
    )
    
    # Show thinking message
    loading_msg = await update.message.reply_text("🔍 Finding matching users with AI...")
    
    try:
        # Call LLM
        response = gpt.submit(prompt)
        await loading_msg.edit_text(response)
        
        # Save to cloud log
        insert_request_log(user_id, "match", user_interest, response[:500])
        
    except Exception as e:
        logger.error(f"Match error: {e}")
        await loading_msg.edit_text("Sorry, match service is temporarily unavailable.")
        metrics["error_responses"] += 1


async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /events command - list all events"""
    user_id = update.effective_user.id
    metrics["command_usage"]["events"] += 1
    
    activities = get_all_activities()
    
    response = "🎉 **Upcoming Events**\n\n"
    for act in activities:
        response += f"**{act['id']}. {act['name']}**\n"
        response += f"   📅 {act['date']} | {act['time']}\n"
        response += f"   📍 {act['location']}\n"
        response += f"   🏷️ {', '.join(['#' + t for t in act['tags']])}\n\n"
    
    response += "Use `/recommend` for AI-powered suggestions!"
    
    await update.message.reply_text(response, parse_mode='Markdown')
    
    insert_request_log(user_id, "events", "list_events", "Success")


async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /recommend command - AI-powered event recommendations with Prompt Template"""
    user_id = update.effective_user.id
    metrics["command_usage"]["recommend"] += 1
    
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    # Get user interests
    interests = get_user_interests(user_id)
    user_interests_str = ', '.join(interests) if interests else "No interests set yet"
    
    # Get all events
    events = get_all_activities()
    events_str = json.dumps(events, ensure_ascii=False, indent=2)
    
    # Build prompt using template
    prompt = EVENT_RECOMMEND_PROMPT_TEMPLATE.format(
        user_interests=user_interests_str,
        events=events_str
    )
    
    loading_msg = await update.message.reply_text("🎯 Getting AI-powered recommendations...")
    
    try:
        response = gpt.submit(prompt)
        await loading_msg.edit_text(response)
        
        insert_request_log(user_id, "recommend", user_interests_str, response[:500])
        
    except Exception as e:
        logger.error(f"Recommend error: {e}")
        await loading_msg.edit_text("Sorry, recommendation service is temporarily unavailable.")
        metrics["error_responses"] += 1


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages - AI-powered Course Q&A with Prompt Template"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Rate limiting
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏰ Too many requests. Please try again later.")
        return
    
    # Update metrics
    metrics["total_requests"] += 1
    
    # Log request
    logger.info(f"REQUEST - User: {user_id}, Message: {text}")
    
    # Build prompt using template
    prompt = COURSE_QA_PROMPT_TEMPLATE.format(question=text)
    
    # Show thinking message
    loading_msg = await update.message.reply_text("🤔 Thinking...")
    
    try:
        # Call LLM
        response = gpt.submit(prompt)
        await loading_msg.edit_text(response)
        
        # Log response
        logger.info(f"RESPONSE - User: {user_id}, Response: {response[:100]}...")
        metrics["successful_responses"] += 1
        
        # Save to cloud log
        insert_request_log(user_id, "course_qa", text, response[:500])
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await loading_msg.edit_text("Sorry, I'm having trouble. Please try again later.")
        metrics["error_responses"] += 1


# ========== Main Application ==========

def init_redis():
    """Initialize Redis connection"""
    global redis_client, config
    try:
        config = configparser.ConfigParser()
        config.read('config.ini')
        
        url = config['REDIS']['URL']
        token = config['REDIS']['TOKEN']
        
        redis_client = Redis(url=url, token=token)
        redis_client.ping()
        logger.info("✅ Redis connected successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        return False


def main():
    """Main entry point"""
    global gpt
    
    logger.info("🚀 Starting Campus Assistant Bot...")
    
    # Initialize Redis
    if not init_redis():
        logger.error("Failed to connect to Redis. Exiting...")
        return
    
    # Initialize preset users for demo
    init_preset_users()
    
    # Initialize ChatGPT
    gpt = ChatGPT(config)
    logger.info("✅ ChatGPT initialized")
    
    # Load Telegram token
    telegram_token = config['TELEGRAM']['ACCESS_TOKEN']
    
    # Create application
    app = ApplicationBuilder().token(telegram_token).build()
    
    # Add command handlers
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('logs', logs_command))
    
    app.add_handler(CommandHandler('interests', view_interests_command))
    app.add_handler(CommandHandler('setinterest', set_interest_command))
    app.add_handler(CommandHandler('addinterest', add_interest_command))
    app.add_handler(CommandHandler('removeinterest', remove_interest_command))
    app.add_handler(CommandHandler('match', match_command))
    
    app.add_handler(CommandHandler('events', events_command))
    app.add_handler(CommandHandler('recommend', recommend_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, callback))
    
    logger.info("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == '__main__':
    main()