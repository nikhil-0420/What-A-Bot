-- migrations/002_multi_business.sql
-- Additive only. Does not touch 001_init.sql's tables/rows. Apply once, after
-- reviewing against the actual current schema.

ALTER TABLE businesses ADD COLUMN IF NOT EXISTS business_type TEXT NOT NULL DEFAULT 'retail'
    CHECK (business_type IN ('retail', 'service'));

ALTER TABLE inbox ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT;
ALTER TABLE inbox ADD COLUMN IF NOT EXISTS telegram_update_id BIGINT;
ALTER TABLE inbox ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;
-- Fixes known issue #1: input_id becomes 'tg:<bot_id>:<update_id>' (globally
-- unique, not chat-scoped message_id). Store chat/message id separately for tracing.

CREATE TABLE IF NOT EXISTS owners (
    owner_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS owner_business_memberships (
    owner_id UUID NOT NULL REFERENCES owners(owner_id),
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    PRIMARY KEY (owner_id, business_id)
);

CREATE TABLE IF NOT EXISTS bot_link_tokens (
    token TEXT PRIMARY KEY,
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    owner_id UUID NOT NULL REFERENCES owners(owner_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_by_chat_id BIGINT
);
-- Single-use: consumed_at IS NULL is the only usable state. Enforce in code
-- via UPDATE ... WHERE consumed_at IS NULL RETURNING token (CAS pattern,
-- same style as order confirmation).

CREATE TABLE IF NOT EXISTS services (
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    service_id TEXT NOT NULL,
    name TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    price_paise INTEGER NOT NULL CHECK (price_paise > 0),
    PRIMARY KEY (business_id, service_id)
);

CREATE TABLE IF NOT EXISTS service_slots (
    slot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    FOREIGN KEY (business_id, service_id) REFERENCES services(business_id, service_id)
);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    origin_input_id TEXT UNIQUE NOT NULL REFERENCES inbox(input_id),
    session_id UUID NOT NULL REFERENCES sessions(session_id),
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    slot_id UUID NOT NULL REFERENCES service_slots(slot_id),
    status TEXT NOT NULL CHECK (status IN ('draft', 'held', 'confirmed', 'cancelled')),
    total_paise INTEGER NOT NULL CHECK (total_paise >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id TEXT NOT NULL REFERENCES businesses(business_id),
    dodo_event_id TEXT UNIQUE NOT NULL,   -- dedup key
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS business_plan (
    business_id TEXT PRIMARY KEY REFERENCES businesses(business_id),
    plan TEXT NOT NULL DEFAULT 'trial' CHECK (plan IN ('trial', 'test_paid')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed data:
INSERT INTO businesses (business_id, name, review_above_paise, faq, business_type) VALUES
    ('demo-stationery-1', 'Sharma Stationery', 100000, '{}', 'retail'),
    ('demo-supermarket-1', 'Daily Fresh Supermarket', 150000, '{}', 'retail'),
    ('demo-services-1', 'UrbanFix Home Services', 200000, '{}', 'service')
ON CONFLICT (business_id) DO NOTHING;

INSERT INTO catalog (business_id, sku, name, brand, ruling, size, unit_price_paise, qty) VALUES
    ('demo-stationery-1', 'A', 'Classic Ruled A5',   'Classmate', 'ruled',   'A5', 4000, 50),
    ('demo-stationery-1', 'B', 'Premium Ruled A5',   'Navneet',   'ruled',   'A5', 5000, 40),
    ('demo-stationery-1', 'C', 'Deluxe Ruled A5',    'Sundaram',  'ruled',   'A5', 6000, 50),
    ('demo-stationery-1', 'D', 'Basic Unruled A5',   'Classmate', 'unruled', 'A5', 2500, 30),
    ('demo-supermarket-1', 'S1', 'Milk 1L',          'Amul',      'unruled', 'A5', 6000, 20),
    ('demo-supermarket-1', 'S2', 'Bread 400g',       'Britannia', 'unruled', 'A5', 4500, 15),
    ('demo-supermarket-1', 'S3', 'Eggs 6pk',         'FarmFresh', 'unruled', 'A5', 5500, 30),
    ('demo-supermarket-1', 'S4', 'Butter 100g',      'Amul',      'unruled', 'A5', 5800, 25)
ON CONFLICT (business_id, sku) DO NOTHING;

INSERT INTO services (business_id, service_id, name, duration_minutes, price_paise) VALUES
    ('demo-services-1', 'srv-ac-repair', 'AC Repair & Service', 60, 49900),
    ('demo-services-1', 'srv-plumbing', 'Plumbing Inspection & Fix', 45, 29900),
    ('demo-services-1', 'srv-electric', 'Electrical Wiring & Repair', 45, 34900)
ON CONFLICT (business_id, service_id) DO NOTHING;

-- Seed owners (hash of 'password123' using pbkdf2 sha256 or simple salt)
-- We use sha256: 'ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f' for 'password123'
INSERT INTO owners (owner_id, email, password_hash) VALUES
    ('00000000-0000-0000-0000-000000000001', 'owner@demo.com', 'ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f'),
    ('00000000-0000-0000-0000-000000000002', 'restricted@demo.com', 'ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f')
ON CONFLICT (email) DO NOTHING;

INSERT INTO owner_business_memberships (owner_id, business_id) VALUES
    ('00000000-0000-0000-0000-000000000001', 'demo-stationery-1'),
    ('00000000-0000-0000-0000-000000000001', 'demo-supermarket-1'),
    ('00000000-0000-0000-0000-000000000001', 'demo-services-1'),
    ('00000000-0000-0000-0000-000000000001', 'test_shop'),
    ('00000000-0000-0000-0000-000000000002', 'demo-stationery-1')
ON CONFLICT (owner_id, business_id) DO NOTHING;

