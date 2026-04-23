import os
from urllib.parse import quote_plus

import mysql.connector
import mysql
from hockey.helpers.pretty_print import *
from sqlalchemy import create_engine


def open_database(db_name="hockeystats_ver3"):
    stats_db = mysql.connector.connect(
        host="localhost",
        user="apa",
        auth_plugin='mysql_native_password',
        password="apa",
        database=db_name,
    )
    return stats_db


def open_database_azure(db_name: str | None = None):
    stats_db = mysql.connector.connect(
        host=os.environ["DATABASE_HOST_AZURE"],
        user=os.environ["DATABASE_USERNAME_AZURE"],
        auth_plugin='mysql_native_password',
        password=os.environ["DATABASE_PWD_AZURE"],
        database=db_name or os.getenv("DATABASE_NAME", "sportlogiq"),
    )
    return stats_db


def sqlalchemy_engine():
    engine = create_engine("mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3")
    return engine


def sqlalchemy_engine_azure():
    host = os.environ["DATABASE_HOST_AZURE"]
    user = os.environ["DATABASE_USERNAME_AZURE"]
    pwd = quote_plus(os.environ["DATABASE_PWD_AZURE"])
    db_name = os.getenv("DATABASE_NAME_AZURE", "sportlogiq")
    ssl_ca = os.getenv("DATABASE_SSL_CA", "~/DigiCertGlobalRootCA.crt.pem")
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{pwd}@{host}:3306/{db_name}",
        connect_args={"ssl_ca": ssl_ca},
    )
    return engine


def create_map(table, cursor=None, values: list[int] = None):
    if cursor is None:
        db = open_database()
        cursor = db.cursor()

    if values is None:
        sql = f"select id, sl_id from {table};"
    else:
        sql = f"select id, sl_id from {table} where sl_id in ({','.join([str(k) for k in values])});"
    try:
        cursor.execute(sql)
        map_data = cursor.fetchall()
        map = {row[1]: row[0] for row in map_data}
        return map
    except Exception as e:
        err(f"Error creating map: {e}")
        return None


def get_table_columns(table, cursor=None):
    cursor.execute(f"DESCRIBE {table}")
    columns = [row[0] for row in cursor.fetchall()]
    return columns


if __name__ == "__main__":
    try:
        db = open_database()
        cursor = db.cursor()
        cursor.execute(f"SELECT * FROM team;")
        ok("Connection to database OK")
    except Exception as e:
        err(f"Error connecting to database: {e}")

    tables = ['player', 'team', 'league']
    try:
        db = open_database()
        cursor = db.cursor()
        for t in tables:
            map = create_map(t, cursor)
            if map:
                ok(f"Map creation OK: {t}")
            else:
                err(f"Map creation failed: {t}")
    except Exception as e:
        err(f"Error creating maps {', '.join(tables)} {e}")
