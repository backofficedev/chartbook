"""Every text file ChartBook reads or writes is UTF-8, and every one it writes has ``\\n`` line endings.

On Windows, Python reads and writes text in the system's code page unless told
otherwise, and writes ``\\r\\n`` for each ``\\n``. ChartBook's files are UTF-8, and
what it writes to a store is the same bytes on every machine that shares it:
so each call says so, and this test reads the source to see that it does. The
command output ChartBook reads (git's) is UTF-8 too, and a byte that is not
does not stop it.
"""

import ast
from pathlib import Path

import chartbook

SOURCE = Path(chartbook.__file__).parent
SUBPROCESS = {"run", "Popen", "check_output", "check_call", "call"}
NOT_FILES = {"os", "webbrowser", "tarfile", "zipfile", "gzip", "io", "codecs", "Image"}


def _mode(call: ast.Call, position: int):
    mode = call.args[position].value if len(call.args) > position and isinstance(call.args[position], ast.Constant) else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value.value if isinstance(keyword.value, ast.Constant) else "?"
    return mode


def _lacking(call: ast.Call) -> list:
    function = call.func
    name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
    owner = function.value.id if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name) else None
    said = {keyword.arg for keyword in call.keywords}
    if None in said:
        return []  # **keywords: not to be read from here
    lacking = []
    if name == "read_text" and not call.args and "encoding" not in said:
        lacking.append("encoding")
    elif name == "write_text":
        if "encoding" not in said and len(call.args) < 2:
            lacking.append("encoding")
        if "newline" not in said and len(call.args) < 4:
            lacking.append("newline")
    elif name == "open" and owner not in NOT_FILES:
        position = 1 if isinstance(function, ast.Name) else 0
        mode = _mode(call, position)
        if mode == "?" or (mode is not None and "b" in mode):
            return []
        if "encoding" not in said and len(call.args) < position + 4:
            lacking.append("encoding")
        if mode and any(letter in mode for letter in "wax") and "newline" not in said:
            lacking.append("newline")
    elif name in SUBPROCESS and owner in ("subprocess", None) and ({"text", "universal_newlines"} & said):
        if "encoding" not in said:
            lacking.append("encoding")
    return lacking


def test_every_text_read_and_write_says_utf_8_and_every_write_says_its_line_ending():
    found = []
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                lacking = _lacking(node)
                if lacking:
                    found.append(f"{path.relative_to(SOURCE.parent)}:{node.lineno} lacks {' and '.join(lacking)}")
    assert not found, "\n".join(found)


def test_the_check_finds_what_it_is_for():
    calls = {
        'p.read_text()': ["encoding"],
        'p.write_text("x", encoding="utf-8")': ["newline"],
        'open(p, "w")': ["encoding", "newline"],
        'open(p, "rb")': [],
        'open(p, "a", encoding="utf-8", newline="")': [],
        'subprocess.run(["git"], text=True)': ["encoding"],
        'os.open(p, 0)': [],
    }
    for text, lacking in calls.items():
        assert _lacking(ast.parse(text).body[0].value) == lacking, text
