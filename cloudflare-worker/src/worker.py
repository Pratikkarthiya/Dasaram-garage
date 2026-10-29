import hashlib
import hmac
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from pyodide.ffi import to_js
from js import Object, Response as JSResponse
from workers import WorkerEntrypoint, fetch

COOKIE = "dg_admin"
SESSION_SECONDS = 60 * 60 * 12
STATUSES = {"pending", "confirmed", "completed", "cancelled"}


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_now():
    return now_utc().isoformat()


def json_response(data, status=200, headers=None):
    base = {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"}
    if headers:
        base.update(headers)
    return JSResponse.new(json.dumps(data, ensure_ascii=False), to_js({"status": status, "headers": base}, dict_converter=Object.fromEntries))


def text_response(body, status=200, content_type="text/plain; charset=utf-8", headers=None):
    base = {"content-type": content_type, "x-content-type-options": "nosniff"}
    if headers:
        base.update(headers)
    return JSResponse.new(body, to_js({"status": status, "headers": base}, dict_converter=Object.fromEntries))


def clean(value, limit=250):
    return str(value or "").strip()[:limit]


def valid_phone(value):
    return bool(re.fullmatch(r"\+?[0-9 ()-]{8,20}", value))


def appointment_label(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return value


def row_dict(row):
    if row is None:
        return None
    try:
        return dict(row)
    except Exception:
        return row.to_py() if hasattr(row, "to_py") else row


def rows_from(result):
    if result is None:
        return []
    try:
        data = result.results
        return [row_dict(item) for item in data]
    except Exception:
        try:
            data = result["results"]
            return [row_dict(item) for item in data]
        except Exception:
            return []


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(request.url)
        path, method = url.path.rstrip("/") or "/", request.method.upper()
        if path == "/api/health":
            try:
                await self.env.DB.prepare("SELECT 1 AS ok").first()
                return json_response({"ok": True})
            except Exception:
                return json_response({"ok": False, "message": "Database is not configured"}, 503)
        try:
            if path == "/api/bookings" and method == "POST":
                return await self.create_booking(request)
            if path == "/api/reviews" and method == "GET":
                return await self.public_reviews()
            if path == "/api/reviews" and method == "POST":
                return await self.create_review(request)
            if path == "/api/gallery" and method == "GET":
                return await self.public_gallery()
            if path == "/api/settings/public" and method == "GET":
                return await self.public_settings()
            if path == "/api/admin/login" and method == "POST":
                return await self.login(request)
            if path == "/api/admin/logout" and method == "POST":
                self.require_admin(request)
                return json_response({"ok": True}, headers={"set-cookie": self.clear_cookie()})
            if path.startswith("/api/admin/"):
                self.require_admin(request)
                return await self.admin_api(request, path, method)
            if path.startswith("/api/"):
                return json_response({"error": "Not found"}, 404)
            return await self.env.ASSETS.fetch(request)
        except PermissionError:
            return json_response({"error": "Sign in required"}, 401)
        except ValueError as error:
            return json_response({"error": str(error)}, 400)
        except Exception:
            return json_response({"error": "Something went wrong. Please try again."}, 500)

    def require_admin(self, request):
        secret = getattr(self.env, "SESSION_SECRET", "")
        cookie_header = request.headers.get("Cookie") or ""
        token = ""
        for part in cookie_header.split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key == COOKIE:
                token = value
                break
        exp, dot, signature = token.partition(".")
        if not secret or not dot or not exp.isdigit() or int(exp) < int(now_utc().timestamp()):
            raise PermissionError()
        expected = hmac.new(secret.encode(), exp.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError()

    def session_cookie(self):
        expiry = str(int(now_utc().timestamp()) + SESSION_SECONDS)
        secret = self.env.SESSION_SECRET
        signature = hmac.new(secret.encode(), expiry.encode(), hashlib.sha256).hexdigest()
        return f"{COOKIE}={expiry}.{signature}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"

    def clear_cookie(self):
        return f"{COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0"

    async def read_json(self, request):
        try:
            data = await request.json()
        except Exception:
            raise ValueError("Please submit a valid form.")
        if not isinstance(data, dict):
            raise ValueError("Please submit a valid form.")
        return data

    async def login(self, request):
        data = await self.read_json(request)
        expected = getattr(self.env, "ADMIN_PASSWORD", "")
        supplied = clean(data.get("password"), 300)
        if len(expected) < 12 or not hmac.compare_digest(supplied, expected):
            return json_response({"error": "Incorrect password."}, 401)
        return json_response({"ok": True}, headers={"set-cookie": self.session_cookie()})

    async def create_booking(self, request):
        data = await self.read_json(request)
        name = clean(data.get("name"), 90)
        phone = clean(data.get("phone"), 25)
        car = clean(data.get("car_model"), 90)
        service = clean(data.get("service"), 120)
        appointment = clean(data.get("appointment_at"), 40)
        consent = bool(data.get("whatsapp_opt_in"))
        if not name or not car or not service or not appointment or not valid_phone(phone):
            raise ValueError("Please fill in all booking details and enter a valid phone number.")
        try:
            parsed = datetime.fromisoformat(appointment.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Choose a valid appointment date and time.")
        if parsed.tzinfo is None:
            raise ValueError("Choose a valid appointment date and time.")
        if parsed <= now_utc() or parsed > now_utc() + timedelta(days=120):
            raise ValueError("Choose a date within the next 120 days.")
        booking_id = secrets.token_hex(12)
        await self.env.DB.prepare("INSERT INTO bookings (id, customer_name, phone, car_model, service, appointment_at, whatsapp_opt_in, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)").bind(booking_id, name, phone, car, service, parsed.isoformat(), 1 if consent else 0, iso_now()).run()
        if consent:
            await self.send_template(phone, "booking_received", [name, service, parsed.strftime("%d %b %Y, %I:%M %p")], booking_id)
        return json_response({"ok": True, "message": "Booking request received. The garage will contact you to confirm the time."}, 201)

    async def public_reviews(self):
        result = await self.env.DB.prepare("SELECT id, customer_name, rating, review_text, created_at FROM reviews WHERE approved = 1 ORDER BY created_at DESC LIMIT 30").all()
        return json_response({"reviews": rows_from(result)})

    async def create_review(self, request):
        data = await self.read_json(request)
        name, body = clean(data.get("name"), 80), clean(data.get("review"), 800)
        try:
            rating = int(data.get("rating"))
        except Exception:
            rating = 0
        if not name or len(body) < 10 or rating not in range(1, 6):
            raise ValueError("Add your name, a rating and a review of at least 10 characters.")
        await self.env.DB.prepare("INSERT INTO reviews (id, customer_name, rating, review_text, approved, created_at) VALUES (?, ?, ?, ?, 0, ?)").bind(secrets.token_hex(12), name, rating, body, iso_now()).run()
        return json_response({"ok": True, "message": "Thanks for your review. It will appear after the garage approves it."}, 201)

    async def public_gallery(self):
        result = await self.env.DB.prepare("SELECT id, image_url, caption FROM gallery ORDER BY created_at DESC LIMIT 24").all()
        return json_response({"photos": rows_from(result)})

    async def public_settings(self):
        result = await self.env.DB.prepare("SELECT setting_key, setting_value FROM settings WHERE setting_key IN ('address','phone','opening_hours','maps_url')").all()
        settings = {item["setting_key"]: item["setting_value"] for item in rows_from(result)}
        return json_response({"settings": settings})

    async def admin_api(self, request, path, method):
        if path == "/api/admin/bookings" and method == "GET":
            result = await self.env.DB.prepare("SELECT * FROM bookings ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, appointment_at DESC LIMIT 300").all()
            return json_response({"bookings": rows_from(result)})
        if path.startswith("/api/admin/bookings/") and method == "PATCH":
            booking_id = path.rsplit("/", 1)[-1]
            data = await self.read_json(request)
            status = clean(data.get("status"), 20)
            if status not in STATUSES:
                raise ValueError("Invalid booking status.")
            booking = await self.env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(booking_id).first()
            if not booking:
                return json_response({"error": "Booking not found."}, 404)
            await self.env.DB.prepare("UPDATE bookings SET status = ? WHERE id = ?").bind(status, booking_id).run()
            if status == "confirmed" and booking["whatsapp_opt_in"]:
                await self.send_template(booking["phone"], "appointment_confirmed", [booking["customer_name"], booking["service"], appointment_label(booking["appointment_at"])], booking_id)
            if status == "completed" and booking["status"] != "completed":
                record_id = secrets.token_hex(12)
                service_date = booking["appointment_at"][:10]
                await self.env.DB.prepare("INSERT INTO service_records (id, customer_name, phone, car_model, service, service_date, whatsapp_opt_in, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ").bind(record_id, booking["customer_name"], booking["phone"], booking["car_model"], booking["service"], service_date, booking["whatsapp_opt_in"], iso_now()).run()
                next_date = clean(data.get("next_service_date"), 10)
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", next_date):
                    await self.env.DB.prepare("UPDATE service_records SET next_service_date = ? WHERE id = ?").bind(next_date, record_id).run()
            return json_response({"ok": True})
        if path == "/api/admin/history" and method == "GET":
            result = await self.env.DB.prepare("SELECT * FROM service_records ORDER BY service_date DESC LIMIT 500").all()
            return json_response({"records": rows_from(result)})
        if path == "/api/admin/history" and method == "POST":
            data = await self.read_json(request)
            name, phone, car = clean(data.get("name"), 90), clean(data.get("phone"), 25), clean(data.get("car_model"), 90)
            service, service_date = clean(data.get("service"), 120), clean(data.get("service_date"), 10)
            next_date = clean(data.get("next_service_date"), 10) or None
            if not all([name, car, service]) or not valid_phone(phone) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", service_date):
                raise ValueError("Complete all customer and service details.")
            consent = 1 if data.get("whatsapp_opt_in") else 0
            await self.env.DB.prepare("INSERT INTO service_records (id, customer_name, phone, car_model, service, service_date, next_service_date, whatsapp_opt_in, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind(secrets.token_hex(12), name, phone, car, service, service_date, next_date, consent, clean(data.get("notes"), 500), iso_now()).run()
            return json_response({"ok": True}, 201)
        if path == "/api/admin/reviews" and method == "GET":
            result = await self.env.DB.prepare("SELECT * FROM reviews ORDER BY approved ASC, created_at DESC").all()
            return json_response({"reviews": rows_from(result)})
        if path.startswith("/api/admin/reviews/") and method == "PATCH":
            review_id = path.rsplit("/", 1)[-1]
            data = await self.read_json(request)
            approved = 1 if data.get("approved") else 0
            await self.env.DB.prepare("UPDATE reviews SET approved = ? WHERE id = ?").bind(approved, review_id).run()
            return json_response({"ok": True})
        if path == "/api/admin/gallery" and method == "POST":
            data = await self.read_json(request)
            image_url, caption = clean(data.get("image_url"), 1000), clean(data.get("caption"), 120)
            parsed = urlparse(image_url)
            if parsed.scheme != "https" or not parsed.netloc or not caption:
                raise ValueError("Use an HTTPS image link and add a short caption.")
            await self.env.DB.prepare("INSERT INTO gallery (id, image_url, caption, created_at) VALUES (?, ?, ?, ?)").bind(secrets.token_hex(12), image_url, caption, iso_now()).run()
            return json_response({"ok": True}, 201)
        if path.startswith("/api/admin/gallery/") and method == "DELETE":
            await self.env.DB.prepare("DELETE FROM gallery WHERE id = ?").bind(path.rsplit("/", 1)[-1]).run()
            return json_response({"ok": True})
        if path == "/api/admin/settings" and method == "GET":
            result = await self.env.DB.prepare("SELECT setting_key, setting_value FROM settings").all()
            return json_response({"settings": {item["setting_key"]: item["setting_value"] for item in rows_from(result)}})
        if path == "/api/admin/settings" and method == "PUT":
            data = await self.read_json(request)
            allowed = {"address": 250, "phone": 30, "opening_hours": 120, "maps_url": 1000}
            for key, limit in allowed.items():
                value = clean(data.get(key), limit)
                await self.env.DB.prepare("INSERT INTO settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value").bind(key, value).run()
            return json_response({"ok": True})
        return json_response({"error": "Not found"}, 404)

    async def send_template(self, phone, template_key, values, reference_id):
        token = getattr(self.env, "WHATSAPP_TOKEN", "")
        phone_id = getattr(self.env, "WHATSAPP_PHONE_NUMBER_ID", "")
        api_version = getattr(self.env, "WHATSAPP_API_VERSION", "")
        template_language = getattr(self.env, "WHATSAPP_TEMPLATE_LANGUAGE", "en")
        template_name = getattr(self.env, "WA_TEMPLATE_" + template_key.upper(), "")
        if not (token and phone_id and re.fullmatch(r"v\d+\.\d+", api_version) and template_name):
            return False
        normalized = re.sub(r"\D", "", phone)
        if len(normalized) == 10:
            normalized = "91" + normalized
        elif len(normalized) == 11 and normalized.startswith("0"):
            normalized = "91" + normalized[1:]
        params = [{"type": "text", "text": str(value)} for value in values]
        payload = {"messaging_product": "whatsapp", "to": normalized, "type": "template", "template": {"name": template_name, "language": {"code": template_language}, "components": [{"type": "body", "parameters": params}]}}
        try:
            response = await fetch(f"https://graph.facebook.com/{api_version}/{phone_id}/messages", to_js({"method": "POST", "headers": {"Authorization": "Bearer " + token, "Content-Type": "application/json"}, "body": json.dumps(payload)}, dict_converter=__import__("js").Object.fromEntries))
            status = int(response.status)
            await self.env.DB.prepare("INSERT INTO message_log (id, recipient, message_type, reference_id, status, provider_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(message_type, reference_id) DO UPDATE SET status=excluded.status, provider_status=excluded.provider_status, created_at=excluded.created_at").bind(secrets.token_hex(12), normalized, template_key, reference_id, "sent" if response.ok else "failed", status, iso_now()).run()
            return bool(response.ok)
        except Exception:
            return False

    async def scheduled(self, controller, env, ctx):
        now = now_utc()
        soon = (now + timedelta(hours=24)).isoformat()
        later = (now + timedelta(hours=25)).isoformat()
        due_bookings = await env.DB.prepare("SELECT * FROM bookings WHERE status='confirmed' AND whatsapp_opt_in=1 AND appointment_reminder_sent_at IS NULL AND julianday(appointment_at) >= julianday(?) AND julianday(appointment_at) < julianday(?) LIMIT 50").bind(soon, later).all()
        for booking in rows_from(due_bookings):
            sent = await self.send_template(booking["phone"], "appointment_reminder", [booking["customer_name"], booking["service"], appointment_label(booking["appointment_at"])], booking["id"])
            if sent:
                await env.DB.prepare("UPDATE bookings SET appointment_reminder_sent_at = ? WHERE id = ? AND appointment_reminder_sent_at IS NULL").bind(iso_now(), booking["id"]).run()
        today = now.date()
        due_service = await env.DB.prepare("SELECT * FROM service_records WHERE whatsapp_opt_in=1 AND next_service_date IS NOT NULL AND next_service_date <= ? AND reminder_sent_at IS NULL LIMIT 50").bind((today + timedelta(days=7)).isoformat()).all()
        for record in rows_from(due_service):
            sent = await self.send_template(record["phone"], "service_due_reminder", [record["customer_name"], record["car_model"], record["next_service_date"]], record["id"])
            if sent:
                await env.DB.prepare("UPDATE service_records SET reminder_sent_at = ? WHERE id = ? AND reminder_sent_at IS NULL").bind(iso_now(), record["id"]).run()
