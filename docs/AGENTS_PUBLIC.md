# CAM Local: development and command control

Prefer the supported authenticated JSON command API when testing the desktop application. Read `docs/COMANDOS.md`. Use an isolated `--data-dir` for tests and close it with `app.close`; preserve the user's project and settings.

For frequent calls, add `work/cam-ui` and `work/roughing` to Python's module path, import `CommandClient` from `command_client`, and initialize it with the data directory. The client discovers the port and session token; never hardcode either.

Start with `calculate.start`, inspect `calculate.status`, then use `calculate.wait` before export or simulation. On a command timeout with `command_id`, query `command.result` instead of repeating the mutation.

The application starts empty. Keep examples opt-in, generated from original geometry. Add new controls to the command API as well as the visible interface.

Run `.venv/Scripts/python.exe scripts/test.py`. Build with `scripts/build.ps1`. Runtime data, generated models, NC files, dependencies and EXEs belong outside Git.
