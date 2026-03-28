
-- Schema creation for Bookstore DB (SQLite compatible)

CREATE TABLE authors (
    author_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    country VARCHAR(100),
    bio TEXT
);

CREATE TABLE books (
    book_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(255) NOT NULL,
    author_id INTEGER,
    genre VARCHAR(100),
    price DECIMAL(10, 2),
    stock INTEGER DEFAULT 0,
    published_date DATE,
    FOREIGN KEY(author_id) REFERENCES authors(author_id)
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    city VARCHAR(100),
    country VARCHAR(100),
    joined_date DATE
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER,
    order_date DATETIME,
    total_amount DECIMAL(10, 2),
    status VARCHAR(50),
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    book_id INTEGER,
    quantity INTEGER,
    unit_price DECIMAL(10, 2),
    FOREIGN KEY(order_id) REFERENCES orders(order_id),
    FOREIGN KEY(book_id) REFERENCES books(book_id)
);

CREATE TABLE reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER,
    customer_id INTEGER,
    rating INTEGER CHECK(rating >= 1 AND rating <= 5),
    comment TEXT,
    review_date DATE,
    FOREIGN KEY(book_id) REFERENCES books(book_id),
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);
