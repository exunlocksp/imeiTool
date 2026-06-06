# PyInstaller runtime hook: pymobiledevice3 imports IPython/xonsh at load time
# for interactive CLI shells — stub them in the packaged app.
import sys
from types import ModuleType
from typing import Annotated


def _unavailable(*_args, **_kwargs):
    raise RuntimeError("Interactive shell is not available in the packaged app")


def _install_ipython() -> None:
    if "IPython" in sys.modules:
        return

    ipython = ModuleType("IPython")
    ipython.start_ipython = _unavailable
    ipython.embed = _unavailable
    sys.modules["IPython"] = ipython


def _install_xonsh() -> None:
    if "xonsh" in sys.modules:
        return

    class _FakeAliases(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class _FakeEnv:
        def __init__(self) -> None:
            self._data = {"PROMPT": "", "PATH": []}

        def __getitem__(self, key: str):
            return self._data[key]

        def get(self, key: str, default=None):
            return self._data.get(key, default)

    class _FakeXSH:
        ctx: dict = {}
        aliases = _FakeAliases()
        env = _FakeEnv()
        subproc_cd = ""

    xonsh = ModuleType("xonsh")
    built_ins = ModuleType("xonsh.built_ins")
    built_ins.XSH = _FakeXSH()

    cli_utils = ModuleType("xonsh.cli_utils")

    class Arg:
        def __init__(self, *args, **kwargs):
            pass

    class ArgParserAlias:
        def __init__(self, *args, **kwargs):
            pass

    cli_utils.Annotated = Annotated
    cli_utils.Arg = Arg
    cli_utils.ArgParserAlias = ArgParserAlias

    main_mod = ModuleType("xonsh.main")
    main_mod.main = _unavailable

    tools = ModuleType("xonsh.tools")
    tools.print_color = print

    sys.modules["xonsh"] = xonsh
    sys.modules["xonsh.built_ins"] = built_ins
    sys.modules["xonsh.cli_utils"] = cli_utils
    sys.modules["xonsh.main"] = main_mod
    sys.modules["xonsh.tools"] = tools


_install_ipython()
_install_xonsh()
