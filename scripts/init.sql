CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS notes (
    id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title   TEXT NOT NULL,
    body    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name     TEXT NOT NULL,
    category TEXT NOT NULL,
    price    NUMERIC(10, 2) NOT NULL
);
