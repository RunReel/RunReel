class Node:
    def __init__(self, key):
        self.key = key
        self.left = None
        self.right = None


def insert(root, key):
    if root is None:
        return Node(key)
    node = root
    while True:
        if key < node.key:
            if node.left is None:
                node.left = Node(key)
                return root
            node = node.left
        else:
            if node.right is None:
                node.right = Node(key)
                return root
            node = node.right


def build(keys):
    root = None
    for key in keys:
        root = insert(root, key)
    return root


if __name__ == "__main__":
    print(build([5, 3, 8, 1, 4]).key)
