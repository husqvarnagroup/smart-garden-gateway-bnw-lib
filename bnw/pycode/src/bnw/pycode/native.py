# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib
import inspect
import os
import pkgutil
import subprocess
import tempfile
from graphlib import TopologicalSorter
from pathlib import Path

from redbaron import RedBaron  # type: ignore


def execute_source(source):
    ns = {}
    code = compile(source, "<string>", "exec")
    exec(code, ns, ns)
    return ns


def flatten_stubs(package, search_module, directory=None):
    search_module_name = search_module.__name__
    base_path = Path("stubs") if directory is None else Path(directory)
    dir = "/".join(search_module_name.split("."))
    os.listdir(base_path / dir)

    all_files = [os.path.join(path, name) for path, subdirs, files in os.walk(base_path / dir) for name in files]

    modules_code = []
    for file in all_files:
        if not file.endswith(".pyi"):
            continue
        with open(file, "r") as f:
            code = f.read()

            # convert file name to module name (remove stub directory, and remove trailing .pyi)
            path = file[len(str(base_path)) + 1 :]
            packages = path.split("/")
            packages[-1] = packages[-1][:-4]  # remove .pyi
            if packages[-1] == "__init__":
                del packages[-1]

            modules_code.append((".".join(packages), code))

    return merge_code(modules_code, search_module_name, package, validate_code=False)


def flatten_module(package, search_module):
    search_module_name = search_module.__name__
    modules_code = []
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=package.__path__, prefix=package.__name__ + ".", onerror=lambda x: None
    ):

        if modname == search_module_name or modname.startswith(search_module_name + "."):
            search_module = importlib.import_module(modname)

            try:
                source_code = inspect.getsource(search_module)
                modules_code.append((modname, source_code))
            except OSError:
                if search_module.__file__.endswith("__init__.py"):
                    # don't treat empty __init__.py files as error
                    pass
                else:
                    raise ValueError("Could not load source for %s" % modname)

    return merge_code(modules_code, search_module_name, package)


def merge_code(modules_code, search_module_name, package, validate_code=True):
    modules_dependency_graph = {}
    modules_modified_code = {}

    for name, source in sorted(modules_code, key=lambda i: i[0]):
        code = RedBaron(source)

        depends_on = set()

        for node in code.find_all("ImportNode"):
            if node.modules()[0].startswith(search_module_name):
                depends_on.add(node.value.dumps())
                node.replace("# " + " ".join(line for line in node.dumps().splitlines()))

        for node in code.find_all("FromImportNode"):
            if node.full_path_modules()[0].startswith(search_module_name):
                depends_on.add(node.value.dumps())
                node.replace("# " + " ".join(line for line in node.dumps().splitlines()))

        modules_dependency_graph[name] = depends_on
        modules_modified_code[name] = code.dumps()

    ts = TopologicalSorter(modules_dependency_graph)
    ordered_modules = list(ts.static_order())
    all_code = "\n\n".join(modules_modified_code[m] for m in ordered_modules)
    package_version = package.__version__ if hasattr(package, "__version__") else "?"
    header = (
        "# DO NOT EDIT! Auto-Generated Code (multiple modules flattened into single module)\n"
        + f"# package: {package.__name__}@{package_version}; module: {search_module_name}\n"
        + f"# included: {', '.join(ordered_modules)}\n"
        + "\n"
        + "# fmt: off\n"
        + "# flake8: noqa\n"
        + "# isort: skip_file\n"
        + "\n"
    )

    all_code = header + all_code

    if validate_code:
        # Validate resulting code
        execute_source(all_code)

    return all_code


def generate_stubs(module, directory):
    subprocess.call(["stubgen", "-q", "-p", module.__name__, "-o", directory])


def generate_protocol_py():
    import bnw.protocol

    return flatten_module(bnw, bnw.protocol)


def generate_protocol_pyi():
    import bnw.protocol

    with tempfile.TemporaryDirectory() as dir:
        generate_stubs(bnw.protocol, dir)
        return flatten_stubs(bnw, bnw.protocol, directory=dir)


def generate_utils_py():
    import bnw.utils

    return flatten_module(bnw, bnw.utils)
