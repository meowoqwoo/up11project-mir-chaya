import sys
import os
import psycopg2
from psycopg2 import pool
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QLineEdit, QComboBox, QPushButton, QScrollArea, 
                               QMessageBox, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox)
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
RES_DIR = os.path.join(ROOT_DIR, "resources")

DISCOUNT_PERCENT = 25

def get_ordered_product_ids(start_date, end_date):
    try:
        conn = psycopg2.connect(host="localhost", port=5432, database="mir_chaya", user="postgres", password="123")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT si.product_id
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN stock_items si ON oi.stock_item_id = si.stock_item_id
            WHERE o.order_date >= %s AND o.order_date < %s
        """, (start_date, end_date))
        ids = {row[0] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        return ids
    except Exception as e:
        print(f"Ошибка БД при проверке скидки: {e}")
        return set()

def calculate_discount_price(price, has_orders):
    price = Decimal(str(price))
    if has_orders:
        return price
    multiplier = Decimal(100 - DISCOUNT_PERCENT) / Decimal(100)
    return (price * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

class Database:
    def __init__(self):
        self.connection_pool = None
        self.init_pool()

    def init_pool(self):
        try:
            self.connection_pool = pool.SimpleConnectionPool(
                1, 10, host="localhost", port=5432, database="mir_chaya", user="postgres", password="123"
            )
        except psycopg2.Error as e:
            print(f"Ошибка БД: {e}")

    def get_connection(self):
        if self.connection_pool: return self.connection_pool.getconn()
        return None

    def release_connection(self, conn):
        if self.connection_pool and conn: self.connection_pool.putconn(conn)

    def check_login(self, login):
        conn = self.get_connection()
        if not conn: return None
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.user_id, u.role_id, u.last_name, u.first_name, u.middle_name, r.name 
            FROM users u
            JOIN roles r ON u.role_id = r.role_id
            WHERE u.login = %s
        """, (login,))
        user = cursor.fetchone()
        cursor.close()
        self.release_connection(conn)
        return user

    def get_categories(self):
        conn = self.get_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM categories ORDER BY name")
        cats = [row[0] for row in cursor.fetchall()]
        cursor.close()
        self.release_connection(conn)
        return cats

    def get_products(self, search="", category="Все категории", sort="По возрастанию цены"):
        conn = self.get_connection()
        if not conn: return []
        cursor = conn.cursor()
        
        query = """
            SELECT p.product_id, p.name, p.manufacturer, p.description, p.composition, 
                   p.image_path, p.base_price, c.name as category, COALESCE(SUM(si.quantity), 0) as total_quantity
            FROM products p
            LEFT JOIN stock_items si ON p.product_id = si.product_id
            JOIN categories c ON p.category_id = c.category_id
            WHERE (p.name ILIKE %s OR p.description ILIKE %s)
        """
        params = [f"%{search}%", f"%{search}%"]
        if category != "Все категории":
            query += " AND c.name = %s"
            params.append(category)
        
        query += " GROUP BY p.product_id, c.name"
        
        if sort == "По возрастанию цены":
            query += " ORDER BY p.base_price ASC"
        elif sort == "По убыванию цены":
            query += " ORDER BY p.base_price DESC"
        elif sort == "По алфавиту (А-Я)":
            query += " ORDER BY p.name ASC"
            
        cursor.execute(query, tuple(params))
        raw_products = cursor.fetchall()
        cursor.close()
        self.release_connection(conn)

        ordered_ids = get_ordered_product_ids(date(2026, 4, 1), date(2026, 5, 1))

        products = []
        for row in raw_products:
            p_id, name, mfg, desc, comp, img, base_price, cat, qty = row
            has_orders = p_id in ordered_ids
            final_price = calculate_discount_price(base_price, has_orders)
            
            products.append({
                "product_id": p_id, "name": name, "manufacturer": mfg, "description": desc, 
                "composition": comp, "image_path": img, "base_price": float(base_price), 
                "final_price": float(final_price), "has_discount": not has_orders,
                "category": cat, "total_quantity": qty
            })
        return products

    def get_variants_for_product(self, product_id, has_discount):
        conn = self.get_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.stock_item_id, v.name as variant_name, si.quantity, si.price
            FROM stock_items si JOIN variants v ON si.variant_id = v.variant_id
            WHERE si.product_id = %s ORDER BY si.price ASC
        """, (product_id,))
        variants = []
        for v_id, v_name, v_qty, v_price in cursor.fetchall():
            final_v_price = calculate_discount_price(v_price, not has_discount)
            variants.append((v_id, v_name, v_qty, float(final_v_price)))
        cursor.close()
        self.release_connection(conn)
        return variants

    def create_order(self, user_id, cart_items):
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO orders (user_id, order_date) VALUES (%s, %s) RETURNING order_id", (user_id, date.today()))
            order_id = cursor.fetchone()[0]
            
            for item in cart_items:
                cursor.execute("SELECT quantity FROM stock_items WHERE stock_item_id = %s FOR UPDATE", (item['stock_item_id'],))
                if cursor.fetchone()[0] < item['quantity']: 
                    raise Exception(f"Мало товара на складе: {item['name']}")
                
                cursor.execute("INSERT INTO order_items (order_id, stock_item_id, quantity, price) VALUES (%s, %s, %s, %s)", 
                               (order_id, item['stock_item_id'], item['quantity'], item['price']))
                cursor.execute("UPDATE stock_items SET quantity = quantity - %s WHERE stock_item_id = %s", 
                               (item['quantity'], item['stock_item_id']))
            
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            QMessageBox.critical(None, "Ошибка оформления", str(e))
            return False
        finally:
            cursor.close()
            self.release_connection(conn)

    def get_orders(self, role_id, user_id):
        conn = self.get_connection()
        if not conn: return []
        cursor = conn.cursor()
        query = """
            SELECT o.order_id, o.order_date, 
                   u.last_name || ' ' || u.first_name || ' ' || COALESCE(u.middle_name, ''), 
                   SUM(oi.quantity * oi.price)
            FROM orders o JOIN users u ON o.user_id = u.user_id
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
        """
        if role_id == 3:
            query += " WHERE o.user_id = %s GROUP BY o.order_id, u.last_name, u.first_name, u.middle_name ORDER BY o.order_date DESC"
            cursor.execute(query, (user_id,))
        else:
            query += " GROUP BY o.order_id, u.last_name, u.first_name, u.middle_name ORDER BY o.order_date DESC"
            cursor.execute(query)
        orders = cursor.fetchall()
        cursor.close()
        self.release_connection(conn)
        return orders

    def get_order_details(self, order_id):
        conn = self.get_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.name, p.manufacturer, v.name, oi.quantity, oi.price, (oi.quantity * oi.price)
            FROM order_items oi JOIN stock_items si ON oi.stock_item_id = si.stock_item_id
            JOIN products p ON si.product_id = p.product_id JOIN variants v ON si.variant_id = v.variant_id
            WHERE oi.order_id = %s
        """, (order_id,))
        details = cursor.fetchall()
        cursor.close()
        self.release_connection(conn)
        return details

    def delete_order(self, order_id):
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT stock_item_id, quantity FROM order_items WHERE order_id = %s", (order_id,))
            for stock_id, qty in cursor.fetchall():
                cursor.execute("UPDATE stock_items SET quantity = quantity + %s WHERE stock_item_id = %s", (qty, stock_id))
            cursor.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
            cursor.execute("DELETE FROM orders WHERE order_id = %s", (order_id,))
            conn.commit()
            return True
        except:
            conn.rollback()
            return False
        finally:
            cursor.close()
            self.release_connection(conn)

