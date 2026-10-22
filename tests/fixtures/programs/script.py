import sys


def read_numbers():
    count = int(input())
    values = list(map(int, sys.stdin.readline().split()))
    return count, values


def main():
    count, values = read_numbers()
    best = max(values[:count])
    print("best", best)
    for v in values:
        print(v, end=" ")
    print()


if __name__ == "__main__":
    main()
    sys.exit(0)
