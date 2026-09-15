#!/usr/bin/env python3
"""Entry point for the shipped .app.

serve.py is a developer's server: it binds a fixed port, resolves every data file
relative to the working directory, and has no way to stop it but ctrl-C in the terminal
that started it. None of those hold inside a double-clicked .app, so this wraps it.

  - chdir to the bundled resources, because traverse.py opens "config/..." and
    "data/..." relative and rewriting ~30 call sites to be bundle-aware would be a
    worse change than setting the directory once, here
  - take any free port, because 8790 may be in use and a silent failure to bind is
    the least debuggable thing this app could do to someone
  - show a window, because a server with no window cannot be quit by someone who does
    not know what Activity Monitor is

Explore-only is set here rather than left to the person launching it: the bundle has no
review process behind it, so it must not be able to write a decision.
"""
import os, sys, socket, threading, webbrowser


def resources():
    """Where data/, config/ and web/ live -- inside the bundle, or the repo in dev."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port(preferred=8790):
    for port in (preferred, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    return 0


def main():
    os.chdir(resources())
    os.environ["FOODON_EXPLORE_ONLY"] = "1"
    sys.path.insert(0, os.path.join(resources(), "build"))

    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk()
    root.title("FoodOn Avoidance Graph")
    root.resizable(False, False)
    frame = tk.Frame(root, padx=28, pady=22)
    frame.pack()

    title = tk.Label(frame, text="FoodOn Avoidance Graph",
                     font=tkfont.Font(size=15, weight="bold"))
    title.pack(anchor="w")
    status = tk.Label(frame, text="Loading the ontology index…",
                      font=tkfont.Font(size=12), fg="#555")
    status.pack(anchor="w", pady=(6, 14))

    buttons = tk.Frame(frame)
    buttons.pack(anchor="w")
    state = {"url": None}

    def open_browser():
        if state["url"]:
            webbrowser.open(state["url"])

    open_btn = tk.Button(buttons, text="Open in browser", command=open_browser,
                         state="disabled")
    open_btn.pack(side="left")
    tk.Button(buttons, text="Quit", command=root.destroy).pack(side="left", padx=(8, 0))

    def serve():
        """Load the graph and start the server off the UI thread.

        The index is 16 MB of JSON; on a cold filesystem this is seconds, and a window
        that does not paint until it finishes reads as a hang.
        """
        import http.server, socketserver, traceback
        try:
            import serve as app                       # loads the graph on import
        except Exception:
            # bind the message now: `except ... as exc` unbinds exc at block exit, so a
            # lambda closing over it raises NameError later and hides the real fault
            detail = traceback.format_exc()
            sys.stderr.write(detail)
            first = detail.strip().splitlines()[-1]
            root.after(0, lambda m=first: status.config(
                text=f"Failed to load:\n{m}", fg="#b00", justify="left"))
            return
        port = free_port()
        socketserver.TCPServer.allow_reuse_address = True
        httpd = socketserver.TCPServer(("127.0.0.1", port), app.Handler)
        url = f"http://localhost:{port}/"
        state["url"] = url

        def ready():
            status.config(
                text=f"Running at {url}\n"
                     f"{len(app.GRAPH.N):,} classes, FoodOn {app.GRAPH.meta['version']}"
                     "\nExplore-only build — nothing is written to disk.",
                fg="#333", justify="left")
            open_btn.config(state="normal")
            webbrowser.open(url)

        # stdout as well as the window: the build script tails this to prove the
        # bundle serves its own data, and a window cannot be read by a test
        print(f"serving {url}", flush=True)
        root.after(0, ready)
        httpd.serve_forever()

    threading.Thread(target=serve, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