class ProductDetailDialog(QDialog):
    def __init__(self, p_data, db, cart, parent=None):
        super().__init__(parent)
        self.db, self.cart, self.p = db, cart, p_data
        self.setWindowTitle(f"Товар: {self.p['name']}")
        self.resize(500, 400)
        layout = QVBoxLayout()
        
        top = QHBoxLayout()
        img_lbl = QLabel()
        img_path = os.path.join(RES_DIR, self.p['image_path'] if self.p['image_path'] else "picture.png")
        if not os.path.exists(img_path): img_path = os.path.join(RES_DIR, "picture.png")
        img_lbl.setPixmap(QPixmap(img_path).scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(img_lbl)
        
        info = QVBoxLayout()
        info.addWidget(QLabel(f"<b>{self.p['manufacturer']} | {self.p['name']}</b>"))
        info.addWidget(QLabel(f"<i>{self.p['description']}</i>"))
        if self.p['has_discount']:
            info.addWidget(QLabel(f"<span style='color:red; text-decoration:line-through;'>{self.p['base_price']:.2f} ₽</span>"))
            info.addWidget(QLabel(f"<b style='color:green;'>Со скидкой 25%: {self.p['final_price']:.2f} ₽</b>"))
        top.addLayout(info)
        layout.addLayout(top)
        
        layout.addWidget(QLabel("Выберите вариант упаковки:"))
        self.combo = QComboBox()
        self.vars = self.db.get_variants_for_product(self.p['product_id'], self.p['has_discount'])
        for v in self.vars:
            self.combo.addItem(f"{v[1]} - {v[3]:.2f} ₽ (В наличии: {v[2]})" if v[2] > 0 else f"{v[1]} - Нет", v[0])
        layout.addWidget(self.combo)
        
        layout.addWidget(QLabel("Количество:"))
        self.qty = QSpinBox(); self.qty.setMinimum(1); layout.addWidget(self.qty)
        self.combo.currentIndexChanged.connect(lambda: self.qty.setMaximum(self.vars[self.combo.currentIndex()][2] if self.vars[self.combo.currentIndex()][2] > 0 else 1))
        
        btn = QPushButton("Добавить в корзину")
        btn.setStyleSheet("background-color: #70B2AF; color: black; font-weight: bold;")
        btn.clicked.connect(self.add_to_cart)
        layout.addWidget(btn)
        self.setLayout(layout)

    def add_to_cart(self):
        idx = self.combo.currentIndex()
        if idx < 0 or self.vars[idx][2] <= 0: return
        v_id, v_name, v_qty, v_price = self.vars[idx]
        for item in self.cart:
            if item['stock_item_id'] == v_id:
                item['quantity'] += self.qty.value()
                QMessageBox.information(self, "Успех", "Товар добавлен в корзину!")
                self.accept(); return
        self.cart.append({'stock_item_id': v_id, 'name': self.p['name'], 'variant': v_name, 'price': float(v_price), 'quantity': self.qty.value()})
        QMessageBox.information(self, "Успех", "Товар добавлен в корзину!")
        self.accept()

class ProductCard(QWidget):
    def __init__(self, p_data, db, cart):
        super().__init__()
        self.p, self.db, self.cart = p_data, db, cart
        self.setStyleSheet("background-color: #ff8080; border-radius: 5px; margin: 2px;" if self.p['total_quantity'] <= 3 else "background-color: #FFFFFF; border: 1px solid #ccc; border-radius: 5px; margin: 2px;")
        
        layout = QHBoxLayout(self)
        img_lbl = QLabel()
        img_path = os.path.join(RES_DIR, self.p['image_path'] if self.p['image_path'] else "picture.png")
        if not os.path.exists(img_path): img_path = os.path.join(RES_DIR, "picture.png")
        img_lbl.setPixmap(QPixmap(img_path).scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        img_lbl.setFixedSize(100, 100)
        layout.addWidget(img_lbl)

        text = QVBoxLayout()
        text.addWidget(QLabel(f"<b>{self.p['manufacturer']} | {self.p['name']}</b>"))
        text.addWidget(QLabel(f"В наличии: {self.p['total_quantity']} упак."))
        layout.addLayout(text)
        layout.addStretch()

        right = QVBoxLayout()
        if self.p['has_discount']:
            right.addWidget(QLabel(f"<span style='color:red; text-decoration:line-through;'>{self.p['base_price']:.2f} ₽</span>"))
            right.addWidget(QLabel(f"<b style='color:green;'>{self.p['final_price']:.2f} ₽</b>"))
        else:
            right.addWidget(QLabel(f"<b>от {self.p['base_price']:.2f} ₽</b>"))

        btn = QPushButton("Подробнее")
        btn.clicked.connect(lambda: ProductDetailDialog(self.p, self.db, self.cart, self).exec())
        right.addWidget(btn)
        layout.addLayout(right)

class CartDialog(QDialog):
    def __init__(self, cart, db, user_id, parent=None):
        super().__init__(parent)
        self.cart, self.db, self.user_id = cart, db, user_id
        self.setWindowTitle("Корзина")
        self.resize(600, 400)
        
        layout = QVBoxLayout()
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Товар", "Вариант", "Цена", "Кол-во", "Сумма"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        self.total_lbl = QLabel("Итого: 0.00 ₽")
        self.total_lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(self.total_lbl)
        
        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.clear_cart)
        btn_layout.addWidget(clear_btn)
        
        checkout_btn = QPushButton("Оформить заказ")
        checkout_btn.setStyleSheet("background-color: #70B2AF; color: black; font-weight: bold;")
        checkout_btn.clicked.connect(self.checkout)
        btn_layout.addWidget(checkout_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.update_table()

    def update_table(self):
        self.table.setRowCount(len(self.cart))
        total = 0
        for i, item in enumerate(self.cart):
            self.table.setItem(i, 0, QTableWidgetItem(item['name']))
            self.table.setItem(i, 1, QTableWidgetItem(item['variant']))
            self.table.setItem(i, 2, QTableWidgetItem(f"{item['price']:.2f}"))
            self.table.setItem(i, 3, QTableWidgetItem(str(item['quantity'])))
            s = item['price'] * item['quantity']
            total += s
            self.table.setItem(i, 4, QTableWidgetItem(f"{s:.2f}"))
        self.total_lbl.setText(f"Итого: {total:.2f} ₽")

    def clear_cart(self):
        self.cart.clear()
        self.update_table()

    def checkout(self):
        if not self.cart:
            QMessageBox.warning(self, "Ошибка", "Корзина пуста!")
            return
            
        if self.user_id is None:
            QMessageBox.warning(self, "Ошибка", "Гостям нельзя оформлять заказы. Войдите в аккаунт!")
            return

        if self.db.create_order(self.user_id, self.cart):
            QMessageBox.information(self, "Успех", "Заказ успешно оформлен! Он появился в списке заказов.")
            self.cart.clear()
            self.update_table()
            self.accept()

class OrdersDialog(QDialog):
    def __init__(self, db, role_id, user_id, parent=None):
        super().__init__(parent)
        self.db, self.role_id, self.user_id = db, role_id, user_id
        self.setWindowTitle("Список заказов"); self.resize(800, 500)
        
        layout = QVBoxLayout()
        self.table = QTableWidget(); self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["№", "Дата", "Клиент", "Сумма"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        view_btn = QPushButton("Просмотр состава")
        view_btn.clicked.connect(self.view_details)
        btn_layout.addWidget(view_btn)
        
        if self.role_id in [1, 2]:
            del_btn = QPushButton("Удалить заказ")
            del_btn.setStyleSheet("background-color: #ff8080; color: black;")
            del_btn.clicked.connect(self.delete_order)
            btn_layout.addWidget(del_btn)
            
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.load_orders()

    def load_orders(self):
        orders = self.db.get_orders(self.role_id, self.user_id)
        self.table.setRowCount(len(orders))
        for i, o in enumerate(orders):
            self.table.setItem(i, 0, QTableWidgetItem(str(o[0])))
            self.table.setItem(i, 1, QTableWidgetItem(str(o[1])))
            self.table.setItem(i, 2, QTableWidgetItem(str(o[2])))
            self.table.setItem(i, 3, QTableWidgetItem(f"{o[3]:.2f} ₽" if o[3] else "0.00 ₽"))

    def view_details(self):
        row = self.table.currentRow()
        if row < 0: return
        order_id = int(self.table.item(row, 0).text())
        details = self.db.get_order_details(order_id)
        msg = f"<b>Состав заказа №{order_id}:</b><br><br>"
        for d in details:
            msg += f"{d[1]} | {d[0]} ({d[2]}) - {d[3]} шт. x {d[4]:.2f} ₽ = {d[5]:.2f} ₽<br>"
        QMessageBox.information(self, "Детали заказа", msg)

    def delete_order(self):
        row = self.table.currentRow()
        if row < 0: return
        order_id = int(self.table.item(row, 0).text())
        reply = QMessageBox.question(self, "Удаление", f"Удалить заказ №{order_id}? Остатки будут возвращены на склад.", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.db.delete_order(order_id):
                QMessageBox.information(self, "Успех", "Заказ удален")
                self.load_orders()

class MainWindow(QMainWindow):
    def __init__(self, db, role_id=None, full_name="Гость", login_window=None, user_id=None, role_name=""):
        super().__init__()
        self.db, self.role_id, self.user_id = db, role_id, user_id
        self.full_name, self.login_window, self.cart = full_name, login_window, []
        self.role_name = role_name
        
        self.setWindowTitle("Мир чая — Каталог"); self.resize(1000, 800)
        self.setWindowIcon(QIcon(os.path.join(RES_DIR, "icon.ico")))

        central = QWidget(); self.setCentralWidget(central)
        main_l = QVBoxLayout(central)

        header = QWidget(); header.setStyleSheet("background-color: #D2F6E7;")
        h_l = QHBoxLayout(header)
        logo = QLabel(); logo.setPixmap(QPixmap(os.path.join(RES_DIR, "logo.png")).scaledToHeight(50))
        h_l.addWidget(logo); h_l.addStretch()
        h_l.addWidget(QLabel(f"<b>ФИО: {self.full_name}</b>"))
        
        if self.role_name in ["Администратор", "Менеджер"]:
            b_orders = QPushButton("Заказы")
            b_orders.setStyleSheet("background-color: #70B2AF; color: black;")
            b_orders.clicked.connect(lambda: OrdersDialog(self.db, self.role_id, self.user_id, self).exec())
            h_l.addWidget(b_orders)
        
        if self.role_name == "Авторизованный пользователь" or self.role_id is None:
            b_cart = QPushButton("Корзина")
            b_cart.setStyleSheet("background-color: #70B2AF; color: black;")
            b_cart.clicked.connect(lambda: CartDialog(self.cart, self.db, self.user_id, self).exec())
            h_l.addWidget(b_cart)
            
        b_logout = QPushButton("Выход")
        b_logout.setStyleSheet("background-color: #70B2AF; color: black;")
        b_logout.clicked.connect(self.logout); h_l.addWidget(b_logout)
        main_l.addWidget(header)

        filt = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Поиск по названию..."); self.search.textChanged.connect(self.load_products)
        filt.addWidget(self.search)
        
        self.cat = QComboBox(); self.cat.addItem("Все категории"); self.cat.addItems(self.db.get_categories()); self.cat.currentIndexChanged.connect(self.load_products)
        filt.addWidget(self.cat)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["По возрастанию цены", "По убыванию цены", "По алфавиту (А-Я)"])
        self.sort_combo.currentIndexChanged.connect(self.load_products)
        filt.addWidget(self.sort_combo)
        
        main_l.addLayout(filt)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll_w = QWidget(); self.scroll_l = QVBoxLayout(self.scroll_w)
        self.scroll.setWidget(self.scroll_w); main_l.addWidget(self.scroll)
        self.load_products()

    def load_products(self):
        products = self.db.get_products(self.search.text(), self.cat.currentText(), self.sort_combo.currentText())
        for i in reversed(range(self.scroll_l.count())): 
            w = self.scroll_l.itemAt(i).widget()
            if w: w.setParent(None)
        for p in products: self.scroll_l.addWidget(ProductCard(p, self.db, self.cart))
        self.scroll_l.addStretch()

    def logout(self):
        if QMessageBox.question(self, "Выход", "Вы уверены?") == QMessageBox.Yes:
            self.close()
            if self.login_window: self.login_window.show()

class LoginWindow(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Авторизация"); self.resize(300, 250)
        self.setWindowIcon(QIcon(os.path.join(RES_DIR, "icon.ico")))
        l = QVBoxLayout()
        l.addWidget(QLabel("<b>Вход в систему</b>"))
        self.login_in = QLineEdit(); self.login_in.setPlaceholderText("Логин (admin, client01)"); l.addWidget(self.login_in)
        
        btn = QPushButton("Войти"); btn.clicked.connect(self.check)
        l.addWidget(btn)
        
        g_btn = QPushButton("Войти как гость"); g_btn.setStyleSheet("background-color: #D2F6E7;")
        g_btn.clicked.connect(self.guest)
        l.addWidget(g_btn)
        self.setLayout(l)

    def check(self):
        user = self.db.check_login(self.login_in.text().strip())
        if not user: 
            QMessageBox.warning(self, "Ошибка", "Неверный логин")
            return
        
        full_fio = f"{user[2]} {user[3]} {user[4] if user[4] else ''}".strip()
        self.mw = MainWindow(self.db, user[1], full_fio, self, user[0], user[5])
        self.mw.show(); self.close()

    def guest(self):
        self.mw = MainWindow(self.db, None, "Гость", self, None, "Гость"); self.mw.show(); self.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    db = Database()
    login = LoginWindow(db); login.show()
    sys.exit(app.exec())