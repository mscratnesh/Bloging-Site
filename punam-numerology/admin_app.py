from http.server import ThreadingHTTPServer

from app import NumerologyHandler, initialize_database


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", 8021), NumerologyHandler)
    print("Private Punam Numerology admin is running at http://127.0.0.1:8021/admin-login.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
