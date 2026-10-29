# Dasaram Garage — Python booking app

This is the Python backend and static website for the requested garage features. It uses a Cloudflare Python Worker, D1 database, Static Assets, and a 15-minute Cron Trigger. Cloudflare Pages alone only serves the static site; deploy this folder as a **Worker** to run the Python API and reminders.

## Included

- Customer appointment requests with name, phone, car, service, date/time, and WhatsApp consent.
- Admin sign-in, booking queue, and appointment status updates.
- Completing a booking adds a service-history record. Admins can also add records directly and set the next service date.
- WhatsApp message hooks for booking receipt, appointment confirmation, 24-hour appointment reminder, and service-due reminders (7 days before or overdue).
- Address, phone, opening hours, and Google Maps link managed by the admin.
- Customer reviews with admin moderation.
- Garage photo gallery managed with public HTTPS image URLs.
- Admin password is a Cloudflare secret; sessions are signed, HTTP-only, secure, and expire after 12 hours. Failed login attempts are throttled per IP.

## One-time setup

Requirements: Node.js/npm, Python 3.12+, and `uv`.

1. In Cloudflare, create a D1 database named `dasaram-garage-db`, or run `npx wrangler d1 create dasaram-garage-db` after `npx wrangler login`.
2. Copy the returned database ID into `d1_databases[0].database_id` in `wrangler.jsonc`, replacing `REPLACE_WITH_D1_DATABASE_ID`.
3. From this folder, run `npx wrangler d1 migrations apply dasaram-garage-db --remote` to create the tables.
4. Set a strong admin password and a random session-signing secret. Do not commit these values:

   ```sh
   npx wrangler secret put ADMIN_PASSWORD
   npx wrangler secret put SESSION_SECRET
   ```

   `ADMIN_PASSWORD` must contain at least 12 characters. Generate a session secret locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and enter it at the Wrangler prompt.

5. Deploy the Worker and static files:

   ```sh
   uv run pywrangler deploy
   ```

6. Open the Worker URL and use **Garage admin** to set the address, contact number, hours, and Maps link.

## Connect GitHub for automatic Worker deploys

The existing Cloudflare Pages project does not execute Python. In **Workers & Pages**, create a Worker connected to `Pratikkarthiya/Dasaram-garage`, set the root directory to `cloudflare-worker`, and use `uv run pywrangler deploy` as the deploy command. Configure the D1 binding and database ID in the Worker's settings or `wrangler.jsonc`, and add the secrets above in the Worker settings. Name the Worker `dasaram-garage-python` to match `wrangler.jsonc`. Cloudflare Workers Builds can deploy a Worker automatically on Git pushes.

## WhatsApp setup

WhatsApp reminders are intentionally inactive until the garage configures WhatsApp Business Platform credentials and message templates. Add these in Cloudflare Worker settings (never in Git):

- `WHATSAPP_TOKEN` — secret access token
- `WHATSAPP_PHONE_NUMBER_ID` — phone number ID from the WhatsApp Business account
- `WHATSAPP_API_VERSION` — current Graph API version, for example `vXX.0`
- `WA_TEMPLATE_BOOKING_RECEIVED` — approved template name with 3 body variables
- `WA_TEMPLATE_APPOINTMENT_CONFIRMED` — approved template name with 3 body variables
- `WA_TEMPLATE_APPOINTMENT_REMINDER` — approved template name with 3 body variables
- `WA_TEMPLATE_SERVICE_DUE_REMINDER` — approved template name with 3 body variables

Create and get approval for matching utility templates in WhatsApp Manager. Suggested body variable order:

- Booking received: customer name, requested service, requested date and time.
- Appointment confirmed/reminder: customer name, service, appointment date and time.
- Service due reminder: customer name, car model, next service date.

The booking form includes a separate WhatsApp opt-in checkbox. The system only sends reminders to customers who opted in. The Cloudflare Cron Trigger runs every 15 minutes; appointment reminders are sent about 24 hours before, and service reminders are sent once when due within 7 days (or overdue).

## Photos and reviews

Admins add photos using a public HTTPS image URL and caption. Customer reviews are held for approval before they appear on the site. Do not publish customer images or reviews without permission.

## Important

This project contains no real garage address, phone, opening hours, WhatsApp token, or template names. Configure those in the dashboard before using it with customers. Customer records are stored in D1; keep account access limited to the garage owner and retain records only as needed.
