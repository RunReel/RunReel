# What the player draws

Contents: where pictures come from · colours · arrays · grids · binary trees · linked lists · graphs · when nothing is drawn · sizes that stay readable

## Where pictures come from

- Each step is shown just before its line runs, so a line's effect appears on the next step. Printed text is the exception: it shows on the last step recorded before it was printed, or on the first step if none was recorded yet. That's usually the print line's own step, but when the print calls one of the file's functions, as in `print(solve(x))`, it's the step where that call returns.
- Pictures come from the local variables of the recorded functions, in every frame on the stack. In a whole-script run, the module's own variables count too.
- Under `--call` the module level isn't recorded, so a global the function reads isn't drawn. Pass the data in as an argument instead: `--call "dijkstra(G, 0)"`.
- Objects reachable only through attributes or containers aren't drawn. A linked list reached through a field, such as `self.head`, is the one exception.
- Several rules look at how variables are used anywhere in the file, by name. If another function in the same file uses the same names differently, the picture can change.
- Rebinding a name to a new object (`a = sorted(a)`) starts a new picture. Changing it in place (`a[i] = x`) shades the cells that changed.
- Values that fit none of the shapes appear in the variables pane. A value is shaded when its shown text changes, so a change hidden inside a `…` isn't. The pane cuts each value at 40 characters and shows a container inside another value only by its type, as `list(…)`, so data held in an object's fields or in a dict of tuples can't be followed there.

## Colours

The player has no legend, so tell the user what the colours mean:

| Colour | Means |
|---|---|
| Yellow line with an orange bar, in the code | The line about to run. Grey lines have already run. |
| Orange shading | What changed on this step: an array or grid cell whose value changed or that was added (a whole new array or grid starts unshaded), a linked-list node that is new or has a new label, and a variables-pane value that changed or is new in a call already running (a new call's arguments aren't shaded). A node that was only relinked isn't shaded: its new link is drawn thick instead. Tree and graph nodes never get this shading; a pale fill inside a ring goes with the ring. |
| Blue outline | The grid cell the current line works on. |
| Light blue shading | Another `name[a ± k][b ± k]` cell of the grid on the current line, such as the cells `dp[i][j] = dp[i - 1][j] + 1` reads. |
| Orange-red ring | The graph node being worked on, or a tree node a variable points at. |
| Thick orange-red line | The graph edge being looked at, or a linked-list pointer that changed on this step. |
| Blue ring | The graph neighbour being looked at. |
| Green | A visited graph node. In a BFS that marks nodes as it queues them, green means queued, not yet processed. |
| Blue `↑ name` labels | Pointers: int variables under the array cells they index, and variables or fields such as `self.head` under the list nodes they hold. |
| Blue arrows in a grid | Reads more than one cell away from the cell being worked on. |

These are the light theme's colours. In dark mode, which the reel follows unless its Theme button is set otherwise, the fills are darker (an olive code line, and dark amber, blue and green shading), while rings, lines and labels keep their colours.

The reel writes infinity as ∞ (`dist=∞`), where the summary and `read_reel.py` print `inf`.

## Arrays

- **Drawn for:** lists, tuples and deques whose items are all plain values (numbers, strings, booleans, None) or small tuples of plain values, such as `(dist, node)` pairs.
- **Shows:** each cell with its index, and cells that changed shaded orange.
- **Pointers:** an int variable of the running function appears as `↑ name` under the cell it points at, when it's between 0 and the length (inclusive) and either:
  - the file indexes this list with it somewhere, as in `a[i]`, `a[i + 1]`, `a[lo:hi]` or `a[min(i, j)]`, or
  - it's one of `i`, `j`, `k`, `l`, `r`, `lo`, `hi`, `mid`, `left`, `right`, `low`, `high`, `start` or `end`, it isn't used inside any subscript in the file, and the file does index this list.
