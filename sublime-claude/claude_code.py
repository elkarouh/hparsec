"""
ClaudeCode - Sublime Text plugin
Integrates Claude Code CLI into Sublime Text via the Terminus package.
Also provides access to the Zed AI threads database for listing, viewing,
saving, and restoring past conversations.

Commands:
  claude_code_open            - Open an interactive Claude Code session in Terminus
  claude_code_send            - Send selected text (or whole file) to the active Claude session
  claude_code_toggle_watch    - Toggle auto-review on save
  claude_code_status          - Show current watcher status
  claude_code_list_threads    - List past conversations from Zed threads DB
  claude_code_view_thread     - View a past conversation in a read-only buffer
  claude_code_restore_thread  - Replay a past conversation into the active Claude session
  claude_code_save_thread     - Save current Terminus session transcript to the DB

Keybindings (Default (Linux).sublime-keymap):
  Ctrl+Alt+C  -> claude_code_open
  Ctrl+Alt+A  -> claude_code_send
  Ctrl+Alt+W  -> claude_code_toggle_watch
  Ctrl+Alt+S  -> claude_code_status
  Ctrl+Alt+H  -> claude_code_list_threads  (History)
"""

import os
import uuid
import json
import sqlite3
import datetime
import threading
import subprocess
import tempfile
import sublime
import sublime_plugin

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

SETTINGS_FILE = "ClaudeCode.sublime-settings"
DEBOUNCE_SECONDS = 1.0
WATCHED_EXTENSIONS = {".hpy", ".py", ".nim"}
DEFAULT_WATCH_PROMPT = (
    "Quick review: any bugs, refactors, type errors, or improvements? Be concise."
)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_watcher_enabled = False
_debounce_timer = None
_TERMINUS_TAG = "claude_code_session"

# Cached thread list from last DB query: list of (id, summary, updated_at)
_thread_cache = []


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _settings():
    return sublime.load_settings(SETTINGS_FILE)


def _claude_bin():
    return _settings().get("claude_bin", "claude")


def _zstd_bin():
    return _settings().get("zstd_bin", "/auto/home/ekhassan/.cargo/bin/zstd")


def _threads_db():
    default = "/auto/local_build/dhws149/disk1/DOWNLOADS/zed/threads/threads.db"
    return _settings().get("zed_threads_db", default)


# ---------------------------------------------------------------------------
# Zed DB helpers
# ---------------------------------------------------------------------------

def _db_connect():
    return sqlite3.connect(_threads_db())


def _decompress(data):
    """Decompress a zstd blob, return decoded JSON string."""
    zstd = _zstd_bin()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zst") as f:
        f.write(data)
        tmp = f.name
    try:
        result = subprocess.check_output([zstd, "-d", "-c", tmp])
        return result.decode("utf-8", errors="replace")
    finally:
        os.unlink(tmp)


def _compress(json_str):
    """Compress a JSON string with zstd, return bytes."""
    zstd = _zstd_bin()
    data = json_str.encode("utf-8")
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        tmp_in = f.name
    tmp_out = tmp_in + ".zst"
    try:
        subprocess.check_call([zstd, "-q", tmp_in, "-o", tmp_out])
        with open(tmp_out, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_in)
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)


def _list_threads():
    """Return list of (id, summary, updated_at) sorted newest first."""
    con = _db_connect()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT id, summary, updated_at FROM threads ORDER BY updated_at DESC"
        )
        return cur.fetchall()
    finally:
        con.close()


def _load_thread(thread_id):
    """Return parsed JSON dict for a thread, or None."""
    con = _db_connect()
    try:
        cur = con.cursor()
        cur.execute("SELECT data_type, data FROM threads WHERE id=?", (thread_id,))
        row = cur.fetchone()
        if not row:
            return None
        data_type, data = row
        if data_type == "zstd":
            raw = _decompress(data)
        else:
            raw = data.decode("utf-8") if isinstance(data, bytes) else data
        return json.loads(raw)
    finally:
        con.close()


