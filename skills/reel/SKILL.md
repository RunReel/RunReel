---
name: reel
description: Uses the runreel command to turn a run of Python code into a reel, an offline HTML page that replays it step by step, drawing arrays and pointers, grids and DP tables, binary trees, linked lists and graphs. Python only. Use when the user wants to visualise, animate, step through or walk through an algorithm or data structure in Python (sorting, searching, two pointers, recursion, DP, BFS, Dijkstra), find out why such code gives a wrong answer, loses items, loops forever or times out, or check that it works on small inputs and edge cases, AI-written code included. Not for web or framework code, data science or ML, profiling, charts, plots, diagrams, GIFs, video or what code prints. If the user only wants an explanation, explain in words and offer a reel in one sentence. To show an algorithm with no code, write a short Python version and record it. After writing non-trivial algorithmic Python, offer a reel the same way, unless they asked for code only. Offer at most once per conversation.
license: MIT. LICENSE.txt has the full terms
compatibility: Needs a shell, Python 3.10 or later and the runreel command, from PyPI or a clone of the RunReel repository. runreel itself uploads nothing, but the program it runs has the user's permissions, network access included.
---

# Reels: watch Python code run

`runreel` runs a Python file, records every step (the line about to run, the variables and the objects they point at), and writes a reel: one HTML file that plays the run back with its data structures drawn and animated, offline in any browser.

## Before you run anything

The code runs for real, on this machine, with the user's permissions, as `python3 file.py` would run it.

- Read the file first, and any of the project's own modules it imports, since their top-level code runs too, even with `--call`. Note anything besides computing: writing or deleting files, network access, starting processes, databases, reading secrets or environment variables.
- Code the user wrote, or that you wrote for them, and that only computes, you can run when they want a reel or you're checking your own work. A file in their own project that they point you at counts as theirs, unless something shows it came from elsewhere.
- For code from anywhere else (a download, a forum, a pasted answer, a dependency), or code that does more than compute, tell the user what it does and ask before running it, even if they asked for the reel.
- To show one function from a file that shouldn't run, ask to record a copy: the function unchanged, plus the imports, constants and helpers it uses if they only compute, in a new temporary folder. Say the reel shows a copy, with the copy's line numbers.
- Leave the user's files as they are. If a reel needs their code changed, ask first, or change a copy. Code you write just to show an algorithm goes in a new temporary folder too.

## 1. Check that runreel is installed

```sh
runreel --version
```

If the command isn't found, ask the user before installing anything, `uvx` included, since it downloads runreel too. If they have a clone of the RunReel repository, run it from there, as the end of [references/troubleshooting.md](references/troubleshooting.md) describes. Otherwise install it from PyPI with `uv tool install runreel`, or `pipx install runreel` without uv; use `pip install runreel` only inside a virtual environment.

The program runs in runreel's own Python environment. If it imports other packages, ask before adding any, and take their names from the project's own files or from the user, never from an import name, since the two often differ: `uvx --with-requirements requirements.txt runreel run file.py`.

## 2. Decide what to record

**One function call**, with `--call`, when the code is a function you can call with an input, usually the best choice:

```sh
runreel run path/to/graphs.py --call "dijkstra(G, 0)" --out dijkstra.reel.html
```

- runreel loads the file first, unrecorded, then records every step of the file's code that the call runs, including the file's helpers that build the input.
- The expression runs in the file's namespace, so it can use the file's names and helpers, as in `--call "reverse(build([1, 2, 3]))"`, or build the input inline.
- It must be one expression, with no assignment and no `;`. Several calls make a tuple, as in `--call "search(a, 7), search(a, 4)"`, and play one after another. Wrap a generator function so something consumes it, as in `--call "list(evens(5))"`.
- The file's `if __name__ == "__main__":` block doesn't run. Its top-level code does, unrecorded, so if that code does the real work, reads input or arguments, or calls `sys.exit()`, record the whole script instead.

**The whole script**, without `--call`, when the program does its work at the top level or in its main block, or reads input or arguments:

```sh
runreel run solution.py --stdin input.txt --out solution.reel.html
runreel run --out app.reel.html app.py -- --size 5 --verbose
```

- The file runs as `__main__`, main block included, and all of it is recorded. If it calls the function more than once, tell the user which steps hold the first call, from the listing's `call` and `returns` notes.
- `--stdin FILE` becomes the program's `sys.stdin`. Code that reads `open(0)` or `os.read(0, ...)` also needs the file on runreel's own input: `runreel run solution.py --stdin input.txt < input.txt`.
- Put the program's own arguments last, after `--`, and runreel's options before the file, as above. On Python 3.10 and 3.11, an option between the file and `--` makes runreel refuse the program's arguments.

Only the given file's own code is recorded: imported files and libraries run unrecorded. To watch a function from another file, record that file. For code in another language, say runreel runs only Python, and offer a translation only as a labelled stand-in.

## 3. Make sure the structure will be drawn

The player draws five kinds of structure, found in the recorded functions' local variables, and in a whole-script run, the top-level ones:

