def check(x):
    if x < 0:
        raise ValueError(f"negative: {x}")
    return x


def safe(x):
    try:
        return check(x)
    except ValueError as error:
        return str(error)
    finally:
        x = 0


def again(x):
    try:
        check(x)
    except ValueError:
        raise


def main():
    results = [safe(2), safe(-1)]
    try:
        again(-5)
    except ValueError:
        results.append("re-raised")
    assert len(results) == 3, "three results"
    return check(-9)
