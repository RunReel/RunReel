# Troubleshooting

Contents: exit codes · error messages · summaries that need a second look · when runreel doesn't finish · limits · working from a RunReel clone

## Exit codes

| Code | Meaning |
|---|---|
| 0 | A reel was written and the summary printed. This includes runs where the program raised, called `sys.exit`, hit the step limit or was stopped. |
| 1 | No reel. A line on standard error starting with `runreel:` says why. |
| 2 | The command line was wrong. Nothing ran. |
| 130 | Ctrl+C arrived while the program wasn't running: before it started, or while the reel was being written. If no `reel:` line was printed, run it again. |

runreel's exit code doesn't follow the program's: `sys.exit(3)` still gives exit 0, with a reel whose summary says `error SystemExit: 3`. `os._exit(N)` ends runreel at once with code N and no reel, and a crash or a signal, as from `os.abort()` or `os.kill`, ends it with that signal's code. So judge by the `reel:` line. Rarely, exit code 1 comes with a raw Python traceback instead of a `runreel:` line: under `--call`, the file's top-level code raised `GeneratorExit`, `CancelledError` or another `BaseException` that isn't an `Exception`, `SystemExit` or `KeyboardInterrupt`.

## Error messages

runreel's own messages start with `runreel:`. A wrong command line prints a `usage:` line first, then `runreel: error:` or `runreel run: error:`. Anything else on standard error comes from the program.

| Message | Cause | What to do |
|---|---|---|
| `can't read FILE: No such file or directory` | The path is wrong. It's relative to the current folder. | Fix the path. |
| `can't read X: ...` with `--call`, where X is a data file or the error doesn't fit | The file's top-level code failed to open something while loading, and runreel reports it as if it couldn't read the file. | Check the path: like python, runreel resolves relative paths from the current folder, so run it from the folder the program expects. If the file is missing, ask the user for it. Recording the whole script opens the same file, so it won't help. |
| `can't read FILE: it isn't UTF-8 text` | The file isn't saved as UTF-8. | Save it as UTF-8. |
| `FILE doesn't compile: MESSAGE (line N)` | A syntax error in the file, or a `--call` value that isn't a single expression. runreel compiles with its own Python, which may be newer or older than the user's. | Check whether the file parses, without running it: `python3 -c "import ast, sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" FILE`. If it does, fix `--call`: one expression, with no assignment, no `;` and no leading spaces. Combine calls as a tuple, `f(1), f(2)`. |
| `FILE doesn't compile: invalid non-printable character U+FEFF (line 1)` | The file starts with a byte order mark, which some Windows editors add. | Save it as UTF-8 without a byte order mark. |
| `FILE failed while loading: TYPE: MESSAGE` | With `--call`, top-level code raised while loading. A common case is `input()` at the top level. | If that code and the main block only compute, record the whole script, with `--stdin` for its input. Otherwise ask to record a copy of the function you want. Moving the code under `if __name__ == "__main__":` changes the user's file, so ask before that too. |
| `FILE failed while loading: ModuleNotFoundError: No module named 'X'`, or in a whole-script run, a summary with `error ModuleNotFoundError` | The code imports a package that isn't in runreel's Python environment. | Ask before adding any package, and take its name from the project's own files (`requirements.txt`, `pyproject.toml`) or from the user, never from the import name: they often differ, as `yaml` comes from PyYAML. Then add the project's packages to the run, as in `uvx --with-requirements requirements.txt runreel run FILE`, or install runreel into the environment that already has them. |
| `FILE exited while loading (sys.exit(...))` | With `--call`, top-level code called `sys.exit()`, often through argument parsing. | If the top-level code and the main block only compute, record the whole script, with the program's arguments after `--`. Otherwise ask to record a copy of the function you want. Moving the code under `if __name__ == "__main__":`, as runreel suggests, changes the user's file, so ask before that too. |
| `CALL failed before any of its code ran: NameError: name 'X' is not defined` | The call uses a name the file doesn't define at top level, or one set only in its main block. | Check the spelling, or build the value inside `--call`. |
| `CALL failed before any of its code ran: TypeError: ...` | The arguments don't match the function. | Match the function's parameters. If `--lines` is in use, also check that it covers lines that ran. |
| `no step was recorded: CALL ran none of FILE's own code; call one of the functions it defines` | The call only ran builtins, library code or another file's code, the brackets are missing (`--call f`), or it called a generator or `async` function, which only builds a generator or coroutine. | Call a function defined in this file, with brackets. Wrap a generator, as in `--call "list(evens(5))"`, and an `async` function, as in `--call "asyncio.run(main())"` if the file imports `asyncio`. |
| `no step was recorded: none of the lines given with --lines ran` | `--lines` names lines that never ran. | Check the line numbers. They're the file's own numbers, also with `--call`. |
| `FILE was stopped at the T s time limit before any step was recorded` | Nothing was recorded before the time limit: slow top-level code, a call that never entered the file's code, or `--lines` that excluded everything. | Find the slow part, check `--call` and `--lines`, or raise `--timeout`. |
| `FILE was stopped by Ctrl+C before any step was recorded` | Ctrl+C before any step. | Run it again. |
| `can't read STDIN_FILE: ...` | The `--stdin` file is missing or isn't UTF-8. | Fix that file. On Linux and macOS, `--stdin /dev/stdin` passes a pipe through; on Windows, save the input to a file first. |
| `can't write OUT: ...`, or `No such file or directory` with the `--out` path | The reel can't be written there, or its folder doesn't exist. | Create the folder first, or choose another path. |
| `the player isn't built yet` | Running from a RunReel clone without building. | See the last section. |
| `runreel: error: unrecognized arguments: ...` with a usage line | A program option placed before `--`, or a misspelt option. | Put the program's own arguments last, after `--`. |
| `runreel run: error: ...` with a usage line | A bad option or value, such as `--max-steps 0` or `--lines 5-3`. | Fix the command. |

