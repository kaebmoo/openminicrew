import asyncio
from dispatcher import dispatch

async def main():
    text = "ขอผลหวยเดือน กุมภาพันธ์ 2568 ขอดูทุกงวดเลย"
    text2 = "ตรวจเลข 820866 ในหวยทุกงวดของเดือนธันวาคม 2568"
    user_id = "test_user"
    user = {"telegram_chat_id": "123", "default_llm": "claude"}

    print("Testing Month Fetch:")
    result = await dispatch(user_id, user, text)
    if isinstance(result, tuple):
        print(result[0])
    
    print("\n\nTesting Check Month Fetch:")
    result2 = await dispatch(user_id, user, text2)
    if isinstance(result2, tuple):
        print(result2[0])

if __name__ == "__main__":
    asyncio.run(main())
