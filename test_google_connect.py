import aiohttp
import asyncio

async def test_google():
    url = "https://www.google.com"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                print(f"Status: {resp.status}")
                print("Google reachable!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_google())
