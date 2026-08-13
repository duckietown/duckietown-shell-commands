import sys

import math
import shutil
import textwrap

__all__ = ["ProgressBar"]


class ProgressBar:
    def __init__(self, scale=1.0, buf=sys.stdout, header="Progress", columns=None):
        self._finished = False
        self._buffer = buf
        self._header = header
        self._detail = ""
        self._last_header = None
        self._last_detail = None
        self._last_line_count = 0
        self._last_value = -1
        self._columns = columns
        self._scale = max(0.0, min(1.0, scale))
        self._max = int(math.ceil(100 * self._scale))

    def set_header(self, header):
        self._header = header

    def set_detail(self, detail):
        self._detail = detail

    def _get_columns(self):
        if self._columns is not None:
            return max(20, self._columns)
        return max(20, shutil.get_terminal_size(fallback=(120, 20)).columns)

    def _clear_previous_render(self):
        if self._last_line_count <= 0:
            self._buffer.write("\r\x1b[2K")
            return
        self._buffer.write("\r")
        for idx in range(self._last_line_count):
            self._buffer.write("\x1b[2K")
            if idx < self._last_line_count - 1:
                self._buffer.write("\x1b[1A\r")

    def _progress_bar_line(self, percentage_int):
        prefix = f"{self._header}: [" if self._scale > 0.5 else "["
        suffix = "] {:d}%".format(percentage_int)
        columns = self._get_columns()
        bar_width = max(1, min(self._max, columns - len(prefix) - len(suffix)))
        progress_fraction = percentage_int / 100.0

        if progress_fraction >= 1.0:
            bar = "=" * bar_width
        else:
            head_position = min(bar_width - 1, int(math.floor(progress_fraction * bar_width)))
            bar_chars = [" "] * bar_width
            for idx in range(head_position):
                bar_chars[idx] = "="
            bar_chars[head_position] = ">"
            bar = "".join(bar_chars)
        return f"{prefix}{bar}{suffix}"

    def _render_lines(self, percentage_int):
        core_line = self._progress_bar_line(percentage_int)
        if not self._detail:
            return [core_line]
        detail_text = f"({self._detail})"
        columns = self._get_columns()
        if len(core_line) + 1 + len(detail_text) <= columns:
            return [f"{core_line} {detail_text}"]

        detail_indent = "  "
        detail_width = max(10, columns - len(detail_indent))
        wrapped_detail = textwrap.wrap(
            detail_text,
            width=detail_width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        lines = [core_line]
        for line in wrapped_detail:
            lines.append(f"{detail_indent}{line}")
        return lines

    def _write_lines(self, lines):
        for idx, line in enumerate(lines):
            self._buffer.write("\r\x1b[2K")
            self._buffer.write(line)
            if idx < len(lines) - 1:
                self._buffer.write("\n")

    def update(self, percentage):
        percentage_int = int(max(0, min(100, percentage)))
        if (
            percentage_int == self._last_value
            and self._header == self._last_header
            and self._detail == self._last_detail
        ):
            return
        if self._finished:
            return
        lines = self._render_lines(percentage_int)
        self._clear_previous_render()
        if percentage_int >= 100:
            self._buffer.write("\r\x1b[2KDone!\n")
            self._finished = True
            self._last_line_count = 0
        else:
            self._write_lines(lines)
            self._last_line_count = len(lines)
        self._buffer.flush()
        self._last_header = self._header
        self._last_detail = self._detail
        self._last_value = percentage_int

    def done(self):
        self.update(100)
