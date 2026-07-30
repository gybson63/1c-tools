"""Применение BSL-патчей расширения (&ИзменениеИКонтроль) к модулям основной CF."""

from __future__ import annotations

import re
from dataclasses import dataclass

METHOD_START = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<keyword>Процедура|Функция|Procedure|Function)\s+"
    r"(?P<name>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)"
    r"(?P<sig>\([^)]*\))"
    r"(?P<export>\s+Экспорт|\s+Export)?"
    r"(?P<rest>.*)$",
    re.MULTILINE,
)

METHOD_END = re.compile(
    r"^\s*(КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

DIRECTIVE = re.compile(r"^\s*&")

CHANGE_AND_CONTROL = re.compile(
    r'^\s*&ИзменениеИКонтроль\s*\(\s*"(?P<target>[^"]+)"\s*\)\s*$'
    r"|^\s*&ChangeAndValidate\s*\(\s*\"(?P<target_en>[^\"]+)\"\s*\)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

INSERT_START = re.compile(r"^\s*#Вставка\s*$|^\s*#Insert\s*$", re.IGNORECASE)
INSERT_END = re.compile(r"^\s*#КонецВставки\s*$|^\s*#EndInsert\s*$", re.IGNORECASE)
DELETE_START = re.compile(r"^\s*#Удаление\s*$|^\s*#Delete\s*$", re.IGNORECASE)
DELETE_END = re.compile(r"^\s*#КонецУдаления\s*$|^\s*#EndDelete\s*$", re.IGNORECASE)

INTERCEPTOR_DIRS = (
    "&перед",
    "&после",
    "&вместо",
    "&изменениеиконтроль",
    "&before",
    "&after",
    "&around",
    "&changeandvalidate",
)


@dataclass
class Method:
    name: str
    keyword: str
    signature: str
    is_export: bool
    is_function: bool
    directives: list[str]
    body_lines: list[str]
    full_text: str
    start: int
    end: int
    target_name: str | None = None  # for &ИзменениеИКонтроль


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_methods(source: str) -> list[Method]:
    text = _normalize_newlines(source)
    methods: list[Method] = []
    pos = 0
    while True:
        m = METHOD_START.search(text, pos)
        if not m:
            break
        line_start = text.rfind("\n", 0, m.start()) + 1
        directives: list[str] = []
        before = text[:line_start].rstrip("\n")
        if before:
            prev_lines = before.split("\n")
            di = len(prev_lines) - 1
            collected: list[str] = []
            while di >= 0 and DIRECTIVE.match(prev_lines[di] or ""):
                collected.append(prev_lines[di])
                di -= 1
            directives = list(reversed(collected))

        end_m = METHOD_END.search(text, m.end())
        if not end_m:
            break
        end_line = end_m.end()
        if end_line < len(text) and text[end_line] == "\n":
            end_line += 1

        block = text[m.start() : end_m.start()]
        body = block[len(m.group(0)) :]
        if body.startswith("\n"):
            body = body[1:]
        body_lines = body.split("\n") if body else []
        keyword = m.group("keyword")
        is_function = keyword.lower() in ("функция", "function")
        full_start = m.start()
        if directives:
            dir_block = "\n".join(directives) + "\n"
            idx = text.rfind(dir_block, 0, m.start() + 1)
            if idx >= 0:
                full_start = idx
        full_text = text[full_start:end_line]

        target_name: str | None = None
        for d in directives:
            cm = CHANGE_AND_CONTROL.match(d.strip())
            if cm:
                target_name = cm.group("target") or cm.group("target_en")
                break

        methods.append(
            Method(
                name=m.group("name"),
                keyword=keyword,
                signature=m.group("sig") or "()",
                is_export=bool(m.group("export")),
                is_function=is_function,
                directives=directives,
                body_lines=body_lines,
                full_text=full_text,
                start=full_start,
                end=end_line,
                target_name=target_name,
            )
        )
        pos = end_line
    return methods


def apply_markers_to_body(base_body: list[str], marked_body: list[str]) -> list[str]:
    """Apply #Удаление / #Вставка markers from extension method onto base body.

    The marked body from &ИзменениеИКонтроль is a full reconstructed body with
    markers. We replay it: keep unmarked lines, skip delete blocks, insert insert blocks.
    """
    result: list[str] = []
    i = 0
    while i < len(marked_body):
        line = marked_body[i]
        if DELETE_START.match(line):
            i += 1
            while i < len(marked_body) and not DELETE_END.match(marked_body[i]):
                i += 1
            if i < len(marked_body):
                i += 1  # skip end marker
            continue
        if INSERT_START.match(line):
            i += 1
            while i < len(marked_body) and not INSERT_END.match(marked_body[i]):
                result.append(marked_body[i])
                i += 1
            if i < len(marked_body):
                i += 1
            continue
        result.append(line)
        i += 1
    return result


def _end_keyword(method: Method) -> str:
    if method.is_function:
        return "КонецФункции" if method.keyword.lower() in ("функция", "function") else "EndFunction"
    return "КонецПроцедуры" if method.keyword.lower() in ("процедура", "procedure") else "EndProcedure"


def _is_interceptor_directive(line: str) -> bool:
    low = line.strip().casefold()
    return any(x in low for x in INTERCEPTOR_DIRS)


def _render_method(method: Method, body_lines: list[str], *, name: str | None = None) -> str:
    lines: list[str] = []
    for d in method.directives:
        if _is_interceptor_directive(d):
            continue
        lines.append(d)
    export = " Экспорт" if method.is_export else ""
    proc_name = name or method.name
    lines.append(f"{method.keyword} {proc_name}{method.signature}{export}")
    lines.extend(body_lines)
    lines.append(_end_keyword(method))
    return "\n".join(lines).rstrip() + "\n"


def merge_extension_bsl_into_main(
    main_src: str | None,
    extension_src: str,
) -> tuple[str, list[str]]:
    """Merge extension BSL module into main configuration module text.

    Returns (merged_text, warnings).
    """
    warnings: list[str] = []
    main_text = _normalize_newlines(main_src or "")
    ext_methods = parse_methods(extension_src)
    main_methods = parse_methods(main_text)
    main_by_name = {m.name: m for m in main_methods}

    if not ext_methods:
        if extension_src.strip():
            warnings.append("В модуле расширения не найдено процедур/функций")
        return main_text, warnings

    # Apply change-and-control patches first
    replacements: list[tuple[int, int, str]] = []
    appended: list[str] = []

    for em in ext_methods:
        if em.target_name:
            target = main_by_name.get(em.target_name)
            if target is None:
                warnings.append(
                    f"Не найден целевой метод «{em.target_name}» в основной конфигурации "
                    f"для &ИзменениеИКонтроль ({em.name})"
                )
                continue
            new_body = apply_markers_to_body(target.body_lines, em.body_lines)
            rendered = _render_method(target, new_body)
            replacements.append((target.start, target.end, rendered))
        else:
            # New method (or Before/After/Around — treat as append if not interceptor-only)
            if any(_is_interceptor_directive(d) for d in em.directives):
                warnings.append(
                    f"Директива перехвата (&Перед/&После/&Вместо) не переносится автоматически: {em.name}"
                )
                continue
            if em.name in main_by_name:
                warnings.append(
                    f"Метод «{em.name}» уже есть в основной конфигурации — пропуск добавления из расширения"
                )
                continue
            appended.append(_render_method(em, em.body_lines))

    # Apply replacements from end to start
    result = main_text
    for start, end, text in sorted(replacements, key=lambda x: x[0], reverse=True):
        result = result[:start] + text + result[end:]

    if appended:
        if result and not result.endswith("\n"):
            result += "\n"
        if result and not result.endswith("\n\n"):
            result += "\n"
        result += "\n".join(appended)
        if not result.endswith("\n"):
            result += "\n"

    return result, warnings


def read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def write_text_bom(path: str, content: str) -> None:
    import os

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(normalized)