- The pointer sits at the variable's value, so `a[i - 1]` still puts `↑ i` at `i`. A size used in a slice, such as `k` in `a[:k]`, shows as a pointer that doesn't move.
- Only the first 200 items are kept; the rest show as `+N more`.
- **Not drawn as arrays:** strings (single values), sets, dicts, lists of objects, ragged nested lists, `bytes`, `range`, `array.array` and numpy arrays. A list held only in an attribute, such as `self.items`, isn't drawn either.
- A list held by several calls, such as a module-level list passed to a function or a list passed down in recursion, is drawn once, under the running call's name and with its pointers. A call that makes its own list, by slicing or copying as merge sort does, gets its own picture, and the running call's pointers can appear under its callers' copies too. The variables pane lists every call. Keep recursive inputs tiny.

## Grids

- **Drawn for:**
  - a non-empty list of lists of plain values, all the same non-zero length, or
  - a list of two or more strings of the same length, when the file indexes it as `name[a][b]` with variables (`maze[r][c]`, `maze[r][c + 1]`).
- **Shows:** row and column numbers, and cells that changed shaded orange.
- **Focus:** the cell named by the first plain `name[a][b]` on the current line, with no `± k`, is outlined, with `a` and `b` taken from int variables. In a search, that's often the neighbour being tested, such as `maze[nr][nc]`. On lines that don't index the grid, the outline goes on the `name[a][b]` the file writes most often, at the variables' current values.
- **Other cells on the line:** the line's other `name[a ± k][b ± k]` cells are shaded light blue, and those more than one cell away get an arrow into the focus. In a line that pulls values in, such as `dp[i][j] = dp[i - 1][j] + dp[i][j - 1]`, those are exactly the cells it reads. In one that pushes a value out, such as `dp[i + 1][j] += dp[i][j]`, the outline is on the cell read and the shading on the cell written. An index that isn't a variable plus or minus a number, such as `best[i - 1][c - w[i]]`, gets no shading and no arrow.
- Grids over 2,500 cells show a 40 × 60 window around the focus, with the real row and column numbers.
- **Not drawn as grids:** ragged rows, rows that are tuples (shown as an array of tuples), and dicts keyed by `(row, col)`.
- A list-of-lists adjacency list whose rows happen to be the same length is drawn as a grid, not a graph.

## Binary trees

- **Drawn for:** objects with a field called `left` or `right`, from the first node. With other field names, a class counts as a tree once both of its child fields have held a node. Until then it's drawn as a linked list, so when the fields have other names, pick keys that go both ways early, such as 5, 3, 8. A third field that points back up, like `parent`, is ignored.
- At least one variable must point at a node. The tree is drawn from its root, with each node placed by its rank in order, so a node moves right only when a smaller key is inserted.
- **Node labels:** the first of the fields `key`, `val`, `value`, `data` or `item` that exists, otherwise the first plain field, otherwise the class name.
- Nodes that variables point at are highlighted, with the variables' names underneath. In recursion this marks the whole path of calls.
- **Not drawn:** trees with a list of children (n-ary trees and tries), heaps stored in a list (drawn as an array), and trees reached only through an attribute, such as `self.root`, until a variable points at a node.

## Linked lists

- **Drawn for:** objects with a field called `next` (or `_next`), from the first node; with `prev` (or `_prev`) too, they're doubly linked. With other field names, a class counts once its objects link through one field (a singly linked list) or two that point back at each other (doubly linked).
- **Also found through an object's field**, such as a `LinkedList` with `self.head`.
- **Shows:** each chain of nodes on its own row, in the order of its link field (`next`, or whichever field links the nodes), ending in `None`, an arrow back into a loop, or an arrow across to a list it joins. Variables of the running function that point at nodes, and fields such as `self.head`, appear under them as `↑ name` labels.
- **Node labels:** as for trees, the first of `key`, `val`, `value`, `data` or `item`, otherwise the first plain field, otherwise the class name.
- A link that changed on this step is drawn thick and orange-red. In the usual loop that reverses a list, it shows as two rows, the part already reversed and the rest: each pass moves one node to the front of the reversed row, with its new link drawn thick. A recursive reversal adds each node to the end of the reversed row instead, and the rest of the list points across into it. New nodes and nodes whose label changed are shaded; a node that was only relinked isn't.
- Chains over 30 nodes show a 30-node window around the pointers, and at most 10 chains are drawn.
- **Not drawn:** a link field that holds an index into an array, and nodes held only in a list or dict until a variable points at one.

