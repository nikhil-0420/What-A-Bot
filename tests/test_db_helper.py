import contextlib
import re
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta


class FakePostgresConn:
    def __init__(self, db_path=":memory:"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.isolation_level = None  # Autocommit mode, manual savepoints
        self._init_schema()

    def execute(self, sql: str, params=()):
        s = sql
        # Replace %s with ?
        s = re.sub(r"%s", "?", s)
        # Remove PostgreSQL specific clauses
        s = re.sub(r"\bFOR UPDATE\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"::text", "", s)
        s = re.sub(r"::jsonb", "", s)
        # Replace interval expressions
        s = re.sub(
            r"now\(\)\s*\+\s*interval\s*'[^']*'",
            f"'{(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}'",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(
            r"now\(\)",
            f"'{datetime.now(timezone.utc).isoformat()}'",
            s,
            flags=re.IGNORECASE,
        )

        cur = self.conn.cursor()
        cur.execute(s, tuple(params))
        return cur

    @contextlib.contextmanager
    def transaction(self):
        sp_name = f"sp_{uuid.uuid4().hex[:8]}"
        self.conn.execute(f"SAVEPOINT {sp_name}")
        try:
            yield self
            self.conn.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            self.conn.execute(f"RELEASE SAVEPOINT {sp_name}")
            raise

    def commit(self):
        pass

    def rollback(self):
        pass

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS businesses (
                business_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                business_type TEXT NOT NULL DEFAULT 'retail',
                review_above_paise INTEGER NOT NULL DEFAULT 100000,
                faq TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS catalog (
                business_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                name TEXT NOT NULL,
                brand TEXT NOT NULL,
                ruling TEXT,
                size TEXT,
                unit_price_paise INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                updated_at TEXT,
                PRIMARY KEY (business_id, sku)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                customer_phone TEXT NOT NULL,
                destination TEXT NOT NULL,
                active_business_id TEXT
            );

            CREATE TABLE IF NOT EXISTS inbox (
                input_id TEXT PRIMARY KEY,
                sequence INTEGER,
                source TEXT NOT NULL,
                session_id TEXT,
                business_id TEXT,
                body TEXT,
                status TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                quote_code TEXT UNIQUE NOT NULL,
                origin_input_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL,
                business_id TEXT NOT NULL,
                status TEXT NOT NULL,
                constraints TEXT NOT NULL,
                items TEXT NOT NULL,
                total_paise INTEGER NOT NULL,
                expires_at TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS invoices (
                order_id TEXT PRIMARY KEY,
                invoice_id TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS message_outcomes (
                input_id TEXT PRIMARY KEY,
                order_id TEXT,
                kind TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS outbox (
                outbox_id TEXT PRIMARY KEY,
                event_key TEXT UNIQUE NOT NULL,
                input_id TEXT,
                session_id TEXT,
                business_id TEXT,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                attempt_no INTEGER DEFAULT 0,
                twilio_sid TEXT,
                delivery_status TEXT,
                next_attempt_at TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                input_id TEXT,
                kind TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS services (
                business_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                price_paise INTEGER NOT NULL,
                PRIMARY KEY (business_id, service_id)
            );

            CREATE TABLE IF NOT EXISTS service_slots (
                slot_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                capacity INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bookings (
                booking_id TEXT PRIMARY KEY,
                origin_input_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL,
                business_id TEXT NOT NULL,
                slot_id TEXT NOT NULL,
                status TEXT NOT NULL,
                total_paise INTEGER NOT NULL,
                created_at TEXT
            );
            """
        )

        # Seed test data
        self.seed_defaults()

    def seed_defaults(self):
        # Businesses
        self.conn.execute(
            """
            INSERT OR REPLACE INTO businesses (business_id, name, business_type, review_above_paise)
            VALUES ('demo-stationery-1', 'Sharma Stationery', 'retail', 100000)
            """
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO businesses (business_id, name, business_type, review_above_paise)
            VALUES ('demo-supermarket-1', 'Fresh Supermarket', 'retail', 100000)
            """
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO businesses (business_id, name, business_type, review_above_paise)
            VALUES ('demo-services-1', 'UrbanFix Services', 'service', 100000)
            """
        )

        # Stationery catalog items (Section I fixture)
        stationery_items = [
            ("demo-stationery-1", "A", "Classic Ruled A5", "Classmate", "ruled", "A5", 4000, 5),
            ("demo-stationery-1", "B", "Premium Ruled A5", "Navneet", "ruled", "A5", 5000, 4),
            ("demo-stationery-1", "C", "Deluxe Ruled A5", "Sundaram", "ruled", "A5", 6000, 5),
            ("demo-stationery-1", "D", "Basic Unruled A5", "Classmate", "unruled", "A5", 2500, 30),
        ]
        for it in stationery_items:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO catalog (business_id, sku, name, brand, ruling, size, unit_price_paise, qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                it,
            )

        # Supermarket catalog items
        supermarket_items = [
            ("demo-supermarket-1", "M1", "Milk 1L", "Amul", "unruled", "A5", 6000, 20),
            ("demo-supermarket-1", "M2", "Bread 400g", "Modern", "unruled", "A5", 4500, 15),
            ("demo-supermarket-1", "M3", "Eggs 6pk", "FarmFresh", "unruled", "A5", 5000, 10),
            ("demo-supermarket-1", "M4", "Butter 100g", "Amul", "unruled", "A5", 5500, 12),
            ("demo-supermarket-1", "M5", "Cheese 200g", "Britannia", "unruled", "A5", 12000, 8),
            ("demo-supermarket-1", "M6", "Atta 5kg", "Aashirvaad", "unruled", "A5", 24000, 10),
        ]
        for it in supermarket_items:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO catalog (business_id, sku, name, brand, ruling, size, unit_price_paise, qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                it,
            )

        # Services & slots
        self.conn.execute(
            """
            INSERT OR REPLACE INTO services (business_id, service_id, name, duration_minutes, price_paise)
            VALUES ('demo-services-1', 'srv_ac_repair', 'AC Repair Service', 60, 50000)
            """
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO service_slots (slot_id, business_id, service_id, starts_at, capacity)
            VALUES ('slot_10am', 'demo-services-1', 'srv_ac_repair', '2026-09-28T10:00:00Z', 1)
            """
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO service_slots (slot_id, business_id, service_id, starts_at, capacity)
            VALUES ('slot_2pm', 'demo-services-1', 'srv_ac_repair', '2026-09-28T14:00:00Z', 2)
            """
        )
