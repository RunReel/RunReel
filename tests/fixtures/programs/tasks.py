import asyncio


async def work(name, rounds):
    done = []
    for r in range(rounds):
        await asyncio.sleep(0)
        done.append(f"{name}{r}")
    return done


async def gather_all():
    a, b = await asyncio.gather(work("a", 2), work("b", 1))
    return a + b


def main():
    return asyncio.run(gather_all())
