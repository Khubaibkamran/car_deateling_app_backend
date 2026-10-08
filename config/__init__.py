import pymysql

# Use the pure-Python PyMySQL driver as Django's MySQL client (no C compiler needed on Windows).
pymysql.install_as_MySQLdb()