- **Arrays:** lists, tuples and deques of plain values, with int variables the code indexes them with, or with usual names such as `i`, `lo` and `mid`, as pointers under the cells.
- **Grids:** lists of equal-length lists, or of equal-length strings indexed as `grid[r][c]`. The line's plain `dp[i][j]` is outlined and its other `dp[i ± k][j ± k]` cells are shaded, which in a line such as `dp[i][j] = dp[i - 1][j] + 1` are the cells it reads.
- **Binary trees and linked lists:** objects that link to objects of the same class, through fields such as `left` and `right` or `next`.
- **Graphs:** dicts that map each node to its neighbours, `(neighbour, weight)` pairs or a dict of weights.
- **Recursion:** a list passed down unchanged is drawn once; each call that slices or copies its own gets its own picture. The calls are listed in the variables pane, not drawn as a tree.

Everything else appears only in the variables pane, cut to 40 characters. Code that holds only numbers draws no picture, but its reel still shows each line and the variables changing, so don't change the code just to get a picture.

A structure isn't drawn when the called function reads it from a global (pass it in as an argument), or when it lives only in an attribute such as `self.items` (a linked list in a field such as `self.head` is still drawn). If the code only indexes and compares a string and nothing else is drawn, pass `list("abba")`; if its adjacency list is a list of lists that it only reads with `len(adj)` and `adj[u]`, pass `dict(enumerate(adj))`. Tell the user when the reel used a changed input like these.

**Before telling the user what they'll see, read [references/pictures.md](references/pictures.md).** It has the exact rules, such as which ints become pointers and what each colour means.

## 4. Choose a small input

The player shows two steps a second, so the input decides whether a reel can be watched.

