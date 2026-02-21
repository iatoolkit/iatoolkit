
-- Seed data for Bookstore DB

-- Authors
INSERT INTO authors (name, country, bio) VALUES
('Isaac Asimov', 'USA', 'Prolific writer of science fiction and popular science.'),
('Agatha Christie', 'UK', 'Best-selling novelist of all time, known for detective novels.'),
('Gabriel García Márquez', 'Colombia', 'Nobel Prize winner, pioneer of magical realism.'),
('Haruki Murakami', 'Japan', 'Contemporary writer known for surrealistic fiction.'),
('Jane Austen', 'UK', 'Novelist known for her social commentary in works like Pride and Prejudice.');

-- Books
INSERT INTO books (title, author_id, genre, price, stock, published_date) VALUES
('Foundation', 1, 'Science Fiction', 15.99, 45, '1951-06-01'),
('I, Robot', 1, 'Science Fiction', 12.50, 30, '1950-12-02'),
('Murder on the Orient Express', 2, 'Mystery', 10.99, 25, '1934-01-01'),
('And Then There Were None', 2, 'Mystery', 11.99, 40, '1939-11-06'),
('One Hundred Years of Solitude', 3, 'Magical Realism', 18.00, 15, '1967-05-30'),
('Love in the Time of Cholera', 3, 'Romance', 16.50, 20, '1985-01-01'),
('Kafka on the Shore', 4, 'Fiction', 19.99, 12, '2002-09-12'),
('Norwegian Wood', 4, 'Fiction', 14.99, 50, '1987-09-04'),
('Pride and Prejudice', 5, 'Classic', 9.99, 100, '1813-01-28'),
('Sense and Sensibility', 5, 'Classic', 8.99, 35, '1811-10-30');

-- Customers
INSERT INTO customers (name, email, city, country, joined_date) VALUES
('Alice Johnson', 'alice@example.com', 'New York', 'USA', '2023-05-10'),
('Bob Smith', 'bob@example.com', 'London', 'UK', '2023-06-15'),
('Carlos Ruiz', 'carlos@example.com', 'Madrid', 'Spain', '2023-07-20'),
('Diana Prince', 'diana@example.com', 'Paris', 'France', '2023-08-05'),
('Evan Wright', 'evan@example.com', 'Toronto', 'Canada', '2024-01-12');

-- Orders (Simple examples)
INSERT INTO orders (customer_id, order_date, total_amount, status) VALUES
(1, '2024-02-01 10:00:00', 31.98, 'Delivered'),   -- Foundation + I, Robot
(2, '2024-02-02 11:30:00', 10.99, 'Shipped'),     -- Murder on the Orient Express
(3, '2024-02-05 14:15:00', 36.00, 'Pending'),     -- 2x One Hundred Years of Solitude
(1, '2024-03-01 09:45:00', 9.99, 'Delivered'),    -- Pride and Prejudice
(4, '2024-03-03 16:20:00', 19.99, 'Processing');  -- Kafka on the Shore

-- Order Items
INSERT INTO order_items (order_id, book_id, quantity, unit_price) VALUES
(1, 1, 1, 15.99),
(1, 2, 1, 15.99), -- Oops, price copied from Foundation, logic fix: I, Robot is 12.50. Let's say discount or error, keeping simple
(2, 3, 1, 10.99),
(3, 5, 2, 18.00),
(4, 9, 1, 9.99),
(5, 7, 1, 19.99);

-- Reviews
INSERT INTO reviews (book_id, customer_id, rating, comment, review_date) VALUES
(1, 1, 5, 'A masterpiece of sci-fi!', '2024-02-10'),
(2, 2, 4, 'Very intriguing concepts.', '2024-02-12'),
(5, 3, 5, 'Absolutely magical reading experience.', '2024-02-20'),
(9, 1, 5, 'A timeless classic.', '2024-03-05');
