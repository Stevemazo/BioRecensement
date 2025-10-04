import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="b5wukeymkwlavs8t0nmf-mysql.services.clever-cloud.com",
        user="u3zvttr70dqoe1mn",
        password="u3zvttr70dqoe1mn",
        database="b5wukeymkwlavs8t0nmf",
        port=3306
        
    )
    