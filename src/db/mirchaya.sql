CREATE DATABASE mir_chaya;

CREATE TABLE categories (
    category_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE variants (
    variant_id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE -- масса упаковки (50 г, 100 г, 200 г)
);

CREATE TABLE roles (
    role_id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES categories(category_id),
    variant_id INTEGER REFERENCES variants(variant_id), 
    name VARCHAR(200) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    image_path VARCHAR(255),
    description TEXT,
    composition TEXT,
    base_price NUMERIC(10,2) CHECK (base_price > 0)
);

CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    role_id INTEGER REFERENCES roles(role_id),
    last_name VARCHAR(100) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    login VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE stock_items (
    stock_item_id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(product_id),
    variant_id INTEGER REFERENCES variants(variant_id),
    quantity INTEGER CHECK (quantity >= 0),
    price NUMERIC(10,2) CHECK (price > 0),
    UNIQUE(product_id, variant_id)
);

CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    order_date DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(order_id),
    stock_item_id INTEGER REFERENCES stock_items(stock_item_id),
    quantity INTEGER CHECK (quantity > 0),
    price NUMERIC(10,2) CHECK (price > 0)
);


