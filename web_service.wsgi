import sys
sys.path.insert(0, "/app")

from db import init_db
from web_service import app as application

init_db()
