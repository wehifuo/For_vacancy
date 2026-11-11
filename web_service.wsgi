import sys
sys.path.insert(0, "/app")

from web_service import app as application, init_db

init_db()
