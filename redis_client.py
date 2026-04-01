"""
Redis Database Client for Upstash Redis
Used to store and manage user schedules for the Campus Assistant Bot
"""
import logging
import configparser
from upstash_redis import Redis

# Global Redis client instance
redis_client = None


def init_redis():
    """
    Initialize Redis connection using config.ini
    Call this once when the bot starts
    """
    global redis_client
    try:
        # Load configuration
        config = configparser.ConfigParser()
        config.read('config.ini')
        
        # Get Redis connection details
        url = config['REDIS']['URL']
        token = config['REDIS']['TOKEN']
        
        # Create Redis client
        redis_client = Redis(url=url, token=token)
        
        # Test connection
        redis_client.ping()
        logging.info("✅ Redis connected successfully")
        return True
        
    except Exception as e:
        logging.error(f"❌ Redis connection failed: {e}")
        return False


def add_schedule(user_id: int, event: str):
    """
    Add a schedule event for a user
    Stores in Redis List: user:{user_id}:schedules
    New events are added to the beginning (LIFO style)
    """
    key = f"user:{user_id}:schedules"
    redis_client.lpush(key, event)
    logging.info(f"User {user_id} added schedule: {event}")


def get_schedules(user_id: int):
    """
    Get all schedule events for a user
    Returns list of events, newest first
    Returns empty list if no schedules
    """
    key = f"user:{user_id}:schedules"
    schedules = redis_client.lrange(key, 0, -1)
    return schedules


def delete_schedule(user_id: int, index: int):
    """
    Delete a schedule at specific index (0 = first/newest)
    Returns True if deleted, False if index invalid
    """
    key = f"user:{user_id}:schedules"
    
    # Get all schedules
    all_schedules = redis_client.lrange(key, 0, -1)
    
    # Check if index is valid
    if 0 <= index < len(all_schedules):
        # Mark the entry for deletion
        redis_client.lset(key, index, "__DELETED__")
        # Remove all marked entries
        redis_client.lrem(key, 1, "__DELETED__")
        logging.info(f"User {user_id} deleted schedule at index {index}")
        return True
    
    logging.warning(f"User {user_id} tried to delete invalid index {index}")
    return False


def delete_all_schedules(user_id: int):
    """
    Delete all schedules for a user
    """
    key = f"user:{user_id}:schedules"
    count = redis_client.llen(key)
    redis_client.delete(key)
    logging.info(f"User {user_id} deleted all {count} schedules")


def get_schedules_count(user_id: int):
    """
    Get total number of schedules for a user
    """
    key = f"user:{user_id}:schedules"
    return redis_client.llen(key)


def get_schedule_by_index(user_id: int, index: int):
    """
    Get a specific schedule by index (0 = first/newest)
    Returns the event string or None if index invalid
    """
    key = f"user:{user_id}:schedules"
    schedules = redis_client.lrange(key, 0, -1)
    
    if 0 <= index < len(schedules):
        return schedules[index]
    return None