## Graphs

- **Drawn for:** a non-empty dict whose keys are plain values and whose values are lists, tuples, sets or deques of neighbours, `(neighbour, weight)` pairs, or dicts from neighbour to weight. At least one neighbour must also be a key, so `{"fruit": ["apple", "pear"]}` isn't a graph.
- **Shows:** nodes on a circle, in the order they first appear in the dict: each key, then its neighbours, then the next key. Edges are arrows with their weights. If every edge has a twin going back with the same weight, the graph is drawn undirected, with plain lines. Repeated edges fan out as arcs, and an edge from a node to itself is a small loop.
- **Current node:** the variable the code indexes the graph with, as in `graph[u]`, nearest the running line. Falls back to variables called `node`, `u`, `cur`, `current`, `v` or `x`.
- **Neighbour:** the loop variable of `for v in graph[u]`, `for v, w in graph[u]`, `for v, w in graph[u].items()` or `for v in graph.get(u, ...)`. Falls back to variables called `neighbour`, `neighbor`, `nbr`, `w`, `nxt` or `next_node`. The edge between the current node and its neighbour is highlighted.
- **Labels:** a dict or list called `dist`, `distance`, `dists` or `cost`, or else one the code indexes with the node variables (`indegree[v]`, `best[v]`), is written under each node.
- **Visited:** a set called `visited`, `seen` or `done`, else any set of nodes, else a list or dict of True and False indexed by node. A list of True and False colours the nodes rather than labelling them. In a breadth-first search that marks nodes as it queues them, nodes turn green when queued, not when they're taken off the queue.
- **Not drawn as graphs:** list-of-lists adjacency lists, edge lists (drawn as arrays of pairs), dicts keyed by tuples, and graphs made of node objects. A loop the player doesn't recognise, such as `for v in sorted(graph[u])`, loses the neighbour highlight unless the variable has one of the fallback names. Lists and dicts indexed only by that variable then don't label or colour the nodes either, unless they're called `dist`, `distance`, `dists` or `cost`, or `visited`, `seen` or `done`.

## When nothing is drawn

| Situation | What to do |
|---|---|
| The data is a string or numbers (palindromes, parsing, gcd, Fibonacci) | If the code only indexes single characters (`s[i]`) and compares them, pass `list("abba")` instead of `"abba"`, and tell the user the reel used a list. Slices compare differently on a list (`s[1:3] == "bb"` is False), so otherwise follow the variables pane. |
| The function reads a module-level global and runs under `--call` | Pass the data in as an argument, or record the whole script if its main block calls the function. |
| The structure lives only in an attribute (`self.items`, `self.adj`, `self.grid`) | Trees appear in methods once a variable points at a node (`cur = self.root`). Otherwise the reel can show only the variables pane's short form, so say so. |
| Adjacency stored as a list of lists | If the code only uses `len(adj)` and `adj[u]`, pass `dict(enumerate(adj))`, as in `--call "bfs(dict(enumerate(ADJ)), 0)"`. Code that loops over `adj` itself or uses `enumerate(adj)` behaves differently on a dict, so leave that alone. |
| The file only defines functions and ran without `--call` | Only the `def` lines run. Add `--call "f(...)"` with a small input. |
| The algorithm is in a file the traced file imports | Run that file instead. Other files are never recorded. |
| The steps ran out on set-up | Use a smaller input, build it in `--call`, or record only the algorithm's lines with `--lines`. |

## Sizes that stay readable

- At 1× the player shows two steps a second: 100 steps take about 50 seconds. Keep reels under about 300 steps.
- Measured on Python 3.12 and later: binary search on 7 items takes 17 steps, inserting 5 keys into a binary search tree 88, Dijkstra on 4 nodes and 5 edges 60, and the 8 × 7 longest common subsequence table for strings of 7 and 6 characters 153. On 3.10 and 3.11, code with comprehensions takes a few more steps (Dijkstra 63, the table 156).
- Pictures stay readable up to about 12 array items, 8 × 8 grids, 15 tree nodes, 10 graph nodes and 8 list nodes.
