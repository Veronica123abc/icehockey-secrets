import os
from urllib.parse import quote_plus

import mysql.connector
import mysql
from hockey.config.settings import load_dotenv
from hockey.helpers.pretty_print import *
from sqlalchemy import create_engine


def open_database(db_name="hockeystats_v2"):
    stats_db = mysql.connector.connect(
        host="localhost",
        user="apa",
        auth_plugin='mysql_native_password',
        password="apa",
        database=db_name,
    )
    return stats_db


def open_database_azure(db_name: str | None = None):
    # The .env is read here rather than left to whatever the caller imported:
    # every one of the variables below comes from it, and a caller that has
    # not built a Settings object is not a caller that should fail.
    load_dotenv()
    stats_db = mysql.connector.connect(
        host=os.environ["DATABASE_HOST_AZURE"],
        user=os.environ["DATABASE_USERNAME_AZURE"],
        auth_plugin='mysql_native_password',
        password=os.environ["DATABASE_PWD_AZURE"],
        database=db_name or os.getenv("DATABASE_NAME_AZURE", "sportlogiq"),
    )
    return stats_db


def sqlalchemy_engine():
    engine = create_engine("mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3")
    return engine


def sqlalchemy_engine_azure():
    load_dotenv()
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


def shift_key(player_id, in_time, out_time):
    """The identity of a shift row, as a comparable tuple.

    The times are rounded to the centisecond because v1 stores them in a
    FLOAT column: a double written as 1234.567 reads back as 1234.5670166,
    and an exact comparison would call that a different shift.
    """
    def t(v):
        return None if v is None else round(float(v), 2)

    return (int(player_id), t(in_time), t(out_time))


def existing_shift_keys(game_db_id: int, cursor) -> set:
    """`shift_key`s already stored for one game.

    Both shift ingests filter against this instead of inserting blind. They
    have to: v1's `shift` has a UNIQUE on (player, game, in, out), so a
    re-run fails the whole batch, and v2 has no unique key at all, so the
    same re-run silently doubles every shift of the game.
    """
    cursor.execute(
        "SELECT player_id, in_time, out_time FROM shift WHERE game_id = %s",
        (game_db_id,))
    return {shift_key(*row) for row in cursor.fetchall()}


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
