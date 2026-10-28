# ruff: noqa: E501
"""A tiny HTML parser and CSS selector engine (stdlib only) so site knowledge can be tested against local fake pages
without a real browser. Supported selector subset (the real knowledge files must stay inside it, a test checks):
``tag  .class  #id  [attr]  [attr=v]  [attr*=v]  [attr^=v]  [attr$=v]  [attr~=v]``, descendant (space), child (``>``), comma lists.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
SKIP_TEXT = {"script", "style", "head", "title"}
BLOCKS = {"div", "p", "li", "tr", "h1", "h2", "h3", "br", "section", "header", "footer"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent: Node | None) -> None:
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def walk(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent  # type: ignore[assignment]
        if n is not self.root:
            self.cur = n.parent  # type: ignore[assignment]

    def handle_data(self, data):
        self.cur.children.append(data)


def parse_html(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def inner_text(node: Node) -> str:
    parts: list[str] = []

    def rec(n: Node) -> None:
        if n.tag in SKIP_TEXT:
            return
        for c in n.children:
            if isinstance(c, str):
                parts.append(c)
            else:
                rec(c)
                if c.tag in BLOCKS:
                    parts.append(" ")

    rec(node)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


# ---------------------------------------------------------------- selectors
_ATTR = re.compile(r"""\[\s*([\w:-]+)\s*(?:([*^$~]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]*)))?\s*\]""")
_TAG = re.compile(r"^[a-zA-Z][\w-]*|^\*")


class SelectorError(ValueError):
    pass


def _scan(s: str, seps: str) -> list[str]:
    """Split ``s`` at any char in ``seps`` that is outside [] and quotes; '>' is kept as its own token."""
    out: list[str] = []
    cur, depth, quote = "", 0, ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == "[":
            depth += 1
            cur += ch
        elif ch == "]":
            depth -= 1
            cur += ch
        elif depth == 0 and ch in seps:
            if cur:
                out.append(cur)
                cur = ""
            if ch == ">":
                out.append(">")
        else:
            cur += ch
    if cur:
        out.append(cur)
    return [p.strip() for p in out if p.strip()]


def _compound(s: str) -> dict:
    spec: dict = {"tag": None, "id": None, "classes": [], "attrs": []}
    rest = s
    m = _TAG.match(rest)
    if m:
        spec["tag"] = None if m.group(0) == "*" else m.group(0).lower()
        rest = rest[m.end():]
    while rest:
        if rest[0] == "#":
            m = re.match(r"#([\w-]+)", rest)
            if not m:
                raise SelectorError(s)
            spec["id"] = m.group(1)
        elif rest[0] == ".":
            m = re.match(r"\.([\w-]+)", rest)
            if not m:
                raise SelectorError(s)
            spec["classes"].append(m.group(1))
        elif rest[0] == "[":
            m = _ATTR.match(rest)
            if not m:
                raise SelectorError(s)
            val = m.group(3) if m.group(3) is not None else (m.group(4) if m.group(4) is not None else m.group(5))
            spec["attrs"].append((m.group(1), m.group(2), val))
        else:
            raise SelectorError(f"unsupported selector syntax: {s!r}")
        rest = rest[m.end():]
    return spec


def parse_selector(sel: str) -> list[list[tuple[str, dict]]]:
    """-> alternatives; each is a chain [(combinator-before-it, compound), ...]."""
    alts = []
    for part in _scan(sel, ","):
        chain: list[tuple[str, dict]] = []
        comb = " "
        for tok in _scan(part, " >"):
            if tok == ">":
                comb = ">"
                continue
            chain.append((comb, _compound(tok)))
            comb = " "
        if not chain:
            raise SelectorError(sel)
        alts.append(chain)
    if not alts:
        raise SelectorError(sel)
    return alts


def _match_compound(n: Node, c: dict) -> bool:
    if c["tag"] and n.tag != c["tag"]:
        return False
    if c["id"] and n.attrs.get("id") != c["id"]:
        return False
    if c["classes"] and not set(c["classes"]) <= n.classes():
        return False
    for name, op, val in c["attrs"]:
        if name not in n.attrs:
            return False
        have = n.attrs[name]
        if (
            (op == "=" and have != val)
            or (op == "*=" and val not in have)
            or (op == "^=" and not have.startswith(val))
            or (op == "$=" and not have.endswith(val))
            or (op == "~=" and val not in have.split())
        ):
            return False
    return True


def _match_chain(n: Node, chain: list[tuple[str, dict]], i: int) -> bool:
    comb, comp = chain[i]
    if not _match_compound(n, comp):
        return False
    if i == 0:
        return True
    p = n.parent
    if comb == ">":
        return p is not None and p.tag != "#root" and _match_chain(p, chain, i - 1)
    while p is not None and p.tag != "#root":
        if _match_chain(p, chain, i - 1):
            return True
        p = p.parent
    return False


def select(root: Node, sel: str) -> list[Node]:
    alts = parse_selector(sel)
    return [n for n in root.walk() if any(_match_chain(n, ch, len(ch) - 1) for ch in alts)]


def selector_supported(sel: str) -> bool:
    try:
        parse_selector(sel)
        return True
    except SelectorError:
        return False
