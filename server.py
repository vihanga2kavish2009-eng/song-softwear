import json
import sys
import time
from base64 import b64encode
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
soundcloud_credentials = None
soundcloud_token = None
soundcloud_token_expires_at = 0
soundcloud_refresh_token = None
soundcloud_token_lock = Lock()


class MusicAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/soundcloud/status":
            return self.send_json(200, {"configured": bool(soundcloud_credentials)})
        if path == "/api/soundcloud/search":
            return self.search_soundcloud()
        if path != "/api/deezer/search":
            return super().do_GET()

        query = parse_qs(urlsplit(self.path).query)
        term = query.get("q", [""])[0].strip()
        if not term:
            return self.send_json(400, {"error": {"message": "A song or artist search term is required."}})

        limit = query.get("limit", ["30"])[0]
        try:
            limit = str(max(1, min(int(limit), 30)))
        except ValueError:
            limit = "30"

        url = "https://api.deezer.com/search?" + urlencode({"q": term, "limit": limit})
        request = Request(url, headers={"User-Agent": "UpLateMusic/1.0"})
        try:
            with urlopen(request, timeout=12) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as error:
            self.send_json(error.code, {"error": {"message": "The music search provider rejected the request."}})
        except (URLError, TimeoutError) as error:
            self.log_error("Music search provider request failed: %s", error)
            self.send_json(502, {"error": {"message": "The music search provider is unavailable. Check your internet connection."}})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/soundcloud/configure", "/api/soundcloud/clear"):
            return self.send_json(404, {"error": {"message": "API endpoint not found."}})
        if not self.is_local_request():
            return self.send_json(403, {"error": {"message": "SoundCloud credentials can only be configured from this local app."}})

        global soundcloud_credentials, soundcloud_token, soundcloud_token_expires_at, soundcloud_refresh_token
        if path == "/api/soundcloud/clear":
            with soundcloud_token_lock:
                soundcloud_credentials = None
                soundcloud_token = None
                soundcloud_token_expires_at = 0
                soundcloud_refresh_token = None
            return self.send_json(200, {"configured": False})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16384:
                return self.send_json(400, {"error": {"message": "Provide a valid SoundCloud Client ID and Client Secret."}})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                return self.send_json(400, {"error": {"message": "Provide a valid SoundCloud Client ID and Client Secret."}})
            client_id = str(payload.get("clientId", "")).strip()
            client_secret = str(payload.get("clientSecret", "")).strip()
        except ValueError:
            return self.send_json(400, {"error": {"message": "Provide a valid SoundCloud Client ID and Client Secret."}})

        if not client_id or not client_secret:
            return self.send_json(400, {"error": {"message": "Provide both a SoundCloud Client ID and Client Secret."}})

        try:
            token_data = self.request_soundcloud_token(client_id, client_secret)
        except HTTPError as error:
            self.log_error("SoundCloud credential verification failed with status %s.", error.code)
            return self.send_json(400, {"error": {"message": "SoundCloud rejected these credentials. Check the Client ID and Secret."}})
        except (URLError, TimeoutError, ValueError) as error:
            self.log_error("SoundCloud credential verification failed: %s", error)
            return self.send_json(502, {"error": {"message": "Could not connect to SoundCloud to verify these credentials."}})

        with soundcloud_token_lock:
            soundcloud_credentials = (client_id, client_secret)
            soundcloud_token = token_data["access_token"]
            soundcloud_refresh_token = token_data.get("refresh_token")
            soundcloud_token_expires_at = time.time() + int(token_data.get("expires_in", 3600))
        return self.send_json(200, {"configured": True})

    def is_local_request(self):
        origin = self.headers.get("Origin")
        if not origin or origin == "null":
            return False
        parsed_origin = urlsplit(origin)
        return parsed_origin.scheme in ("http", "https") and parsed_origin.hostname in ("127.0.0.1", "localhost")

    def request_soundcloud_token(self, client_id, client_secret, refresh_token=None):
        if refresh_token:
            payload = urlencode({
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }).encode("utf-8")
        else:
            credentials = b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
            payload = b"grant_type=client_credentials"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if not refresh_token:
            headers["Authorization"] = f"Basic {credentials}"
        request = Request("https://secure.soundcloud.com/oauth/token", data=payload, headers=headers)
        with urlopen(request, timeout=12) as response:
            token_data = json.loads(response.read())
        if not token_data.get("access_token"):
            raise ValueError("SoundCloud did not return an access token.")
        return token_data

    def get_soundcloud_access_token(self):
        global soundcloud_token, soundcloud_token_expires_at, soundcloud_refresh_token
        with soundcloud_token_lock:
            if not soundcloud_credentials:
                return None
            if soundcloud_token and time.time() < soundcloud_token_expires_at - 60:
                return soundcloud_token

            client_id, client_secret = soundcloud_credentials
            try:
                token_data = self.request_soundcloud_token(client_id, client_secret, soundcloud_refresh_token)
            except HTTPError:
                if not soundcloud_refresh_token:
                    raise
                token_data = self.request_soundcloud_token(client_id, client_secret)
            soundcloud_token = token_data["access_token"]
            soundcloud_refresh_token = token_data.get("refresh_token", soundcloud_refresh_token)
            soundcloud_token_expires_at = time.time() + int(token_data.get("expires_in", 3600))
            return soundcloud_token

    def search_soundcloud(self):
        query = parse_qs(urlsplit(self.path).query)
        term = query.get("q", [""])[0].strip()
        if not term:
            return self.send_json(400, {"error": {"message": "Enter a song or artist to search SoundCloud."}})
        try:
            limit = max(1, min(int(query.get("limit", ["25"])[0]), 50))
        except ValueError:
            limit = 25

        try:
            token = self.get_soundcloud_access_token()
            if not token:
                return self.send_json(503, {"error": {"message": "Add your SoundCloud app credentials in Settings to search tracks here."}})
            url = "https://api.soundcloud.com/tracks?" + urlencode({"q": term, "limit": limit})
            request = Request(url, headers={
                "Accept": "application/json",
                "Authorization": f"OAuth {token}",
            })
            with urlopen(request, timeout=15) as response:
                data = json.loads(response.read())
            tracks = data if isinstance(data, list) else data.get("collection", [])
            if not isinstance(tracks, list):
                raise ValueError("SoundCloud returned an invalid track list.")
            results = []
            for track in tracks:
                permalink = track.get("permalink_url")
                if not permalink or track.get("sharing") not in (None, "public"):
                    continue
                user = track.get("user") or {}
                artwork = track.get("artwork_url") or user.get("avatar_url") or ""
                results.append({
                    "id": str(track.get("urn") or track.get("id") or permalink),
                    "title": track.get("title") or "SoundCloud track",
                    "artist": track.get("metadata_artist") or user.get("username") or "SoundCloud",
                    "album": track.get("genre") or "",
                    "permalink": permalink,
                    "artwork": artwork,
                })
            return self.send_json(200, {"tracks": results})
        except HTTPError as error:
            self.log_error("SoundCloud search failed with status %s.", error.code)
            message = "SoundCloud rejected the request. Check that the app credentials are valid and enabled."
            return self.send_json(502, {"error": {"message": message}})
        except (URLError, TimeoutError, ValueError) as error:
            self.log_error("SoundCloud search request failed: %s", error)
            return self.send_json(502, {"error": {"message": "Could not search SoundCloud. Check your connection and app credentials."}})

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        path = urlsplit(self.path).path
        sys.stderr.write(f"{self.log_date_time_string()} {self.address_string()} {self.command} {path}\n")


class MusicAppServer(ThreadingHTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    handler = partial(MusicAppHandler)
    server = MusicAppServer(("127.0.0.1", 8000), handler)
    print("Up late Music is running at http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Up late Music.")
    finally:
        server.server_close()
