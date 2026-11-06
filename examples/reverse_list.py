class Node:
    def __init__(self, value, next=None):
        self.value = value
        self.next = next


def build(values):
    """A linked list holding values in order, built front to back."""
    head = tail = None
    for value in values:
        node = Node(value)
        if tail is None:
            head = node
        else:
            tail.next = node
        tail = node
    return head


def reverse(head):
    """Reverse a linked list in place, turning its next pointers round one at a time."""
    prev = None
    cur = head
    while cur is not None:
        nxt = cur.next
        cur.next = prev
        prev = cur
        cur = nxt
    return prev


if __name__ == "__main__":
    node = reverse(build([1, 2, 3, 4, 5]))
    while node is not None:
        print(node.value)
        node = node.next