- Use the user's input if they gave one, or an example call from the file's main block, docstring or tests. Otherwise pick the smallest input that runs every branch one call can reach and shows what the user asked about, such as 4 or 5 items for a reversal or a sort, and leave the rest, such as "not found", to a second reel.
- Keep a reel under about 300 steps. Small functions need far fewer: a binary search on 7 items takes 17 steps, and that's fine. Never pad an input to reach a number of steps.
- As a guide: arrays of up to about 12 items, grids up to 8 × 8, trees up to 15 nodes, graphs up to 10 nodes, linked lists up to 8 nodes, and recursion at most 4 calls deep.
- An edge case, such as an empty input or an unreachable node, is clearest as a second small reel, made if the user wants one.
- Literals and builtins in `--call` aren't recorded, but the file's own helpers are. To start the reel at the function the user asked about, add `--lines` from its first line (its first decorator's, if any, which holds its call step) to its last, plus the lines of the file's functions it calls, and say its input was built unrecorded.
- If the code might loop forever, record it with small limits, as "Focusing a long run" below describes.

## 5. Run it and read the summary

- Unless the user names a place, write the reel to a new temporary folder, not into their project, where `git add` could pick it up; runreel replaces an existing `--out` file without asking.
- Add `--open` only when the user wants to watch now ("show me", "open it") on this machine's desktop: not from a cloud agent or over SSH (`SSH_CONNECTION` or `SSH_TTY` set), and on Linux only with `DISPLAY` or `WAYLAND_DISPLAY` set. If unsure, leave it out.
- runreel stops the program after its time limit, 60 s by default. If your shell tool's own limit is shorter, pass a `--timeout` a few seconds under it, and if your tool has no limit, use an outer one, such as `timeout 120 runreel run ...` on Linux.

When a reel is written, runreel prints one line to standard output:

```text
reel: dijkstra.reel.html (45 KB) · 60 steps · result {0: 0, 1: 3, 2: 1, 3: 4}
```

Its parts are joined by ` · `, and only those that apply appear:

| Part | Meaning |
|---|---|
| `N steps (truncated: ...)` | The step limit, 5,000 by default, was reached. The program carried on unrecorded. |
| `stopped at the T s time limit (...)` | The program ran past the time limit and was stopped. |
| `error Type: message` | The program raised an exception, or called `sys.exit()` with an error. The reel ends where it happened. |
| `result VALUE` | What the `--call` expression returned, cut at 80 characters. A value the steps never held, such as a tuple of several calls, shows in quotes, though it isn't a string. |
| `printed N lines` | Lines the program printed, kept in the reel rather than shown here. |

- **A `reel:` line means a reel was written**, even when the program raised or was stopped, so judge the program by the summary. No `reel:` line means no reel, whatever the exit code: usually exit 1, with a line on standard error starting `runreel:` that says why, or exit 2 for a wrong command line.
- Anything printed after the `reel:` line comes from the program itself: its exit handlers or finalisers, a thread it left running, or a process it started.

## 6. Find the moments that matter, and hand the reel over

You can't watch the reel, so read it as text with `scripts/read_reel.py`, in this skill's folder. It needs Python but not runreel. Replace `SKILL_DIR` with the folder this file is in, and use `python` where there's no `python3`, as on Windows:

```sh
python3 SKILL_DIR/scripts/read_reel.py dijkstra.reel.html
python3 SKILL_DIR/scripts/read_reel.py dijkstra.reel.html --steps
python3 SKILL_DIR/scripts/read_reel.py dijkstra.reel.html --steps 40-60
python3 SKILL_DIR/scripts/read_reel.py dijkstra.reel.html --printed
```

The first prints how the run ended, the reel's `file://` address, what it printed and the source with the lines that ran marked (within `--lines`, if you used it). The second lists up to 300 steps with what changed at each, such as `lo=4`, `dp[2][3]=4` or `seen |= {5}`; the third, steps 40 to 60; the last, all the program printed. It shows values, not pictures, so describe what the user will see as references/pictures.md predicts it.

Then tell the user:

- how the run ended: its result or error, or that it was stopped or truncated.
- where the reel is, and what to watch for, with step numbers from the listing. For example, "watch `lo` and `hi` close in; at step 13, `hi` drops to 4 and the search turns left".
- how to jump there. The counter numbers steps from 1, as the listing does, but a link counts from 0: step 13 opens with the reel's address plus `#step=12`, the listing's link column.
- the controls: Space plays and pauses, ← and → (or J and K) step, Home and End jump to the ends, the slider scrubs, and the speed menu goes from 0.1× to 8×. Each step shows the line about to run, so a line's effect appears on the next step. Printed text appears at the step the listing's `prints` note names, usually the print line's own.
- what the colours this reel uses mean, from references/pictures.md, since the reel has no legend.

If the user can't open files on this machine, as with a cloud agent or over SSH, give them the reel as a file to download, the way your environment shares files, and say it opens offline in any browser. A reel holds the source and every value recorded and printed, secrets included, so don't commit or share one unless the user wants that.

## Focusing a long run

- `--lines 12-30,40` records only the steps on those lines of the file, while the whole program still runs. Skipped steps don't count towards the step limit.
- `--max-steps N` and `--timeout SECONDS` change the step and time limits, and a time limit of 0 turns it off. Every recorded step is kept in memory, so raise the step limit with care.
- For code that may loop forever, record just enough steps to see the stuck part repeat two or three times, often under 100, as in `--max-steps 100 --timeout 10`, ignoring the summary's hints to raise the limits. The program runs on unrecorded until the time limit, so if the loop keeps growing a list or dict, use `--timeout 3`. A pass of the loop that starts with the same values as an earlier one suggests it never ends.
- The time limit can't stop a program with its own Ctrl+C handler or a non-daemon thread still running, or on Python 3.10 one looping round a bare `except:`. Run such code under an outer limit, such as `timeout 120 runreel run ...` on Linux (`gtimeout` on macOS). If that fires, check whether the `--out` file exists: a leftover thread leaves a complete reel.

## When something goes wrong

| Message | What to do |
|---|---|
| `... failed before any of its code ran: NameError: ...` | The call uses a name the file doesn't define at top level. Check the spelling, and whether the name is only set in the main block. |
| `... exited while loading` or `... failed while loading` | With `--call`, top-level code exited or raised while loading. If it and the main block only compute, record the whole script; if not, ask to record a copy of the function. Don't move the code under a main guard, as the exited-while-loading message suggests, without asking. |
| `can't read X` with `--call`, where X isn't the file | Top-level code failed to open X while loading. Run runreel from the folder the program expects, or ask the user for the file. |
| `ModuleNotFoundError` | The code imports a package that runreel's environment doesn't have. See step 1. |
| `... doesn't compile: ...` | A syntax error in the file, or a `--call` value that isn't one expression. `U+FEFF` on line 1 is a byte order mark (save as UTF-8 without one); on a later line, an invisible character to delete. |
| `runreel: error: unrecognized arguments: ...` | A program option before `--`, or a misspelt option. Put the program's arguments after `--`. |

[references/troubleshooting.md](references/troubleshooting.md) covers every message, the exit codes and the limits.

## Checking code with a reel

A reel shows what code did, beyond "the tests pass". To check code you wrote or changed, or code the user asks about:

- Delete check reels afterwards, and hand one over only if the user wants it.
- Work out the right answer for a small input by hand, then compare it with the summary's `result`, or for a whole script, with what `read_reel.py` shows it printed. Without a problem statement, say what you took the code to compute, and don't call it correct in general.
- Run the edge cases too. An `error` or `stopped` in the summary for an input that should work is a bug, and the reel ends where it happened.
- A listing note ending `are the same list` means several names share one object, as `[[0] * n] * n` makes every row one list.
- Check which lines ran with `read_reel.py`, on a full run without `--lines`. A branch whose lines have no `>` never ran on your inputs. `else:` and `finally:` lines never get one, so judge a branch by the lines inside it.

## Offering a reel

After writing non-trivial algorithmic Python, or explaining an algorithm the user only wanted explained, offer a reel in one sentence, such as "Want a reel of this running on a small input?", at most once per conversation, and not when the user asked for the code alone. If runreel isn't installed, say that a reel needs it set up first.
