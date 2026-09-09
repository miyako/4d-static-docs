"""Tokenizer, recursive-descent parser and renderer for the 4D OOP `Syntax`
string grammar found in `references/syntaxEN.json`.

The grammar (591 overload lines across the 21-R3 corpus):

    member     := NAME callPart? returnPart?
    callPart   := '(' elements ')'
    elements   := element*
    element    := param | optGroup | ';'
    optGroup   := '{' elements '}'          -- may wrap a leading or trailing ';'
    param      := '...'? (italicName | bareWord) (':' typeName)?  |  '*'
    returnPart := ':' typeName

Design note — why this is lossless
----------------------------------
The tokenizer is **trivia-preserving**: every token records its exact source
spelling *and* the whitespace that preceded it, and the scanner consumes every
character of the input. Rendering is therefore `''.join(trivia + text)` over
the tokens the AST claims, and byte-equality with the source is achievable
without normalizing whitespace at all.

That also makes the round-trip gate meaningful rather than circular: the
renderer walks the *AST* and collects the token indices each node owns, then
asserts that the collected indices are exactly the full token range, in order.
A parser that silently dropped a token would fail the gate rather than
round-trip by accident.

Semantic normalization (stripping `**`/`*` emphasis, recovering `.sign` from
the malformed `.**sign**`) happens only when populating `memberName` and
parameter names — never in the render path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A `(` begins the parameter list, *except* when the source writes an empty
# parameter list inside the bold emphasis (`**.clear()**`, `**4D.Blob.new()**`),
# in which case the `()**` belongs to the name token.
# NB: matched with Pattern.match(line, pos), which anchors at pos, so no "^".
_EMPTY_CALL_IN_NAME_RE = re.compile(r"\(\s*\)\*\*")

_WORD_RE = re.compile(r"[A-Za-z0-9_.]+")
_ITALIC_RE = re.compile(r"\*(\.{0,3}[^*]+?)\*")
_TRIVIA_RE = re.compile(r"\s*")

# Emphasis/punctuation noise to strip when deriving a semantic name from a
# name token. Applied only to the semantic value, never to the rendered text.
_EMPHASIS_RE = re.compile(r"\*+")


class SyntaxParseError(ValueError):
    """Raised when a syntax line cannot be parsed. Never swallowed."""

    def __init__(self, message: str, line: str, position: int | None = None):
        self.line = line
        self.position = position
        where = f" at offset {position}" if position is not None else ""
        super().__init__(f"{message}{where}: {line!r}")


@dataclass
class Token:
    kind: str
    text: str
    trivia: str
    index: int = -1

    @property
    def source(self) -> str:
        return self.trivia + self.text


def tokenize(line: str) -> list[Token]:
    """Scan a single overload line into trivia-preserving tokens.

    Guarantees `''.join(t.source for t in tokens) == line`; this is asserted
    before returning, so a scanner gap can never reach the parser silently.
    """
    tokens: list[Token] = []
    pos = 0
    n = len(line)

    def take_trivia() -> str:
        nonlocal pos
        m = _TRIVIA_RE.match(line, pos)
        trivia = m.group(0)
        pos = m.end()
        return trivia

    # --- name ---------------------------------------------------------------
    # Everything up to the first '(' that opens a real parameter list, or to
    # the ':' that introduces a return type for a property. Kept as one opaque
    # token so the three known emphasis typos (`.**sign**`, `*.verify**`) round
    # trip verbatim.
    trivia = take_trivia()
    start = pos
    while pos < n:
        ch = line[pos]
        if ch == "(":
            empty_call = _EMPTY_CALL_IN_NAME_RE.match(line, pos)
            if empty_call:
                pos = empty_call.end()
                continue
            break
        if ch == ":":
            break
        pos += 1
    name_text = line[start:pos].rstrip()
    if not name_text:
        raise SyntaxParseError("no member name found", line, start)
    # Whitespace trimmed off the end of the name belongs to the next token's
    # trivia, so nothing is lost.
    pos = start + len(name_text)
    tokens.append(Token("NAME", name_text, trivia))

    # --- rest ---------------------------------------------------------------
    simple = {"(": "LPAREN", ")": "RPAREN", "{": "LBRACE", "}": "RBRACE",
              ";": "SEMI", ":": "COLON"}
    while pos < n:
        trivia = take_trivia()
        if pos >= n:
            if trivia:
                # Trailing whitespace: attach to a zero-width EOL token so the
                # render stays byte-exact.
                tokens.append(Token("EOL", "", trivia))
            break
        ch = line[pos]
        if ch in simple:
            tokens.append(Token(simple[ch], ch, trivia))
            pos += 1
            continue
        if line.startswith("...", pos):
            tokens.append(Token("ELLIPSIS", "...", trivia))
            pos += 3
            continue
        if ch == "*":
            m = _ITALIC_RE.match(line, pos)
            if m:
                tokens.append(Token("ITALIC", m.group(0), trivia))
                pos = m.end()
                continue
            tokens.append(Token("STAR", "*", trivia))
            pos += 1
            continue
        m = _WORD_RE.match(line, pos)
        if m:
            tokens.append(Token("WORD", m.group(0), trivia))
            pos = m.end()
            continue
        raise SyntaxParseError(f"unexpected character {ch!r}", line, pos)

    for i, token in enumerate(tokens):
        token.index = i

    rendered = "".join(t.source for t in tokens)
    if rendered != line:
        raise SyntaxParseError(
            "tokenizer did not consume the whole line "
            f"(reconstructed {rendered!r})",
            line,
        )
    return tokens


@dataclass
class ParsedParam:
    name: str
    typeName: str | None
    optional: bool
    variadic: bool
    isLiteralStar: bool
    italicized: bool
    tokens: list[int] = field(default_factory=list)


@dataclass
class ParsedOverload:
    rawSyntax: str
    memberName: str
    receiverPath: str | None
    hasCallPart: bool
    params: list[ParsedParam]
    returnType: str | None
    tokens: list[Token]
    nameTokens: list[int] = field(default_factory=list)
    structuralTokens: list[int] = field(default_factory=list)
    returnTokens: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _semantic_name(name_text: str) -> tuple[str, str | None, list[str]]:
    """Strip emphasis from a name token.

    Returns (memberName, receiverPath, notes). `receiverPath` is the
    `4D.<Class>` prefix for a constructor, None for an instance member.
    """
    notes: list[str] = []
    cleaned = _EMPHASIS_RE.sub("", name_text).strip()
    if cleaned.endswith("()"):
        cleaned = cleaned[:-2]
    if name_text.count("*") != 4 or not name_text.startswith("**") or not name_text.rstrip().endswith("**"):
        notes.append(
            "markdown emphasis is malformed in the source; the member name was "
            "recovered by stripping all '*' characters"
        )
    if cleaned.startswith("."):
        return cleaned, None, notes
    if "." in cleaned:
        receiver, _, member = cleaned.rpartition(".")
        return "." + member, receiver, notes
    return cleaned, None, notes


class _Parser:
    def __init__(self, line: str, tokens: list[Token]):
        self.line = line
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        while self.pos < len(self.tokens) and self.tokens[self.pos].kind == "EOL":
            self.pos += 1
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> Token:
        token = self.peek()
        if token is None:
            raise SyntaxParseError("unexpected end of line", self.line)
        self.pos += 1
        return token

    def expect(self, kind: str) -> Token:
        token = self.next()
        if token.kind != kind:
            raise SyntaxParseError(
                f"expected {kind}, found {token.kind} ({token.text!r})", self.line
            )
        return token

    def parse(self) -> ParsedOverload:
        name = self.expect("NAME")
        member_name, receiver_path, notes = _semantic_name(name.text)

        params: list[ParsedParam] = []
        structural: list[int] = []
        has_call = False
        token = self.peek()
        if token is not None and token.kind == "LPAREN":
            has_call = True
            structural.append(self.next().index)
            self._parse_elements(params, structural, depth=0)
            structural.append(self.expect("RPAREN").index)
        elif name.text.rstrip().endswith("()**") or name.text.rstrip().endswith("()"):
            has_call = True

        return_type = None
        return_tokens: list[int] = []
        token = self.peek()
        if token is not None and token.kind == "COLON":
            return_tokens.append(self.next().index)
            type_token = self.expect("WORD")
            return_tokens.append(type_token.index)
            return_type = type_token.text

        leftover = self.peek()
        if leftover is not None:
            raise SyntaxParseError(
                f"trailing {leftover.kind} ({leftover.text!r}) after the "
                "signature",
                self.line,
            )

        return ParsedOverload(
            rawSyntax=self.line,
            memberName=member_name,
            receiverPath=receiver_path,
            hasCallPart=has_call,
            params=params,
            returnType=return_type,
            tokens=self.tokens,
            nameTokens=[name.index],
            structuralTokens=structural,
            returnTokens=return_tokens,
            notes=notes,
        )

    def _parse_elements(self, params: list[ParsedParam], structural: list[int],
                        depth: int) -> None:
        while True:
            token = self.peek()
            if token is None or token.kind == "RPAREN":
                return
            if token.kind == "RBRACE":
                if depth == 0:
                    raise SyntaxParseError("unbalanced '}'", self.line)
                return
            if token.kind == "SEMI":
                structural.append(self.next().index)
                continue
            if token.kind == "LBRACE":
                structural.append(self.next().index)
                self._parse_elements(params, structural, depth + 1)
                structural.append(self.expect("RBRACE").index)
                continue
            params.append(self._parse_param(depth))

    def _parse_param(self, depth: int) -> ParsedParam:
        owned: list[int] = []
        variadic = False
        token = self.next()
        owned.append(token.index)

        if token.kind == "ELLIPSIS":
            variadic = True
            token = self.next()
            owned.append(token.index)

        if token.kind == "STAR":
            return ParsedParam(
                name="*",
                typeName=None,
                optional=depth > 0,
                variadic=False,
                isLiteralStar=True,
                italicized=False,
                tokens=owned,
            )

        if token.kind == "ITALIC":
            raw = token.text[1:-1]
            italic = True
        elif token.kind == "WORD":
            raw = token.text
            italic = False
        else:
            raise SyntaxParseError(
                f"expected a parameter name, found {token.kind} "
                f"({token.text!r})",
                self.line,
            )
        if raw.startswith("..."):
            variadic = True
            raw = raw[3:]

        type_name = None
        token = self.peek()
        if token is not None and token.kind == "COLON":
            owned.append(self.next().index)
            type_token = self.expect("WORD")
            owned.append(type_token.index)
            type_name = type_token.text

        return ParsedParam(
            name=raw.strip(),
            typeName=type_name,
            optional=depth > 0,
            variadic=variadic,
            isLiteralStar=False,
            italicized=italic,
            tokens=owned,
        )


def parse_overload(line: str) -> ParsedOverload:
    return _Parser(line, tokenize(line)).parse()


def render(overload: ParsedOverload) -> str:
    """Re-emit the source line from the AST.

    Collects the token indices the AST claims — name, structural punctuation,
    every parameter's own tokens, and the return part — and requires them to be
    exactly the full token range in order. This is what makes the round-trip
    gate a real check on the parser rather than a string echo.
    """
    claimed: list[int] = list(overload.nameTokens)
    claimed += overload.structuralTokens
    for param in overload.params:
        claimed += param.tokens
    claimed += overload.returnTokens
    claimed.sort()

    expected = [t.index for t in overload.tokens if t.kind != "EOL"]
    if claimed != expected:
        missing = sorted(set(expected) - set(claimed))
        duplicated = sorted({i for i in claimed if claimed.count(i) > 1})
        raise SyntaxParseError(
            f"AST does not account for every token (missing={missing}, "
            f"duplicated={duplicated})",
            overload.rawSyntax,
        )
    return "".join(t.source for t in overload.tokens)


def split_overloads(syntax: str) -> list[str]:
    """Split a member's `Syntax` field into its individual overload lines.

    Overloads are `<br/>`-separated. The separator itself is not part of any
    overload, so a per-line round-trip plus this join reproduces the field.
    """
    return syntax.split("<br/>")


def parse_member(syntax: str) -> list[ParsedOverload]:
    return [parse_overload(line) for line in split_overloads(syntax)]
