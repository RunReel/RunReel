def count_up(n):
    for i in range(n):
        received = yield i
        if received:
            n += received


def relay(n):
    yield from count_up(n)
    return "done"


def main():
    total = 0
    for x in count_up(3):
        total += x
    g = count_up(2)
    first = next(g)
    second = g.send(1)
    try:
        g.throw(ValueError("stop"))
    except ValueError:
        total -= 1
    squares = sum(k * k for k in range(4))
    for y in relay(2):
        if y == 1:
            break
    closer = count_up(5)
    next(closer)
    closer.close()
    return total, first, second, squares
