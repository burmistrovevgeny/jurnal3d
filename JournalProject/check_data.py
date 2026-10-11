import sqlite3

DB_NAME = 'journal.db'
conn = sqlite3.connect(DB_NAME)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Выбираем первые 10 записей, чтобы просто посмотреть
rows = c.execute("SELECT id, order_num, employee, scan_date, object_name FROM journal LIMIT 10").fetchall()

print(f"Найдено записей в базе: {len(rows)}")
print("-" * 50)
for row in rows:
    print(f"ID: {row['id']} | Заказ: {row['order_num']} | Сотрудник: {row['employee']} | Дата: {row['scan_date']}")

conn.close()