def _thread_to_text(thread_obj):
    """Convert a thread JSON object to a readable plain-text string."""
    lines = []
    title = thread_obj.get("title", "Untitled")
    lines.append("# " + title)
    lines.append("")
    for msg in thread_obj.get("messages", []):
        if "User" in msg:
            lines.append("## User")
            for part in msg["User"].get("content", []):
                if "Text" in part:
                    lines.append(part["Text"])
            lines.append("")
        elif "Agent" in msg:
            lines.append("## Claude")
            for part in msg["Agent"].get("content", []):
                if "Text" in part:
                    lines.append(part["Text"])
            lines.append("")
    return "\n".join(lines)


def _save_thread_to_db(title, messages):
    """
    Insert a new thread into the Zed threads DB.
    messages: list of {"role": "user"|"assistant", "text": str}
    """
    thread_obj = {
        "title": title,
        "messages": []
    }
    for m in messages:
        msg_id = str(uuid.uuid4())
        if m["role"] == "user":
            thread_obj["messages"].append({
                "User": {
                    "id": msg_id,
                    "content": [{"Text": m["text"]}]
                }
            })
        else:
            thread_obj["messages"].append({
                "Agent": {
                    "content": [{"Text": m["text"]}]
                }
            })

    raw = json.dumps(thread_obj)
    compressed = _compress(raw)
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000000000+00:00")
    new_id = str(uuid.uuid4())

    con = _db_connect()
    try:
        con.execute(
            "INSERT INTO threads (id, summary, updated_at, data_type, data) VALUES (?, ?, ?, ?, ?)",
            (new_id, title, now, "zstd", sqlite3.Binary(compressed))
        )
        con.commit()
    finally:
        con.close()
    return new_id


# ---------------------------------------------------------------------------
# Terminus helpers
# ---------------------------------------------------------------------------

def _open_terminus(window, cwd=None):
    """Open (or focus) a Terminus panel running claude."""
    for view in window.views():
        if view.settings().get("terminus_view.tag") == _TERMINUS_TAG:
            window.focus_view(view)
            return

    panel = window.find_output_panel(_TERMINUS_TAG)
    if panel is not None:
        window.run_command("show_panel", {"panel": "output." + _TERMINUS_TAG})
        return

    if cwd is None:
        folders = window.folders()
        cwd = folders[0] if folders else os.path.expanduser("~")

    window.run_command("terminus_open", {
        "cmd": [_claude_bin()],
        "cwd": cwd,
        "title": "Claude Code",
        "panel_name": _TERMINUS_TAG,
        "tag": _TERMINUS_TAG,
        "focus": True,
    })


def _find_terminus_view(window):
    """Return the Terminus view for our Claude session, or None."""
    for view in window.views():
        if view.settings().get("terminus_view.tag") == _TERMINUS_TAG:
            return view
    panel = window.find_output_panel(_TERMINUS_TAG)
    if panel and panel.settings().get("terminus_view"):
        return panel
    return None


def _send_to_terminus(window, text):
    """Send text + newline to the active Terminus Claude session."""
    terminus_view = _find_terminus_view(window)
    if terminus_view is None:
        sublime.error_message(
            "ClaudeCode: No active Claude session.\n"
            "Run 'ClaudeCode: Open Session' first (Ctrl+Alt+C)."
        )
        return
    window.focus_view(terminus_view)
    terminus_view.run_command("terminus_keypress", {"key": text + "\n"})


def _build_message(prompt, context, filename):
    """Compose the message sent into the Claude terminal."""
    label = os.path.basename(filename) if filename else "snippet"
    return prompt + "\n\n```" + label + "\n" + context + "\n```"


# ---------------------------------------------------------------------------
# Commands - session management
# ---------------------------------------------------------------------------

class ClaudeCodeOpenCommand(sublime_plugin.WindowCommand):
    """Open an interactive Claude Code session in a Terminus panel."""

    def run(self):
        cwd = None
        active = self.window.active_view()
        if active and active.file_name():
            cwd = os.path.dirname(active.file_name())
        _open_terminus(self.window, cwd)


class ClaudeCodeSendCommand(sublime_plugin.TextCommand):
    """Send selected text (or whole file) to the active Claude session."""

    def run(self, edit, prompt=""):
        view = self.view
        window = view.window()
        sel = view.sel()

        if sel and not sel[0].empty():
            context = view.substr(sel[0])
        else:
            context = view.substr(sublime.Region(0, view.size()))

        filename = view.file_name()

        def do_send(p):
            _open_terminus(window, os.path.dirname(filename) if filename else None)
            msg = _build_message(p, context, filename)
            sublime.set_timeout(lambda: _send_to_terminus(window, msg), 400)

        if prompt:
            do_send(prompt)
        else:
            window.show_input_panel(
                "Ask Claude:",
                "Explain this code.",
                do_send,
                None,
                None,
            )

    def is_enabled(self):
        return True


