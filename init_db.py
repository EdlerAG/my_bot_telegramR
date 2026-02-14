import asyncio
from database import Database
async def main():
    await Database.init()
    print("Нова база створена!")
if __name__ == "__main__":
    asyncio.run(main())
