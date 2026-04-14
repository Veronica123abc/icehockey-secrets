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

def open_database_azure(db_name="hockeystats_ver3"):
    stats_db = mysql.connector.connect(
        host="localhost",
        user="apa",
        auth_plugin='mysql_native_password',
        password="apa",
        database=db_name,
    )
    return stats_db

def sqlalchemy_engine():
    #engine = create_engine("mysql://localhost/mysql/mysql-5.1.1-10.1.")
    engine = create_engine("mysql+mysqlconnector://apa:apa@localhost:3306/hockeystats_ver3")
    # engine = create_engine(
    #     f"mysql+mysqlconnector://mysqladmin:B1llyfjant.1@mysql-flex-public.mysql.database.azure.com:3306/your_database",
    #     connect_args={"ssl_ca": "~/DigiCertGlobalRootCA.crt.pem"}
    # )
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
    """Get list of column names for a table."""
    cursor.execute(f"DESCRIBE {table}")
    columns = [row[0] for row in cursor.fetchall()]
    return columns

if __name__ == "__main__":
    # Test database connection
    try:
        db = open_database()
        cursor = db.cursor()
        cursor.execute(f"SELECT * FROM team;")
        ok("Connection to database OK")
    except Exception as e:
        err(f"Error connecting to database: {e}")

    # Test map creation
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

