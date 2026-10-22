import threading

running = []
results = []


def work(n):
    total = 0
    for i in range(n):
        total += i
    results.append(total)


def start(n):
    running.append(threading.Thread(target=work, args=(n,)))
    running[-1].start()


def finish():
    running.pop().join()
    return results[-1]


def main():
    start(50)
    mine = 0
    for i in range(5):
        mine += i
    theirs = finish()
    return mine, theirs
