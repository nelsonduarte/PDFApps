"""The annotations Python 3.10 evaluates on import evaluate here too.

The snap is built on core22, whose Python is 3.10. There a module's, a
class body's and a function's annotations are evaluated when they are
defined, so one that names something not imported (``TypeGuard`` dropped
from ``app/pdf_io.py``'s ``from typing import ...``) is a NameError when
the module is imported. From 3.14 (PEP 649) they are evaluated only when
something reads them: the import, the app and the rest of the suite all
go on working, and the snap is the only place it shows.

``inspect.get_annotations`` evaluates them the way 3.10 did on import: a
quoted annotation stays a string, and so does everything in a module
with ``from __future__ import annotations``. A name missing (NameError),
an attribute missing from a module (AttributeError) and ``"str" | None``
(TypeError) are what that evaluation can raise. Not covered: functions
nested in another function, and an unquoted name defined further down
the module, which 3.10 cannot see yet at that point and 3.14 can.
"""

import importlib
import inspect
import pkgutil
import typing

import app
from app import pdf_io


def test_pdf_io_public_functions_type_hints_resolve():
    hints = {name: typing.get_type_hints(getattr(pdf_io, name))
             for name in pdf_io.__all__}
    assert hints["is_file_in_use_error"]["return"] == typing.TypeGuard[OSError]


def _app_modules():
    names = ["app"] + sorted(
        info.name for info in pkgutil.walk_packages(app.__path__, "app."))
    return [importlib.import_module(name) for name in names]


def _defined_in(module):
    """The module, and the classes and functions defined in it, with the
    methods of those classes (properties' accessors included)."""
    yield module.__name__, module
    stack = [(module.__name__, value) for value in vars(module).values()]
    seen = set()
    while stack:
        prefix, obj = stack.pop()
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
        if isinstance(obj, property):
            stack.extend((prefix, f) for f in (obj.fget, obj.fset, obj.fdel)
                         if f is not None)
            continue
        if not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        if getattr(obj, "__module__", None) != module.__name__ or id(obj) in seen:
            continue
        seen.add(id(obj))
        name = f"{module.__name__}.{obj.__qualname__}"
        yield name, obj
        if inspect.isclass(obj):
            stack.extend((name, value) for value in vars(obj).values())


def test_every_annotation_evaluated_on_import_evaluates():
    checked, failed = [], []
    for module in _app_modules():
        for name, obj in _defined_in(module):
            checked.append(name)
            try:
                inspect.get_annotations(obj)
            except (NameError, AttributeError, TypeError) as exc:
                failed.append(f"{name}: {type(exc).__name__}: {exc}")
    assert "app.pdf_io.is_file_in_use_error" in checked
    assert "app.i18n._update_config" in checked
    assert failed == []
