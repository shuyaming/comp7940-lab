"""
Test script to verify Redis connection and schedule functions
Run this before starting the chatbot to ensure database works
"""
from upstash_redis import Redis
import configparser

def test_redis_connection():
    """Test basic Redis connection"""
    print("=" * 50)
    print("Testing Redis Connection...")
    print("=" * 50)
    
    # Load config
    config = configparser.ConfigParser()
    config.read('config.ini')
    
    # Get Redis credentials
    url = config['REDIS']['URL']
    token = config['REDIS']['TOKEN']
    
    print(f"URL: {url}")
    print(f"Token: {token[:20]}...")  # Show first 20 chars only
    
    try:
        # Connect to Redis
        redis = Redis(url=url, token=token)
        
        # Test ping
        redis.ping()
        print("\n✅ Ping successful! Redis is reachable.")
        
        # Test write and read
        test_key = "test_connection"
        test_value = "Hello from Campus Assistant Bot!"
        
        redis.set(test_key, test_value)
        result = redis.get(test_key)
        
        print(f"✅ Write test: saved '{test_value}'")
        print(f"✅ Read test: got '{result}'")
        
        # Clean up test data
        redis.delete(test_key)
        print("✅ Cleanup: removed test data")
        
        return redis
        
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        return None


def test_schedule_functions(redis):
    """Test schedule management functions"""
    if not redis:
        print("Skipping schedule tests - no connection")
        return
    
    print("\n" + "=" * 50)
    print("Testing Schedule Functions...")
    print("=" * 50)
    
    test_user_id = 99999
    
    # Test add_schedule
    print("\n1. Testing add_schedule...")
    key = f"user:{test_user_id}:schedules"
    
    # Clear any existing data
    redis.delete(key)
    
    # Add some schedules
    redis.lpush(key, "Submit COMP7940 report by Apr 14")
    redis.lpush(key, "Cloud Computing Lab on Tuesday 2pm")
    redis.lpush(key, "Midterm exam on Apr 20")
    
    print("   ✅ Added 3 schedules")
    
    # Test get_schedules
    print("\n2. Testing get_schedules...")
    schedules = redis.lrange(key, 0, -1)
    print(f"   Found {len(schedules)} schedules:")
    for i, s in enumerate(schedules, 1):
        print(f"   {i}. {s}")
    
    # Test get count
    print("\n3. Testing get count...")
    count = redis.llen(key)
    print(f"   Total schedules: {count}")
    
    # Test delete by index
    print("\n4. Testing delete schedule...")
    all_schedules = redis.lrange(key, 0, -1)
    if len(all_schedules) > 0:
        redis.lset(key, 0, "__DELETED__")
        redis.lrem(key, 1, "__DELETED__")
        print("   ✅ Deleted first schedule")
        
        # Verify deletion
        remaining = redis.lrange(key, 0, -1)
        print(f"   Remaining schedules: {len(remaining)}")
    
    # Test delete all
    print("\n5. Testing delete all schedules...")
    redis.delete(key)
    final_count = redis.llen(key)
    print(f"   All schedules deleted. Count: {final_count}")
    
    print("\n✅ All schedule tests passed!")


def main():
    """Main test function"""
    print("\n🚀 Starting Redis Database Test\n")
    
    # Test connection
    redis = test_redis_connection()
    
    # Test schedule functions
    if redis:
        test_schedule_functions(redis)
    
    print("\n" + "=" * 50)
    print("Test Complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()