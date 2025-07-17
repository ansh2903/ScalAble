'''
This module is responsible for executing the query generated(based on
which database the user chose) by the model onto the database
'''

import psycopg2

conn = psycopg2.connect(
    database="testdb", user='postgres', password = 'admin',
    host='localhost', port='5432'
)

cursor = conn.cursor()

sql = '''Select * from employee; '''

cursor.execute(sql)
results = cursor.fetchall()

print(results)

conn.commit()
conn.close()

def run_query(db_type: str, form_data, query: str, ):
    if db_type == 'postgresql':
        pass
        


if __name__ == "__main__":
    pass