import json
import os
import signal
import sys
from bisect import bisect_right
from collections import deque
from textwrap import fill
from threading import Event, Lock, Thread, get_ident

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.formatted_text.utils import fragment_list_to_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.processors import TabsProcessor
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.text import Text

LIVE_PROFILER_PREFIX = "===DTS_MATRIX_PROFILER==="
MAX_LOG_LINES = 10_000


class ProfilerTextArea(TextArea):
    def __init__(self, **kwargs):
        kwargs.pop("scrollbar", None)
        super().__init__(
            input_processors=[TabsProcessor(char1=" ", char2=" ", style="")],
            scrollbar=False,
            **kwargs,
        )
        self._default_mouse_handler = self.control.mouse_handler
        self.control.mouse_handler = self._mouse_handler
        self._scrollbar_content = None
        self._scrollbar_width = None
        self._scrollbar_offsets = [0]
        self._drag_offset = None
        self.scrollbar = Window(
            FormattedTextControl(self._get_scrollbar_fragments), width=1,
        )
        self.container = VSplit([
            self.window, Window(width=1, char=" "), self.scrollbar,
        ])

    def __pt_container__(self):
        return self.container

    def _scrollbar_metrics(self):
        info = self.window.render_info
        if self._scrollbar_content is not info.ui_content or self._scrollbar_width != info.window_width:
            self._scrollbar_content = info.ui_content
            self._scrollbar_width = info.window_width
            self._scrollbar_offsets = [0]
            for line in range(info.ui_content.line_count):
                height = info.get_height_for_line(line)
                self._scrollbar_offsets.append(self._scrollbar_offsets[-1] + height)
        total = self._scrollbar_offsets[-1]
        maximum = max(0, total - info.window_height)
        track = max(0, info.window_height - 2)
        thumb = min(track, max(1, track * info.window_height // max(1, total)))
        position = self._scrollbar_offsets[self.window.vertical_scroll] + self.window.vertical_scroll_2
        top = (track - thumb) * min(position, maximum) // max(1, maximum)
        return track, thumb, top, maximum

    def _get_scrollbar_fragments(self):
        info = self.window.render_info
        if info is None:
            return []
        track, thumb, top, _ = self._scrollbar_metrics()
        result = [("class:scrollbar.arrow", "^", self._on_scrollbar_mouse)]
        if info.window_height <= 1:
            return result
        result.append(("", "\n"))
        for row in range(track):
            style = "class:scrollbar.button" if top <= row < top + thumb else "class:scrollbar.background"
            result.append((style, " ", self._on_scrollbar_mouse))
            result.append(("", "\n"))
        result.append(("class:scrollbar.arrow", "v", self._on_scrollbar_mouse))
        return result

    def _on_scrollbar_mouse(self, event):
        if event.event_type in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
            return self._mouse_handler(event)
        if event.button != MouseButton.LEFT or self.window.render_info is None:
            return NotImplemented
        track, thumb, top, _ = self._scrollbar_metrics()
        row = event.position.y - 1
        if event.event_type == MouseEventType.MOUSE_DOWN:
            if row < 0:
                self._scroll_rows(-3)
            elif row >= track:
                self._scroll_rows(3)
            elif top <= row < top + thumb:
                self._drag_offset = row - top
            else:
                self._drag_offset = max(0, (thumb - 1) // 2)
                self._drag_scrollbar(row - self._drag_offset)
            return None
        if event.event_type in (MouseEventType.MOUSE_MOVE, MouseEventType.MOUSE_UP):
            if self._drag_offset is not None:
                self._drag_scrollbar(row - self._drag_offset)
            if event.event_type == MouseEventType.MOUSE_UP:
                self._drag_offset = None
            return None
        return NotImplemented

    def _drag_scrollbar(self, position):
        track, thumb, _, maximum = self._scrollbar_metrics()
        travel = track - thumb
        position = min(max(0, position), travel)
        if position == travel:
            self.buffer.cursor_position = len(self.text)
            return
        target = position * maximum // max(1, travel)
        line = min(bisect_right(self._scrollbar_offsets, target) - 1, len(self._scrollbar_offsets) - 2)
        offset = target - self._scrollbar_offsets[line]
        self._set_scroll_position(line, offset)

    def _mouse_handler(self, event):
        if event.event_type == MouseEventType.SCROLL_UP:
            self._scroll_rows(-3)
            return None
        if event.event_type == MouseEventType.SCROLL_DOWN:
            self._scroll_rows(3)
            return None
        return self._default_mouse_handler(event)

    def _scroll_rows(self, distance):
        info = self.window.render_info
        if info is None or info.window_width <= 0:
            return
        line = self.window.vertical_scroll
        offset = self.window.vertical_scroll_2
        if distance > 0:
            remaining = -offset
            for index in range(line, info.ui_content.line_count):
                remaining += info.get_height_for_line(index)
                if remaining > info.window_height + distance:
                    break
            else:
                self.buffer.cursor_position = len(self.text)
                return
        offset += distance
        while offset < 0 and line > 0:
            line -= 1
            offset += info.get_height_for_line(line)
        while line < info.ui_content.line_count - 1:
            height = info.get_height_for_line(line)
            if offset < height:
                break
            offset -= height
            line += 1
        offset = max(0, min(offset, info.get_height_for_line(line) - 1))
        self._set_scroll_position(line, offset)

    def _set_scroll_position(self, line, offset):
        info = self.window.render_info
        text = fragment_list_to_text(info.ui_content.get_line(line))
        target_width = offset * info.window_width
        lower = 0
        upper = len(text)
        while lower < upper:
            middle = (lower + upper) // 2
            if get_cwidth(text[:middle]) < target_width:
                lower = middle + 1
            else:
                upper = middle
        get_processed_line = self.control._last_get_processed_line
        if get_processed_line is None:
            return
        processed_line = get_processed_line(line)
        column = processed_line.display_to_source(lower)
        self.window.vertical_scroll = line
        self.window.vertical_scroll_2 = offset
        document = self.buffer.document
        self.buffer.cursor_position = document.translate_row_col_to_index(line, column)


class AnsiLogLexer(Lexer):
    def __init__(self):
        self.lines = deque(maxlen=MAX_LOG_LINES)

    def lex_document(self, document):
        return self._get_line

    def _get_line(self, line_number):
        if 0 <= line_number < len(self.lines):
            return self.lines[line_number]
        return []


class ProfilerPanel:
    def __init__(self, pane, *, title, weight, on_restore):
        self.pane = pane
        self.title = title
        self.on_restore = on_restore
        self.minimised = False
        self.maximised = False
        self.collapsed_by_maximise = False
        self.scroll_position = None
        self.frame = Frame(pane, title=self._get_title, height=Dimension(min=3, weight=weight))
        self.frame.container.style = self._get_frame_style
        self.header = Window(
            FormattedTextControl(self._get_header_fragments, focusable=True),
            height=1, style=self._get_header_style,
        )
        self.container = DynamicContainer(self._get_container)

    def __pt_container__(self):
        return self.container

    def _is_focused(self):
        application = get_app()
        return application.layout.has_focus(self)

    def _get_title(self):
        return self.title

    def _get_header_text(self):
        return f"[+] {self.title}"

    def _get_header_fragments(self):
        application = get_app()
        width = application.output.get_size().columns
        text = self._get_header_text()
        return [("", text.ljust(width), self._on_header_mouse)]

    def _on_header_mouse(self, event):
        if event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
            self.on_restore(self)
            return None
        return NotImplemented

    def _get_frame_style(self):
        return "class:frame,panel-focused" if self._is_focused() else "class:frame"

    def _get_header_style(self):
        return "class:panel-header.focused" if self._is_focused() else "class:panel-header"

    def _is_collapsed(self):
        return not self.maximised and (self.minimised or self.collapsed_by_maximise)

    def _get_container(self):
        return self.header if self._is_collapsed() else self.frame

    def focus(self, layout):
        target = self.header if self._is_collapsed() else self.pane
        layout.focus(target)


class ProfilerView:
    def __init__(self, stream, *, input=None, output=None):
        self.panes = {
            source: ProfilerTextArea(
                text="Waiting for samples...", read_only=True,
                scrollbar=True, wrap_lines=True, focus_on_click=True,
            )
            for source in ("Engine", "Renderer")
        }
        self.log_lexer = AnsiLogLexer()
        self.logs = ProfilerTextArea(
            read_only=True, scrollbar=True, wrap_lines=True,
            focus_on_click=True, lexer=self.log_lexer,
        )
        self.panels = [
            ProfilerPanel(pane, title=f"{source} Profiling Information",
                          weight=1, on_restore=self._expand_panel)
            for source, pane in self.panes.items()
        ]
        self.panels.append(ProfilerPanel(self.logs, title="Logs", weight=2,
                        on_restore=self._expand_panel))
        self.body = HSplit(self.panels)
        self.maximised_panel = None
        footer = Window(
            FormattedTextControl(self._get_shortcut_text),
            wrap_lines=True, dont_extend_height=True, style="reverse",
        )
        bindings = KeyBindings()
        bindings.add("tab")(self._focus_next)
        bindings.add("s-tab")(self._focus_previous)
        bindings.add("u")(self._move_pane_up)
        bindings.add("U")(self._move_pane_up)
        bindings.add("d")(self._move_pane_down)
        bindings.add("D")(self._move_pane_down)
        bindings.add("m")(self._toggle_minimised)
        bindings.add("M")(self._toggle_minimised)
        bindings.add("x")(self._toggle_maximised)
        bindings.add("X")(self._toggle_maximised)
        bindings.add("c-c", eager=True)(self._interrupt)
        if output is None:
            output = create_output(stdout=stream)
        self.application = Application(
            layout=Layout(HSplit([self.body, footer]), focused_element=self.logs),
            key_bindings=bindings, full_screen=True, mouse_support=True,
            style=Style.from_dict({
                "panel-focused frame.border": "#00d7d7 bold",
                "panel-focused frame.label": "bg:#00d7d7 #000000 bold",
                "panel-header.focused": "bg:#00d7d7 #000000 bold",
            }),
            enable_page_navigation_bindings=True, min_redraw_interval=0.1,
            input=input, output=output, before_render=self._render_pending,
        )
        self.pending_tables = {}
        self.pending_logs = deque(maxlen=MAX_LOG_LINES)
        self.log_lines = deque(maxlen=MAX_LOG_LINES)
        self.lock = Lock()
        self.ready = Event()
        self.error = None
        self.thread = Thread(target=self._run, name="matrix-profiler", daemon=True)

    def _get_shortcut_text(self):
        width = self.application.output.get_size().columns
        return fill(
            "Tab: next panel  U/D: move up/down  M: minimize/restore"
            "  X: maximize/restore  Ctrl+C: stop",
            width=max(1, width), break_long_words=False, break_on_hyphens=False,
        )

    def _focus_next(self, event):
        event.app.layout.focus_next()

    def _focus_previous(self, event):
        event.app.layout.focus_previous()

    def _focused_panel(self, event):
        for panel in self.panels:
            if event.app.layout.has_focus(panel):
                return panel
        return None

    def _expand_panel(self, panel):
        if self.maximised_panel is not None:
            self._restore_panels(self.maximised_panel)
        panel.minimised = False
        panel.focus(self.application.layout)
        self.application.invalidate()

    def _toggle_minimised(self, event):
        panel = self._focused_panel(event)
        if panel is None:
            return
        if self.maximised_panel is not None:
            maximised = self.maximised_panel
            self._restore_panels(maximised)
            panel.minimised = panel is maximised
        else:
            panel.minimised = not panel.minimised
        panel.focus(event.app.layout)
        event.app.invalidate()

    def _toggle_maximised(self, event):
        panel = self._focused_panel(event)
        if panel is None:
            return
        if panel.maximised:
            self._restore_panels(panel)
        else:
            if self.maximised_panel is not None:
                self._restore_panels(self.maximised_panel)
            panel.scroll_position = (
                panel.pane.buffer.cursor_position,
                panel.pane.window.vertical_scroll,
                panel.pane.window.horizontal_scroll,
            )
            panel.maximised = True
            self.maximised_panel = panel
            for other in self.panels:
                other.collapsed_by_maximise = other is not panel
        panel.focus(event.app.layout)
        event.app.invalidate()

    def _restore_panels(self, panel):
        self.maximised_panel = None
        panel.maximised = False
        for other in self.panels:
            other.collapsed_by_maximise = False
        cursor, vertical_scroll, horizontal_scroll = panel.scroll_position
        if panel.pane.buffer.cursor_position == cursor:
            panel.pane.window.vertical_scroll = vertical_scroll
            panel.pane.window.horizontal_scroll = horizontal_scroll
        panel.scroll_position = None

    def _move_pane_up(self, event):
        self._move_pane(event, -1)

    def _move_pane_down(self, event):
        self._move_pane(event, 1)

    def _move_pane(self, event, direction):
        frames = self.body.children
        for index, frame in enumerate(frames):
            if not event.app.layout.has_focus(frame):
                continue
            destination = index + direction
            if 0 <= destination < len(frames):
                frames[index], frames[destination] = frames[destination], frame
                event.app.invalidate()
            return

    def _interrupt(self, event):
        process_id = os.getpid()
        os.kill(process_id, signal.SIGINT)

    def _run(self):
        try:
            self.application.run(pre_run=self.ready.set, handle_sigint=False,
                                 set_exception_handler=False)
        except (EOFError, OSError, RuntimeError) as error:
            self.error = error
        finally:
            self.ready.set()

    def start(self):
        self.thread.start()
        self.ready.wait()
        if self.error is not None:
            raise RuntimeError("Could not start the live profiler") from self.error

    def stop(self):
        loop = self.application.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._exit)
        self.thread.join()

    def _exit(self):
        if self.application.is_running:
            self.application.exit()

    def update_table(self, source, table):
        with self.lock:
            self.pending_tables[source] = table
        self.application.invalidate()

    def write_log(self, line):
        with self.lock:
            self.pending_logs.append(line)
        self.application.invalidate()

    def _replace_text(self, pane, text, *, follow=False, removed_lines=0):
        previous = pane.buffer.document
        document = Document(text)
        if follow:
            cursor = len(text)
        else:
            row = max(0, previous.cursor_position_row - removed_lines)
            cursor = document.translate_row_col_to_index(
                row, previous.cursor_position_col,
            )
        pane.buffer.set_document(Document(text, cursor_position=cursor),
                                 bypass_readonly=True)

    def _render_pending(self, application):
        with self.lock:
            tables = self.pending_tables.copy()
            lines = list(self.pending_logs)
            self.pending_tables.clear()
            self.pending_logs.clear()
        for source, table in tables.items():
            self._replace_text(self.panes[source], table)
        if lines:
            follow = self.logs.buffer.document.is_cursor_at_the_end
            removed = max(0, len(self.log_lines) + len(lines) - MAX_LOG_LINES)
            self.log_lines.extend(lines)
            for line in lines:
                ansi_line = ANSI(line.rsplit("\r", 1)[-1])
                fragments = to_formatted_text(ansi_line)
                self.log_lexer.lines.append(fragments)
            text = "\n".join(
                fragment_list_to_text(fragments)
                for fragments in self.log_lexer.lines
            )
            self._replace_text(self.logs, text, follow=follow, removed_lines=removed)


class LiveProfilerOutput:
    def __init__(self, *, enabled=True, stream=None):
        self.enabled = enabled
        self.stream = stream if stream is not None else sys.stdout
        self.console = Console(file=self.stream, highlight=False, soft_wrap=True)
        self.view = None
        self.tables = {}
        self.buffers = {}
        self.log_lines = deque(maxlen=MAX_LOG_LINES)
        self.lock = Lock()
        self.previous_stdout = None
        self.previous_stderr = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def start(self):
        if self.enabled:
            if self.isatty() and sys.stdin.isatty():
                self.view = ProfilerView(self.stream)
                self.view.start()
                self.previous_stderr = sys.stderr
                sys.stderr = self
            self.previous_stdout = sys.stdout
            sys.stdout = self

    def stop(self):
        if self.previous_stdout is None:
            return
        try:
            if self.view is not None:
                self.view.stop()
            with self.lock:
                for buffered in self.buffers.values():
                    line = buffered.rstrip("\r")
                    if not self.update_snapshot(line):
                        self._write_log(line)
                self.buffers.clear()
                if self.view is not None:
                    for line in self.log_lines:
                        self.console.print(Text.from_ansi(line))
                    for source, table in sorted(self.tables.items()):
                        self.console.print(Text(f"{source} Profiling Information:\n{table}"))
        finally:
            sys.stdout = self.previous_stdout
            self.previous_stdout = None
            if self.previous_stderr is not None:
                sys.stderr = self.previous_stderr
                self.previous_stderr = None

    def write(self, text):
        with self.lock:
            writer = get_ident()
            buffered = self.buffers.get(writer, "") + text
            while "\n" in buffered:
                line, buffered = buffered.split("\n", 1)
                line = line.rstrip("\r")
                if not self.update_snapshot(line):
                    self._write_log(line)
            if buffered:
                self.buffers[writer] = buffered
            else:
                self.buffers.pop(writer, None)
        return len(text)

    def _write_log(self, line):
        if self.view is None:
            self.console.print(Text.from_ansi(line))
        else:
            self.log_lines.append(line)
            self.view.write_log(line)

    def update_snapshot(self, line):
        plain_line = Text.from_ansi(line).plain
        _, separator, payload = plain_line.partition(LIVE_PROFILER_PREFIX)
        if not separator:
            return False
        try:
            snapshot = json.loads(payload)
        except ValueError:
            return False
        if not isinstance(snapshot, dict):
            return False
        source = snapshot.get("source")
        table = snapshot.get("table")
        if source not in ("Engine", "Renderer") or not isinstance(table, str):
            return False
        self.tables[source] = table
        if self.view is None:
            self.console.print(Text(f"{source} Profiling Information:\n{table}"))
        else:
            self.view.update_table(source, table)
        return True

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return self.stream.isatty()

    def fileno(self):
        return self.stream.fileno()

    @property
    def encoding(self):
        return self.stream.encoding
