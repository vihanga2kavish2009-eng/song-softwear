import tkinter.messagebox
from functools import partial

import webview

from server import MusicAppHandler, MusicAppServer


def main():
    app_server = MusicAppServer(("127.0.0.1", 0), partial(MusicAppHandler))
    server_thread = None
    try:
        import threading

        server_thread = threading.Thread(target=app_server.serve_forever, daemon=True)
        server_thread.start()
        webview.create_window(
            "Up late — Music",
            f"http://127.0.0.1:{app_server.server_port}",
            width=1280,
            height=820,
            min_size=(760, 560),
            background_color="#21080f",
        )
        webview.start()
    except Exception as error:
        tkinter.messagebox.showerror(
            "Up late — Music could not start",
            f"The desktop app could not open its window.\n\n{error}\n\n"
            "Install or repair Microsoft Edge WebView2 Runtime, then try again.",
        )
        raise
    finally:
        if server_thread and server_thread.is_alive():
            app_server.shutdown()
        app_server.server_close()


if __name__ == "__main__":
    main()
