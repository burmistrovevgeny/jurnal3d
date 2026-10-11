import pandas as pd
import sqlite3
import os
from datetime import datetime

DB_NAME = 'journal.db'
EXCEL_FILE = 'Журнал 3D (49).xlsx'  # Имя твоего файла

# Маппинг: что читаем из Excel -> куда пишем в БД
# Если названия столбцов в Excel отличаются, поменяй ключи слева на свои названия!
COLUMN_MAP = {
    'order_num': ['№ заказа', 'order_num', 'Заказ'],
    'employee': ['Сотрудник', 'employee', 'Исполнитель'],
    'scan_date': ['Дата', 'scan_date', 'Дата сканирования'],
    'object_name': ['Объект', 'object_name', 'Наименование'],
    'notes': ['Примечание', 'notes', 'Комментарий'],
    
    # Статусы (Цвета)
    'cloud_code': ['Статус облака', 'cloud_code', 'Cloud Status'],
    'cloud_note': ['Примечание облака', 'cloud_note', 'Cloud Note'],
    'cloud_by': ['Кто проверил облако', 'cloud_by'], # Если есть такой столбец
    
    'analysis_code': ['Статус анализа', 'analysis_code', 'Analysis Status'],
    'analysis_note': ['Примечание анализа', 'analysis_note', 'Analysis Note'],
    'analysis_by': ['Кто проверил анализ', 'analysis_by'],

    'e57_code': ['Статус E57', 'e57_code', 'E57 Status'],
    'e57_note': ['Примечание E57', 'e57_note', 'E57 Note'],
    'e57_by': ['Кто проверил E57', 'e57_by']
}

def find_column(df, possible_names):
    """Ищет в DataFrame столбец по списку возможных названий"""
    for name in possible_names:
        if name in df.columns:
            return name
    return None

def import_data():
    if not os.path.exists(EXCEL_FILE):
        print(f"❌ Файл {EXCEL_FILE} не найден!")
        return

    print(f"📂 Читаем файл: {EXCEL_FILE}...")
    try:
        # Читаем Excel. Если файл большой, можно добавить sheet_name=0
        df = pd.read_excel(EXCEL_FILE)
    except Exception as e:
        print(f"❌ Ошибка чтения Excel: {e}")
        return

    print(f"✅ Загружено строк: {len(df)}")
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Отключаем проверку уникальности, чтобы не было ошибок при дублях, если нужно
    # Но лучше сначала очистить таблицу или проверять по order_num
    # Для первого импорта лучше очистить таблицу, если там мусор, или делать INSERT IGNORE
    
    count_inserted = 0
    count_skipped = 0
    count_errors = 0

    for index, row in df.iterrows():
        try:
            # 1. Находим колонки в Excel
            o_num = find_column(df, COLUMN_MAP['order_num'])
            emp = find_column(df, COLUMN_MAP['employee'])
            s_date = find_column(df, COLUMN_MAP['scan_date'])
            obj = find_column(df, COLUMN_MAP['object_name'])
            note = find_column(df, COLUMN_MAP['notes'])

            # 2. Получаем базовые данные
            order_val = str(row[o_num]).strip() if o_num and pd.notna(row[o_num]) else None
            
            # Пропускаем, если нет номера заказа (это ключ)
            if not order_val or order_val.lower() == 'nan':
                continue

            # Форматируем дату
            date_val = row[s_date] if s_date and pd.notna(row[s_date]) else None
            if isinstance(date_val, datetime):
                date_str = date_val.strftime('%Y-%m-%d')
            elif isinstance(date_val, str):
                date_str = date_val
            else:
                date_str = None

            # 3. Получаем статусы (Цвета) и примечания
            # Функция для безопасного получения значения
            def get_val(col_map_key):
                col_name = find_column(df, COLUMN_MAP[col_map_key])
                if col_name and pd.notna(row[col_name]):
                    val = str(row[col_name]).strip()
                    return val if val.lower() != 'nan' else None
                return None

            # Собираем данные для всех полей
            data = {
                'order_num': order_val,
                'employee': get_val('employee'),
                'scan_date': date_str,
                'object_name': get_val('object_name'),
                'notes': get_val('notes'),
                
                'cloud_code': get_val('cloud_code'),
                'cloud_note': get_val('cloud_note'),
                'cloud_by': get_val('cloud_by'),
                'cloud_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), # Время импорта как время проверки
                
                'analysis_code': get_val('analysis_code'),
                'analysis_note': get_val('analysis_note'),
                'analysis_by': get_val('analysis_by'),
                'analysis_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                
                'e57_code': get_val('e57_code'),
                'e57_note': get_val('e57_note'),
                'e57_by': get_val('e57_by'),
                'e57_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                
                'is_deleted': 0,
                'deleted_at': None,
                'file_path': None
            }

            # 4. Проверяем, есть ли уже такой заказ (чтобы не дублировать)
            c.execute("SELECT id FROM journal WHERE order_num = ?", (data['order_num'],))
            existing = c.fetchone()

            if existing:
                # Если заказ есть, можно либо пропустить, либо обновить (UPDATE).
                # Сейчас настроено на ПРОПУСК, чтобы не затереть ручные правки в БД.
                # Если хочешь обновлять данные из Excel даже если запись есть, раскомментируй блок UPDATE ниже.
                count_skipped += 1
                continue

            # 5. Вставляем новую запись
            columns = ', '.join(data.keys())
            placeholders = ', '.join(['?'] * len(data))
            
            sql = f"INSERT INTO journal ({columns}) VALUES ({placeholders})"
            values = list(data.values())
            
            c.execute(sql, values)
            count_inserted += 1

        except Exception as e:
            print(f"⚠️ Ошибка на строке {index + 2}: {e}")
            count_errors += 1
            continue

    conn.commit()
    conn.close()

    print("-" * 30)
    print(f"🏁 ИМПОРТ ЗАВЕРШЕН:")
    print(f"✅ Добавлено новых записей: {count_inserted}")
    print(f"ℹ️ Пропущено (уже были в БД): {count_skipped}")
    print(f"❌ Ошибок: {count_errors}")

if __name__ == '__main__':
    import_data()
