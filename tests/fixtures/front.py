import math


def lowest(a, key=abs):
    best, low = 0, math.inf
    for i in range(len(a)):
        if key(a[i]) < low:
            best, low = i, key(a[i])
    return best


def front(a, log):
    m = lowest(a)
    a[0], a[m] = a[m], a[0]
    log.append(m)
    return a
