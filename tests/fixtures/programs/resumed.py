"""Generators that started outside the recording and are resumed inside it."""

import threading

threads = []


def counter():
    n = 0
    while True:
        n += 1
        yield n


def elsewhere():
    yield "first, on another thread"
    yield "then here"


def never_started():
    yield 1


LOADED = counter()
next(LOADED)  # started while the file loads, before recording begins


def start_on_another_thread(gen):
    threads.append(threading.Thread(target=next, args=(gen,)))
    threads[-1].start()
    threads[-1].join()


def main():
    loaded = [next(LOADED) for _ in range(2)]
    moved = elsewhere()
    start_on_another_thread(moved)
    here = next(moved)
    fresh = never_started()
    try:
        fresh.throw(ValueError("thrown in before it ever ran"))
    except ValueError:
        caught = True
    return loaded, here, caught
