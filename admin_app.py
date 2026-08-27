from http.server import ThreadingHTTPServer

from app import BlogHandler, initialize_database


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", 8001), BlogHandler)
    print("Private Let Money Earn admin is running at http://127.0.0.1:8001/admin-login.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()