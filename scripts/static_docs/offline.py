"""Finalize and audit a Wget mirror without inventing missing documentation."""

import os
import posixpath
import re
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

TAGS = re.compile(r"<(?:a|link|script|img|iframe|source|video|audio|input|embed|object)\b[^>]*>", re.I)
ATTRS = re.compile(r'\b(href|src|poster)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.I)
BADGE = re.compile(r'theme-doc-version-badge[^>]*>([^<]*)', re.I)
CSS_URL = re.compile(r'url\(\s*(?:"([^"]*)"|\'([^\']*)\'|([^)\s]+))\s*\)', re.I)


def inventory(root):
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def route_table(paths):
    routes = dict(paths)
    for name, path in paths.items():
        if name.endswith(".html"):
            routes.setdefault(name[:-5], path)
        if name.endswith("/index.html"):
            routes.setdefault(name[:-10], path)
            routes.setdefault(name[:-11], path)
    if "index.html" in paths:
        routes[""] = paths["index.html"]
    folded = {}
    for name, path in routes.items():
        key = name.casefold()
        if key in folded and folded[key] != path:
            raise ValueError(f"Ambiguous case-insensitive route: {name}")
        folded[key] = path
    return routes, folded


def local_route(name, url, base_path, origins):
    parsed = urlsplit(unescape(url))
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc and f"{parsed.scheme}://{parsed.netloc}" not in origins:
        return None
    if not parsed.path:
        return None
    if parsed.path == base_path.rstrip("/"):
        route = ""
    elif parsed.path.startswith(base_path):
        route = unquote(parsed.path[len(base_path):])
    elif not parsed.netloc and not parsed.path.startswith("/"):
        route = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(parsed.path)))
    else:
        return None
    return route, parsed


def finalize(root, temporary_origin, public_origin, base_path):
    paths = inventory(root)
    routes, folded = route_table(paths)
    unresolved = Counter()
    changed = 0
    for name, path in paths.items():
        if path.suffix not in (".html", ".css"):
            continue
        original = path.read_text(encoding="utf-8")

        def rewrite_tag(tag):
            def rewrite_attr(attr):
                value = next(v for v in attr.groups()[1:] if v is not None)
                resolved = local_route(name, value, base_path, (temporary_origin, public_origin))
                if resolved is None:
                    return attr.group(0)
                route, parsed = resolved
                target = routes.get(route) or folded.get(route.casefold())
                if target is None:
                    unresolved[parsed.path] += 1
                    public = public_origin + base_path + quote(route, safe="/~!$&()*+,;=:@")
                    if parsed.query:
                        public += "?" + parsed.query
                    if parsed.fragment:
                        public += "#" + parsed.fragment
                    return attr.group(1) + '="' + public.replace("&", "&amp;").replace('"', "&quot;") + '"'
                relative = quote(os.path.relpath(target, path.parent).replace(os.sep, "/"), safe="/~!$&()*+,;=:@")
                if parsed.query:
                    relative += "?" + parsed.query
                if parsed.fragment:
                    relative += "#" + parsed.fragment
                return attr.group(1) + '="' + relative.replace("&", "&amp;").replace('"', "&quot;") + '"'

            return ATTRS.sub(rewrite_attr, tag.group(0))

        updated = TAGS.sub(rewrite_tag, original) if path.suffix == ".html" else original
        updated = updated.replace(temporary_origin, public_origin)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return {
        "adjustedFiles": changed,
        "unresolvedUpstreamPaths": dict(sorted(unresolved.items())),
    }


def verify(root, temporary_origin=None, source=None):
    paths = inventory(root)
    folded_paths = {name.casefold() for name in paths}
    directories = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}
    directories.add(".")
    issues = []
    labels = {}
    html_count = 0
    for name, path in paths.items():
        if path.suffix not in (".html", ".css"):
            continue
        text = path.read_text(encoding="utf-8")
        if temporary_origin and temporary_origin in text:
            issues.append((name, "temporary origin remains"))
        references = []
        if path.suffix == ".html":
            html_count += 1
            badge = BADGE.search(text)
            if badge:
                labels[name] = unescape(badge.group(1))
            for tag in TAGS.finditer(text):
                for attr in ATTRS.finditer(tag.group(0)):
                    references.append(next(v for v in attr.groups()[1:] if v is not None))
        else:
            references.extend(next(v for v in match.groups() if v is not None)
                              for match in CSS_URL.finditer(text))
        for reference in references:
            url = urlsplit(unescape(reference))
            if not url.path or url.scheme or url.netloc:
                continue
            route = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(url.path)))
            if url.path.startswith("/") or (route not in paths and route not in directories):
                issues.append((name, url.geturl()))
    if source:
        folded_labels = {name.casefold(): label for name, label in labels.items()}
        for path in source.rglob("*.html"):
            if path.name.endswith(".html.html"):
                continue
            name = path.relative_to(source).as_posix()
            if name.casefold() not in folded_paths:
                issues.append((name, "published source page absent"))
            badge = BADGE.search(path.read_text(encoding="utf-8"))
            if badge and folded_labels.get(name.casefold()) != unescape(badge.group(1)):
                issues.append((name, "published version badge changed"))
    if issues:
        raise ValueError(f"{len(issues)} offline reference/coverage failures: {issues[:20]}")
    if not html_count:
        raise ValueError("Mirror contains no HTML pages")
    return {"htmlPages": html_count, "versionLabels": labels}