## Summaries that need a second look

- `error EOFError: EOF when reading a line`: the program wanted input and got none. Add `--stdin FILE`.
- `error SystemExit: N`: the program called `sys.exit(N)`. `sys.exit()` and `sys.exit(0)` aren't errors.
- `error AttributeError: '_Output' object has no attribute 'buffer'`: the program writes bytes with `sys.stdout.buffer.write`, which runreel's capture of printed text doesn't support yet. Record a copy that uses `sys.stdout.write` or `print`.
- A program reading `open(0)` or `os.read(0, ...)` that fails, or waits until the time limit: it reads runreel's own standard input, not `--stdin`. Give runreel the input there as well, as in `runreel run solution.py --stdin input.txt < input.txt` (in PowerShell, `cmd /c "runreel run solution.py --stdin input.txt < input.txt"`).
- `error UnsupportedOperation: fileno`: the program calls `sys.stdin.fileno()`, which runreel's `--stdin` can't answer yet. Ask to record a copy that reads `sys.stdin.buffer` or `os.read(0, ...)` instead, and say so.
- `5000 steps (truncated: ...)`: the recording filled up. Use a smaller input or `--lines`. Any `result` after a truncated run, or one using `--lines`, can show a changed list or object as it was at the last recorded step.
- `stopped at the 60 s time limit (...)`: probably an infinite loop. The last steps of the reel show where it was going round, unless the summary also says `truncated`, when the reel holds only the first steps. Then record again with small limits, such as `--max-steps 100 --timeout 10`, or with `--lines` on the loop you suspect.
- `stopped by Ctrl+C` without anyone pressing Ctrl+C: the program raised `KeyboardInterrupt` itself.
- `result 'VALUE'` in quotes: either the result really is a string, or it's a value the recorded steps never held, such as a tuple built by the `--call` expression.
- `printed N lines` counts newlines written to standard output, which is kept in the reel. Standard error goes to the terminal and isn't kept.

## When runreel doesn't finish

- **The program installed its own Ctrl+C handler** (`signal.signal(signal.SIGINT, ...)`) and never ends, or on Python 3.10, loops round a bare `except:`. The time limit can't stop it. Run runreel under an outer limit, such as `timeout 120 runreel run ...` on Linux. When that fires, `timeout` exits with code 124 and no reel is written.
- **The program left a non-daemon thread running.** The reel is complete and the `reel:` line printed, but runreel doesn't exit until the thread does, and a shell tool that waits for the command shows nothing until then. Check whether the `--out` file exists, and stop the process if needed. Text the thread prints after the `reel:` line goes to the terminal, not the reel.
- **`--stdin /dev/stdin` reads a pipe that never closes.** runreel reads all of its input before the program starts, so the time limit hasn't begun. Only use it with a pipe that ends.

## Limits

| Limit | Value | Past it |
|---|---|---|
| Steps recorded | 5,000 (`--max-steps`) | Recording stops and the program runs on unrecorded. |
| Time | 60 s (`--timeout`, 0 for none) | The program is stopped and the reel is kept. |
| Items per list, tuple, set or dict | 200 | The rest are counted, not shown. |
| Objects per step | 1,000 | Further objects show as placeholders. |
| Characters per string | 1,000 | Cut, with `…`. |
| Printed text | 1,000,000 characters | Counted, not kept. |
| Threads | The main thread only | Other threads run but aren't recorded. |
| Files | Only the given file | Imported files and libraries run but aren't recorded. |

## Working from a RunReel clone

Before RunReel is installed from PyPI, a clone of its repository can run it. Setting one up downloads dependencies and runs the repository's Makefile and npm scripts, so ask the user first, and only use a clone they trust. It needs make, uv, Node.js 22 with npm, and network access.

In the clone's root folder:

```sh
make setup
make build
uv run runreel run examples/dijkstra.py --call "dijkstra(G, 0)"
```

From another folder, set it up with `make -C PATH/TO/RunReel setup build`, then run `uv run --project PATH/TO/RunReel runreel run ...`. If the program imports other packages, ask first, take their names from the project's own files, and add them to the run, as in `uv run --project PATH/TO/RunReel --with-requirements requirements.txt runreel run ...`. Run `make build` again after pulling changes: the packaged player is built from the source, and an old build draws older pictures.
