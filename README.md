# RunReel

See what your AI actually wrote.

RunReel runs a piece of Python, records every step, and turns the run into a reel: one HTML file you can play, pause and scrub through. Lists show their `i` and `j` pointers moving, trees grow a node at a time, graphs light up as they get explored. It opens in any browser, offline. Nothing is uploaded anywhere.

I started building it because I kept getting code from AI tools that looked right and was only almost right. Reading it line by line was slow, and the tests only told me pass or fail. Watching it run is quicker. You can see the exact step where it goes wrong.

**This is an early preview.** It isn't on PyPI yet and the command-line options will still change. If you try it anyway, I'd love to hear what broke.

## Try it

You'll need [uv](https://docs.astral.sh/uv/) and Node 22.

```sh
git clone https://github.com/RunReel/RunReel.git
cd RunReel
make setup
make build
uv run runreel run examples/dijkstra.py --call "dijkstra(G, 0)" --open
```

That writes `examples/dijkstra.reel.html` and opens it. Space plays and pauses, the arrow keys (or J and K) step, and you can drag the slider to jump around. Add `#step=40` to the address to link someone straight to a step.

Some other ways to run it:

```sh
# a whole script, reading its input from a file like a contest judge would
uv run runreel run solution.py --stdin input.txt

# only record lines 12 to 30, e.g. the loop you actually care about
uv run runreel run sort.py --call "bubble([5, 2, 9, 1])" --lines 12-30

# anything after -- goes to the program, as if you'd run python app.py --n 5
uv run runreel run app.py -- --n 5
```

`uv run runreel run --help` lists everything else.

## What works right now

- Python 3.10 or newer. I work on 3.13, and every change is tested on 3.10 through 3.15.
- Five kinds of picture: arrays (with index variables like `i`, `lo`, `hi` and `mid` drawn as pointers), grids, binary trees, linked lists, and graphs stored as a dict of neighbour lists, optionally with weights.
- Trees and linked lists are recognised by how their objects point at each other, whatever the fields are called. If objects of one class link to each other through one field, that's a linked list. Through two, it's a binary tree, or a doubly linked list if the two point back at each other. With fields called `left` and `right`, or `next` and `prev`, the picture starts from the very first node; with other names, once two nodes are linked.
- A grid is a list of lists, or a list of strings you index as `grid[r][c]`. It outlines the cell your code is working on, so on a DP table like `dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])` you see which cells it reads to fill the next one. `examples/lcs.py` shows one filling up.
- A linked list gets a row per chain of nodes, with your variables under the nodes they point at. A `next` pointer that just changed is highlighted, so in `examples/reverse_list.py` you watch the pointers turn round one at a time as the nodes move over to the reversed list. Loops and lists that join up are drawn too.
- Everything else still shows up in the variables pane, so you can follow any program, just without a drawing.
- It records the first 5,000 steps, and big collections show their first 200 items.
- After 5,000 steps the program keeps going unrecorded, until it finishes or has run for a minute (`--timeout` changes that), so an infinite loop won't hang it. Ctrl+C stops it too, and you still get the reel of what ran.

## What's coming

Two directions, roughly in parallel:

- **Learning:** more pictures (linked lists, heaps, stacks and queues, hash maps) and a gallery of classic algorithms you can open and play.
- **Checking code:** point it at a real project and get a short list of anything surprising, like a function that changes its input, an exception that gets swallowed, or a file or network call you didn't expect. And `pytest --reel`, which turns a failing test into a reel that opens at the failure.

C++ and JavaScript come after that.

## Before you run it on someone else's code

RunReel runs your program for real. It's no different from typing `python yourfile.py`: same machine, same permissions. Don't point it at code you wouldn't be happy to run yourself.

## Contributing

It's early and I'm still moving things around, so please open an issue before starting on anything big. The most useful thing right now is a bug report with a small program that shows the problem.

## Licence

MIT. See [LICENSE](LICENSE).
