import os, mysql.connector
from pathlib import Path

# Load .env the same way app.py does
dotenv = Path(__file__).parent / ".env"
if dotenv.exists():
    for line in dotenv.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

try:
    conn = mysql.connector.connect(
        host=os.environ["DATABASE_HOST_AZURE"],
        user=os.environ["DATABASE_USERNAME_AZURE"],
        password=os.environ["DATABASE_PWD_AZURE"],
        database=os.environ.get("DATABASE_NAME_AZURE", "sportlogiq"),
        connect_timeout=5,
        ssl_disabled=False,
    )
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print("Connected OK:", cur.fetchone())
    conn.close()
except Exception as e:
    print("FAILED:", e)
