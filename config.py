import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="btz7zr3tt1erxfbygo4e-mysql.services.clever-cloud.com",
        user="uep6l1uhu56nkbi3",
        password="CNacQRq1VtTrNx01CoX6",
        database="btz7zr3tt1erxfbygo4e",
        port="3306"
        
    )