class ClaudeCodeToggleWatchCommand(sublime_plugin.WindowCommand):
    """Toggle auto-review of files on save."""

    def run(self):
        global _watcher_enabled
        _watcher_enabled = not _watcher_enabled
        state = "ENABLED" if _watcher_enabled else "DISABLED"
        self.window.status_message("[ClaudeCode] Watcher " + state)

    def description(self):
        state = "Disable" if _watcher_enabled else "Enable"
        return "ClaudeCode: " + state + " Watcher"


class ClaudeCodeStatusCommand(sublime_plugin.WindowCommand):
    """Show current watcher state."""

    def run(self):
        state = "enabled" if _watcher_enabled else "disabled"
        ext = ", ".join(sorted(WATCHED_EXTENSIONS))
        sublime.message_dialog(
            "ClaudeCode status\n\nWatcher: " + state +
            "\nWatching: " + ext +
            "\nClaude bin: " + _claude_bin() +
            "\nThreads DB: " + _threads_db()
        )


# ---------------------------------------------------------------------------
# Commands - thread history
# ---------------------------------------------------------------------------

class ClaudeCodeListThreadsCommand(sublime_plugin.WindowCommand):
    """Show a quick panel listing past Zed AI conversations."""

    def run(self):
        global _thread_cache

        def load():
            try:
                threads = _list_threads()
            except Exception as e:
                sublime.set_timeout(
                    lambda: sublime.error_message("ClaudeCode: DB error\n" + str(e)), 0
                )
                return

            if not threads:
                sublime.set_timeout(
                    lambda: sublime.message_dialog("ClaudeCode: No conversations found."), 0
                )
                return

            global _thread_cache
            _thread_cache = threads

            items = []
            for tid, summary, updated_at in threads:
                # Trim timestamp to date+time without nanoseconds
                short_date = updated_at[:19].replace("T", " ") if updated_at else ""
                items.append([summary, short_date])

            def on_select(idx):
                if idx < 0:
                    return
                self.window.run_command("claude_code_thread_action",
                                        {"thread_idx": idx})

            sublime.set_timeout(
                lambda: self.window.show_quick_panel(items, on_select), 0
            )

        threading.Thread(target=load, daemon=True).start()


class ClaudeCodeThreadActionCommand(sublime_plugin.WindowCommand):
    """Ask what to do with a selected thread: View or Restore."""

    def run(self, thread_idx=0):
        if thread_idx >= len(_thread_cache):
            return
        tid, summary, _ = _thread_cache[thread_idx]
        actions = ["View conversation", "Restore into Claude session"]

        def on_action(idx):
            if idx == 0:
                self.window.run_command("claude_code_view_thread",
                                        {"thread_id": tid})
            elif idx == 1:
                self.window.run_command("claude_code_restore_thread",
                                        {"thread_id": tid})

        self.window.show_quick_panel(actions, on_action)


class ClaudeCodeViewThreadCommand(sublime_plugin.WindowCommand):
    """Open a past conversation in a read-only buffer."""

    def run(self, thread_id=""):
        if not thread_id:
            return

        def load():
            try:
                obj = _load_thread(thread_id)
            except Exception as e:
                sublime.set_timeout(
                    lambda: sublime.error_message("ClaudeCode: " + str(e)), 0
                )
                return

            if obj is None:
                sublime.set_timeout(
                    lambda: sublime.error_message("ClaudeCode: Thread not found."), 0
                )
                return

            text = _thread_to_text(obj)
            title = obj.get("title", "Conversation")

            def show():
                view = self.window.new_file()
                view.set_name(title)
                view.set_scratch(True)
                view.set_read_only(False)
                view.run_command("append", {"characters": text})
                view.set_read_only(True)
                try:
                    view.assign_syntax("Packages/Markdown/Markdown.sublime-syntax")
                except Exception:
                    pass

            sublime.set_timeout(show, 0)

        threading.Thread(target=load, daemon=True).start()


