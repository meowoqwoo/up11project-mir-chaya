import psycopg2
from psycopg2 import pool
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


DISCOUNT_PERCENT = 25

DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "mir_chaya"
DB_USER = "postgres"
DB_PASS = "123"

def get_db_connection():
    """Создает подключение к БД для проверки заказов."""
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )

def get_previous_month_range(calculation_date):
    """Возвращает [начало предыдущего месяца; начало текущего месяца)."""
    current_month_start = calculation_date.replace(day=1)
    if current_month_start.month == 1:
        previous_month_start = current_month_start.replace(year=current_month_start.year - 1, month=12)
    else:
        previous_month_start = current_month_start.replace(month=current_month_start.month - 1)
    return previous_month_start, current_month_start

def get_ordered_product_ids(start_date, end_date):
    """Возвращает множество ID товаров, которые заказывали в указанный период."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT si.product_id
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN stock_items si ON oi.stock_item_id = si.stock_item_id
            WHERE o.order_date >= %s AND o.order_date < %s
        """, (start_date, end_date))
        ids = {row[0] for row in cursor.fetchall()}
        return ids
    finally:
        cursor.close()
        conn.close()

def calculate_final_price(price, has_orders_last_month):
    """Вычисляет цену со скидкой (если заказов не было)."""
    price = Decimal(str(price))
    if has_orders_last_month:
        return price
    multiplier = Decimal(100 - DISCOUNT_PERCENT) / Decimal(100)
    return (price * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def calculate_price(product_id, base_price, calculation_date=None):
    """
    Главная функция расчета.
    Принимает ID товара и его базовую цену.
    Возвращает итоговую цену (со скидкой, если нужно).
    """
    if calculation_date is None:
        calculation_date = date.today()
        
    period_start, period_end = get_previous_month_range(calculation_date)
    
    ordered_ids = get_ordered_product_ids(period_start, period_end)
    
    has_orders = product_id in ordered_ids
    
    final_price = calculate_final_price(base_price, has_orders)
    
    return float(final_price)


if __name__ == "__main__":
    print("=== Тест расчета скидки ===")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT product_id, name, base_price FROM products LIMIT 1")
        p = cur.fetchone()
        cur.close()
        conn.close()

        if p:
            p_id, p_name, p_price = p
            print(f"Товар: {p_name} (ID: {p_id})")
            print(f"Базовая цена: {p_price} ₽")
            
            final_p = calculate_price(p_id, p_price)
            print(f"Итоговая цена (скидка 25% если не заказывали в прошлом месяце): {final_p} ₽")
        else:
            print("В базе нет товаров для теста.")
    except Exception as e:
        print(f"Ошибка: {e}")