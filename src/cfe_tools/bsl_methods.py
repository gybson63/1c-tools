"""Parse BSL methods and build &ИзменениеИКонтроль patches with insert/delete markers."""

from __future__ import annotations

import difflib
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


@dataclass
class Method:
    name: str
    keyword: str  # Процедура / Функция
    signature: str  # (Args)
    is_export: bool
    is_function: bool
    directives: list[str]
    body_lines: list[str]  # without header/footer
    full_text: str
    start: int
    end: int


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_methods(source: str) -> list[Method]:
    """Heuristic BSL method parser (Russian/English keywords)."""
    text = _normalize_newlines(source)
    methods: list[Method] = []
    pos = 0
    while True:
        m = METHOD_START.search(text, pos)
        if not m:
            break
        # Collect preceding directive lines (&НаСервере etc.)
        line_start = text.rfind("\n", 0, m.start()) + 1
        directives: list[str] = []
        # walk backwards over directive-only lines
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
        # include trailing newline if present
        if end_line < len(text) and text[end_line] == "\n":
            end_line += 1

        block = text[m.start() : end_m.start()]
        body = block[len(m.group(0)) :]
        if body.startswith("\n"):
            body = body[1:]
        body_lines = body.split("\n") if body else []
        # drop trailing empty from split artifacts carefully
        keyword = m.group("keyword")
        is_function = keyword.lower() in ("функция", "function")
        full_start = m.start()
        if directives:
            # start at first directive
            dir_block = "\n".join(directives) + "\n"
            idx = text.rfind(dir_block, 0, m.start() + 1)
            if idx >= 0:
                full_start = idx
        full_text = text[full_start:end_line]
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
            )
        )
        pos = end_line
    return methods


def methods_by_name(methods: list[Method]) -> dict[str, Method]:
    return {m.name: m for m in methods}


@dataclass
class MethodDiff:
    name: str
    status: str  # new | changed | removed | unchanged
    base: Method | None = None
    changed: Method | None = None


def diff_methods(base_src: str | None, changed_src: str) -> list[MethodDiff]:
    base_map = methods_by_name(parse_methods(base_src or ""))
    ch_map = methods_by_name(parse_methods(changed_src))
    names = sorted(set(base_map) | set(ch_map))
    result: list[MethodDiff] = []
    for name in names:
        b = base_map.get(name)
        c = ch_map.get(name)
        if b and not c:
            result.append(MethodDiff(name=name, status="removed", base=b))
        elif c and not b:
            result.append(MethodDiff(name=name, status="new", changed=c))
        elif b and c:
            if _method_equal(b, c):
                result.append(MethodDiff(name=name, status="unchanged", base=b, changed=c))
            else:
                result.append(MethodDiff(name=name, status="changed", base=b, changed=c))
    return result


def _method_equal(a: Method, b: Method) -> bool:
    """Compare methods by signature and body, ignoring trailing blank lines."""
    if a.keyword.lower() != b.keyword.lower():
        return False
    if a.signature.strip() != b.signature.strip():
        return False
    if a.is_export != b.is_export:
        return False
    body_a = [ln.rstrip() for ln in a.body_lines]
    body_b = [ln.rstrip() for ln in b.body_lines]
    while body_a and body_a[-1] == "":
        body_a.pop()
    while body_b and body_b[-1] == "":
        body_b.pop()
    return body_a == body_b


def build_marked_body(base_body: list[str], changed_body: list[str]) -> list[str]:
    """Build full method body with #Удаление / #Вставка markers from line diff."""
    sm = difflib.SequenceMatcher(a=base_body, b=changed_body, autojunk=False)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(base_body[i1:i2])
        elif tag == "delete":
            out.append("#Удаление")
            out.extend(base_body[i1:i2])
            out.append("#КонецУдаления")
        elif tag == "insert":
            out.append("#Вставка")
            out.extend(changed_body[j1:j2])
            out.append("#КонецВставки")
        elif tag == "replace":
            out.append("#Удаление")
            out.extend(base_body[i1:i2])
            out.append("#КонецУдаления")
            out.append("#Вставка")
            out.extend(changed_body[j1:j2])
            out.append("#КонецВставки")
    return out


def _end_keyword(method: Method) -> str:
    if method.is_function:
        return "КонецФункции" if method.keyword.lower() in ("функция", "function") else "EndFunction"
    return "КонецПроцедуры" if method.keyword.lower() in ("процедура", "procedure") else "EndProcedure"


def render_new_method(method: Method) -> str:
    """Copy method into extension without interceptor decorator."""
    lines: list[str] = []
    lines.extend(method.directives)
    export = " Экспорт" if method.is_export else ""
    lines.append(f"{method.keyword} {method.name}{method.signature}{export}")
    lines.extend(method.body_lines)
    lines.append(_end_keyword(method))
    return "\n".join(lines).rstrip() + "\n"


def render_modification_and_control(
    base: Method,
    changed: Method,
    name_prefix: str,
    include_context_directives: bool = True,
) -> str:
    """Render &ИзменениеИКонтроль interceptor with full marked body."""
    lines: list[str] = []
    # Keep context directives from changed (or base), skip existing interceptors
    src_dirs = changed.directives or base.directives
    for d in src_dirs:
        low = d.strip().lower()
        if any(
            x in low
            for x in (
                "&перед",
                "&после",
                "&вместо",
                "&изменениеиконтроль",
                "&before",
                "&after",
                "&around",
                "&changeandvalidate",
            )
        ):
            continue
        if include_context_directives:
            lines.append(d)
    lines.append(f'&ИзменениеИКонтроль("{base.name}")')
    keyword = changed.keyword
    proc_name = f"{name_prefix}{base.name}"
    # Interceptor typically without Экспорт
    lines.append(f"{keyword} {proc_name}{changed.signature}")
    marked = build_marked_body(base.body_lines, changed.body_lines)
    lines.extend(marked)
    lines.append(_end_keyword(changed))
    return "\n".join(lines).rstrip() + "\n"


def build_extension_module(
    base_src: str | None,
    changed_src: str,
    name_prefix: str,
) -> tuple[str, list[str]]:
    """Build extension module text from base/changed pair.

    Returns (module_text, warnings).
    """
    diffs = diff_methods(base_src, changed_src)
    chunks: list[str] = []
    warnings: list[str] = []
    for d in diffs:
        if d.status == "new" and d.changed:
            chunks.append(render_new_method(d.changed))
        elif d.status == "changed" and d.base and d.changed:
            try:
                chunks.append(render_modification_and_control(d.base, d.changed, name_prefix))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Skip method {d.name}: {exc}")
        elif d.status == "removed":
            warnings.append(f"Method removed in changes (not applied): {d.name}")
    text = "\n".join(chunks)
    if text and not text.endswith("\n"):
        text += "\n"
    return text, warnings


def read_text(path: str) -> str:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def write_text_bom(path: str, content: str) -> None:
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(normalized)
