"""Formata a descrição de um evento (texto simples vindo da API, muitas vezes
colado de redes sociais: **negrito**, emojis, hashtags, tudo numa linha).

Seguro por construção: o texto é escapado primeiro; só este módulo gera HTML.
"""

import re

from django.template import Library
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = Library()

# Emojis/pictogramas (intervalos principais) + variation selector / ZWJ.
_EMOJI = (
    "[\U0001F300-\U0001FAFF☀-➿⭐⭕⌚-⏿←-⇿"
    "⌀-⏿■-◿✅✨❌❤]"
)
_EMOJI_RUN = rf"(?:{_EMOJI}[️‍]*)+"
_BULLET_LINE = re.compile(rf"^\s*({_EMOJI_RUN})\s*(.*)$")
_DASH_LINE = re.compile(r"^\s*[-*•–]\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_HASHTAG = re.compile(r"(?<!\w)#\w+")


def _inline(text: str) -> str:
    text = escape(text)
    text = _BOLD.sub(lambda m: f"<strong class='font-semibold text-ink'>{m.group(1) or m.group(2)}</strong>", text)
    return text


def _is_hashtag_line(text: str) -> bool:
    rest = _HASHTAG.sub("", re.sub(_EMOJI_RUN, "", text)).strip()
    return bool(_HASHTAG.search(text)) and not rest


def _split_inline_emojis(text: str) -> str:
    """Texto numa só linha: parte antes de cada emoji que abre um item
    (emoji precedido de espaço e não colado a outro emoji)."""
    return re.sub(rf"(?<=[^\s️‍])(?<!{_EMOJI})[ \t]+(?={_EMOJI_RUN})", "\n", text)


_LEAD_BOLD = re.compile(r"^(\*\*[^*]+?(?<!:)\*\*)\s+(\S.*)$")


@register.filter
def rich_text(value):
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    single_line = "\n" not in text
    if single_line:
        text = _split_inline_emojis(text)
    lines = [ln.strip() for ln in text.split("\n")]

    # Em texto de uma só linha, o que vem depois do último item (ex.: "**Entrada
    # gratuita** Vem correr!") é um parágrafo à parte, não parte do item.
    tail = None
    if single_line:
        last = max((i for i, ln in enumerate(lines) if i and _BULLET_LINE.match(ln) and not _is_hashtag_line(ln)), default=None)
        if last is not None:
            m = _BULLET_LINE.match(lines[last])
            lead = _LEAD_BOLD.match(m.group(2))
            if lead:
                lines[last] = f"{m.group(1)} {lead.group(1)}"
                tail = lead.group(2)

    html, items = [], []

    def flush_items():
        if items:
            html.append("<ul class='space-y-2'>" + "".join(items) + "</ul>")
            items.clear()

    def paragraph(line):
        if _is_hashtag_line(line):
            tags = " ".join(escape(t) for t in _HASHTAG.findall(line))
            html.append(f"<p class='pt-2 text-xs uppercase tracking-wide opacity-60'>{tags}</p>")
        else:
            html.append(f"<p>{_inline(line)}</p>")

    for i, line in enumerate(lines):
        if not line:
            flush_items()
            continue
        if _is_hashtag_line(line):
            flush_items()
            paragraph(line)
            continue
        m = _BULLET_LINE.match(line)
        if m and m.group(2) and i > 0:        # a primeira linha é sempre o texto de abertura
            items.append(
                f"<li class='flex gap-3'><span class='shrink-0 w-6 text-center'>{escape(m.group(1))}</span>"
                f"<span>{_inline(m.group(2))}</span></li>"
            )
            continue
        d = _DASH_LINE.match(line)
        if d:
            items.append(f"<li class='flex gap-3'><span class='shrink-0 w-6 text-center'>•</span>"
                         f"<span>{_inline(d.group(1))}</span></li>")
            continue
        flush_items()
        paragraph(line)
    flush_items()
    if tail:
        # volta a juntar à posição certa: o tail vem logo a seguir à lista, antes das hashtags
        tail_html = f"<p>{_inline(tail)}</p>"
        idx = next((k for k, h in enumerate(html) if "uppercase tracking-wide" in h), len(html))
        html.insert(idx, tail_html)
    return mark_safe("".join(html))