class ClaudeCodeRestoreThreadCommand(sublime_plugin.WindowCommand):
    """Replay a past conversation's user messages into the active Claude session."""

    def run(self, thread_id=""):
        if not thread_id:
            return

        def load():
            try:
                obj = _load_thread(thread_id)
            except Exception as e:
                sublime.set_timeout(
                    lambda: sublime.error_message("ClaudeCode: " + str(e)), 0
                )
                return

            if obj is None:
                sublime.set_timeout(
                    lambda: sublime.error_message("ClaudeCode: Thread not found."), 0
                )
                return

            # Collect user messages only — replay the conversation
            user_msgs = []
            for msg in obj.get("messages", []):
                if "User" in msg:
                    parts = msg["User"].get("content", [])
                    text = "\n".join(p["Text"] for p in parts if "Text" in p)
                    if text.strip():
                        user_msgs.append(text)

            if not user_msgs:
                sublime.set_timeout(
                    lambda: sublime.message_dialog("ClaudeCode: No user messages found."), 0
                )
                return

            title = obj.get("title", "restored")
            intro = "Restoring conversation: " + title + "\n(replaying " + str(len(user_msgs)) + " messages)"

            def send_all():
                _open_terminus(self.window)
                delay = 500
                sublime.set_timeout(
                    lambda: _send_to_terminus(self.window, intro), delay
                )
                delay += 300
                for text in user_msgs:
                    def make_sender(t):
                        return lambda: _send_to_terminus(self.window, t)
                    sublime.set_timeout(make_sender(text), delay)
                    delay += 200

            sublime.set_timeout(send_all, 0)

        threading.Thread(target=load, daemon=True).start()


class ClaudeCodeSaveThreadCommand(sublime_plugin.WindowCommand):
    """
    Save the current Terminus session transcript to the Zed threads DB.
    Reads visible text from the Terminus view as a single assistant message.
    """

    def run(self):
        terminus_view = _find_terminus_view(self.window)
        if terminus_view is None:
            sublime.error_message(
                "ClaudeCode: No active Claude session to save."
            )
            return

        transcript = terminus_view.substr(sublime.Region(0, terminus_view.size()))
        if not transcript.strip():
            sublime.error_message("ClaudeCode: Session is empty.")
            return

        def on_title(title):
            if not title:
                title = "Claude Code Session"

            def save():
                try:
                    messages = [{"role": "assistant", "text": transcript}]
                    new_id = _save_thread_to_db(title, messages)
                    sublime.set_timeout(
                        lambda: sublime.message_dialog(
                            "ClaudeCode: Saved as\n\"" + title + "\"\n(id: " + new_id + ")"
                        ), 0
                    )
                except Exception as e:
                    sublime.set_timeout(
                        lambda: sublime.error_message("ClaudeCode: Save failed\n" + str(e)), 0
                    )

            threading.Thread(target=save, daemon=True).start()

        self.window.show_input_panel(
            "Conversation title:",
            "Claude Code Session",
            on_title,
            None,
            None,
        )


# ---------------------------------------------------------------------------
# Event listener (file-save watcher)
# ---------------------------------------------------------------------------

class ClaudeCodeFileWatcher(sublime_plugin.EventListener):
    """Auto-send a review prompt when a watched file is saved."""

    def on_post_save_async(self, view):
        global _debounce_timer

        if not _watcher_enabled:
            return

        filename = view.file_name()
        if not filename:
            return

        if os.path.splitext(filename)[1].lower() not in WATCHED_EXTENSIONS:
            return

        if _debounce_timer is not None:
            _debounce_timer.cancel()

        def fire():
            window = view.window()
            if not window:
                return
            context = view.substr(sublime.Region(0, view.size()))
            msg = _build_message(DEFAULT_WATCH_PROMPT, context, filename)
            cwd = os.path.dirname(filename)

            def open_and_send():
                _open_terminus(window, cwd)
                sublime.set_timeout(lambda: _send_to_terminus(window, msg), 400)

            sublime.set_timeout(open_and_send, 0)

        _debounce_timer = threading.Timer(DEBOUNCE_SECONDS, fire)
        _debounce_timer.start()
