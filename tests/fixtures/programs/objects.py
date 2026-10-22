from dataclasses import dataclass
from functools import wraps


@dataclass
class Point:
    x: int
    y: int


class Box:
    count = 0

    def __init__(self, size):
        self.size = size
        Box.count += 1

    @property
    def double(self):
        return self.size * 2

    def __lt__(self, other):
        return self.size < other.size

    @classmethod
    def made(cls):
        return cls.count


class Opened:
    def __enter__(self):
        self.open = True
        return self

    def __exit__(self, *exc):
        self.open = False
        return False


def logged(fn):
    @wraps(fn)
    def wrapper(*args):
        result = fn(*args)
        return result

    return wrapper


@logged
def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def counter():
    count = 0

    def bump():
        nonlocal count
        count += 1
        return count

    return bump


def main():
    boxes = sorted([Box(3), Box(1), Box(2)])
    sizes = [b.double for b in boxes]
    with Opened() as o:
        inside = o.open
    bump = counter()
    bump()
    p = Point(1, 2)
    ranked = sorted(["bb", "a", "ccc"], key=lambda s: len(s))
    return sizes, inside, bump(), Box.made(), fib(5), p.x, ranked
