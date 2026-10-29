CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY,
  customer_name TEXT NOT NULL,
  phone TEXT NOT NULL,
  car_model TEXT NOT NULL,
  service TEXT NOT NULL,
  appointment_at TEXT NOT NULL,
  whatsapp_opt_in INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','completed','cancelled')),
  created_at TEXT NOT NULL,
  confirmation_sent_at TEXT,
  appointment_reminder_sent_at TEXT
);
CREATE INDEX IF NOT EXISTS bookings_appointment_idx ON bookings(status, appointment_at);
CREATE INDEX IF NOT EXISTS bookings_phone_idx ON bookings(phone);

CREATE TABLE IF NOT EXISTS service_records (
  id TEXT PRIMARY KEY,
  customer_name TEXT NOT NULL,
  phone TEXT NOT NULL,
  car_model TEXT NOT NULL,
  service TEXT NOT NULL,
  service_date TEXT NOT NULL,
  next_service_date TEXT,
  whatsapp_opt_in INTEGER NOT NULL DEFAULT 0,
  reminder_sent_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS service_due_idx ON service_records(next_service_date, reminder_sent_at);
CREATE INDEX IF NOT EXISTS service_phone_idx ON service_records(phone);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  customer_name TEXT NOT NULL,
  rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
  review_text TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery (
  id TEXT PRIMARY KEY,
  image_url TEXT NOT NULL,
  caption TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  setting_key TEXT PRIMARY KEY,
  setting_value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS message_log (
  id TEXT PRIMARY KEY,
  recipient TEXT NOT NULL,
  message_type TEXT NOT NULL,
  reference_id TEXT NOT NULL,
  status TEXT NOT NULL,
  provider_status INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE(message_type, reference_id)
);
CREATE TABLE IF NOT EXISTS admin_login_attempts (
  id TEXT PRIMARY KEY,
  ip TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_attempts_ip_idx ON admin_login_attempts(ip, created_at);
