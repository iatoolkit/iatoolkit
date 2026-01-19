-- Borrar en orden inverso de dependencias
DROP TABLE IF EXISTS employee_territories;
DROP TABLE IF EXISTS territories;
DROP TABLE IF EXISTS regions;
DROP TABLE IF EXISTS order_details;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS shippers;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS suppliers;
DROP TABLE IF EXISTS categories;

-- Categories
CREATE TABLE categories
(
    categoryid   INTEGER PRIMARY KEY,
    categoryname VARCHAR(100) NOT NULL,
    description  TEXT
);

-- Suppliers
CREATE TABLE suppliers
(
    supplierid  INTEGER PRIMARY KEY,
    companyname VARCHAR(255) NOT NULL,
    contactname VARCHAR(255),
    country     VARCHAR(100),
    city        VARCHAR(100),
    phone       VARCHAR(50),
    address     VARCHAR(255)
);

-- Products
CREATE TABLE products
(
    productid       INTEGER PRIMARY KEY,
    productname     VARCHAR(255) NOT NULL,
    supplierid      INTEGER,
    categoryid      INTEGER,
    quantityperunit VARCHAR(100),
    unitprice       REAL         NOT NULL,
    unitsinstock    INTEGER,
    unitsonorder    INTEGER,
    reorderlevel    INTEGER,
    discontinued    INTEGER DEFAULT 0,
    FOREIGN KEY (supplierid) REFERENCES suppliers (supplierid),
    FOREIGN KEY (categoryid) REFERENCES categories (categoryid)
);

-- Customers
CREATE TABLE customers
(
    customerid   VARCHAR(10) PRIMARY KEY,
    companyname  VARCHAR(255) NOT NULL,
    contactname  VARCHAR(255),
    contacttitle VARCHAR(100),
    address      VARCHAR(255),
    city         VARCHAR(100),
    region       VARCHAR(50),
    postalcode   VARCHAR(20),
    country      VARCHAR(100),
    phone        VARCHAR(50)
);

-- Employees
CREATE TABLE employees
(
    employeeid INTEGER PRIMARY KEY,
    lastname   VARCHAR(100),
    firstname  VARCHAR(100),
    title      VARCHAR(100),
    birthdate  DATE,
    hiredate   DATE,
    city       VARCHAR(100),
    country    VARCHAR(100),
    reportsto  INTEGER,
    FOREIGN KEY (reportsto) REFERENCES employees (employeeid)
);

-- Shippers
CREATE TABLE shippers
(
    shipperid   INTEGER PRIMARY KEY,
    companyname VARCHAR(255),
    phone       VARCHAR(50)
);

-- Orders
CREATE TABLE orders
(
    orderid        INTEGER PRIMARY KEY,
    customerid     VARCHAR(10) NOT NULL,
    employeeid     INTEGER     NOT NULL,
    orderdate      DATE,
    requireddate   DATE,
    shippeddate    DATE,
    shipvia        INTEGER,
    freight        REAL,
    shipname       VARCHAR(255),
    shipaddress    VARCHAR(255),
    shipcity       VARCHAR(100),
    shipregion     VARCHAR(50),
    shippostalcode VARCHAR(20),
    shipcountry    VARCHAR(100),
    FOREIGN KEY (customerid) REFERENCES customers (customerid),
    FOREIGN KEY (employeeid) REFERENCES employees (employeeid),
    FOREIGN KEY (shipvia) REFERENCES shippers (shipperid)
);

-- OrderDetails
CREATE TABLE order_details
(
    orderid   INTEGER NOT NULL,
    productid INTEGER NOT NULL,
    unitprice REAL    NOT NULL,
    quantity  INTEGER NOT NULL,
    discount  REAL,
    PRIMARY KEY (orderid, productid),
    FOREIGN KEY (orderid) REFERENCES orders (orderid),
    FOREIGN KEY (productid) REFERENCES products (productid)
);

-- Regions
CREATE TABLE regions
(
    regionid          INTEGER PRIMARY KEY,
    regiondescription VARCHAR(100) NOT NULL
);

-- Territories
CREATE TABLE territories
(
    territoryid          INTEGER PRIMARY KEY,
    territorydescription VARCHAR(100),
    regionid             INTEGER,
    FOREIGN KEY (regionid) REFERENCES regions (regionid)
);

-- EmployeeTerritories
CREATE TABLE employee_territories
(
    employeeid  INTEGER NOT NULL,
    territoryid INTEGER NOT NULL,
    PRIMARY KEY (employeeid, territoryid),
    FOREIGN KEY (employeeid) REFERENCES employees (employeeid),
    FOREIGN KEY (territoryid) REFERENCES territories (territoryid)
);