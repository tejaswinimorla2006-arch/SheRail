# SheRail API

FastAPI service for account registration, JWT sign-in, user profiles, emergency contacts, and transport journeys. PostgreSQL is the source of truth; the mobile app stores only its access token in Expo SecureStore.

## Configure and run

1. Install PostgreSQL and create an application database using your normal secret-management process.
2. From `backend`, copy `.env.example` to `.env`. Set `DATABASE_URL` to a `postgresql+asyncpg://` URL and set `JWT_SECRET_KEY` to a randomly generated secret of at least 32 characters. Keep `.env` private; it is ignored by Git.
3. Create and activate a Python virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Apply all schema migrations and start the API:

   ```powershell
   alembic upgrade head
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Copy the repository-root `.env.example` to `.env` and set `EXPO_PUBLIC_API_URL` to the API's reachable `/api/v1` address. For a physical device, use a reachable development host; use HTTPS for deployed environments. Expo embeds this URL in the client bundle, so it must never contain credentials or secrets.
6. To send real SMS alerts, configure `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` in the backend environment. Set `PUBLIC_API_BASE_URL` to the publicly reachable HTTPS origin of this API (without `/api/v1`) so Twilio can report delivery status. Configure the Twilio sender and account for the destinations you intend to contact. Without valid SMS configuration, alerts are still recorded but their delivery state is reported as `unconfigured`—the API never reports a simulated send as successful.
7. Copy the repository-root `.env.example` and set `EXPO_PUBLIC_ADMIN_URL` to the deployed HTTPS admin dashboard URL. This is a public link, not a credential. For local Vite development, add `http://localhost:5173` to `CORS_ORIGINS` in the backend environment.

After installing or changing native Expo modules/plugins (including SecureStore, ImagePicker, or Notifications), rebuild existing custom development clients so their native code and permissions are current. Remote push requires an EAS development or production build with APNs/FCM credentials; Expo Go does not provide Android remote push.

Interactive API documentation is available at `/docs` while the server is running.

## Safety buddies and safety map

- Safety Buddy invitations are persisted for existing SheRail accounts and appear in the recipient's authenticated app; there is no simulated email delivery. Accepting an invitation does not grant location access.
- The journey owner must separately share each active, GPS-recording journey with an accepted buddy. Shared live location is read-only. Revoking a grant, unlinking a buddy, ending a journey, or revoking GPS recording removes access; SOS, missed-check-in, confirmed anomaly, and journey-state alerts are stored for the buddy and sent over the existing journey WebSocket when connected.
- Nearby assistance searches query live OpenStreetMap/Overpass data for police, hospitals, clinics, and mapped assistance points. The mobile app explains the location transfer and the API requires explicit `location_consent`; SheRail does not store nearby-search coordinates. Results may be empty or unavailable when OpenStreetMap has no mapped result or its service is down. The map attributes OpenStreetMap contributors.
- Community safety reports are private and pending by default. Only active accounts with the database `admin` role can access the review queue, moderate reports, or retrieve original report images. A user cannot obtain this role by changing an email address; bootstrap an administrator through the documented trusted database procedure. Only verified reports are returned to the public map. Moderation is not a claim of law-enforcement verification.
- To submit reports, run `alembic upgrade head`. The mobile Google Maps provider key is optional for Expo Go and iOS Apple Maps; Android standalone builds require a restricted Google Maps API key provided through the root `GOOGLE_MAPS_API_KEY` environment variable. `app.config.js` passes it through the Maps config plugin without checking a key into source control. Rebuild the native app after changing this key.

## Community reports, administration, railway assistance, and notifications

- Community report photos are stored in PostgreSQL, limited to four JPEG, PNG, or WebP images per report and 5 MB per image (12 MB aggregate). Original media is only returned to the report owner or an administrator; verified assistance points and verified community reports are managed by administrators, and no sample records are seeded.
- Reports in the same category within 100 meters and 24 hours are linked as possible duplicates. Moderators can review/reclassify reports and add a note. Verification is a SheRail moderation decision, not a claim of law-enforcement verification.
- The separate `admin/` React/Vite app uses the authenticated `/api/v1/admin` APIs; the backend enforces the database `users.role` and active-account state on every request. To bootstrap the first administrator, register the intended account, verify its identity through your normal out-of-band process, then promote that account using a trusted PostgreSQL administrative connection:

  ```sql
  UPDATE users SET role = 'admin'
  WHERE email = lower('verified-admin@example.com') AND is_active = TRUE;
  ```

  Confirm that exactly one intended row was updated before closing the database session. The dashboard cannot grant its own role. Start the dashboard from `admin/` with `npm install` and `npm run dev`; set `VITE_API_URL` to the API's reachable `/api/v1` URL. Deploy it behind HTTPS and restrict access through your normal hosting controls.
- Railway assistance is optional and has no built-in/example records. Administrators may populate the directory with current, verified information; keep contact and operating details up to date.
- In-app notifications are persisted in PostgreSQL. Push registration is opt-in in the mobile Notifications screen; the worker submits real Expo Push Service requests, checks receipts after 15 minutes, disables device tokens reported as unregistered, and records accepted/failed/no-device/unknown status. `receipt_ok` means APNs/FCM accepted the message, not that a device received or displayed it. Missing receipts are retried for up to 23 hours. Configure APNs/FCM credentials in the EAS project and use a development or production build for remote push; no push is simulated.

## API

- `POST /api/v1/auth/register` — create an account and return a bearer token.
- `POST /api/v1/auth/login` — authenticate with email and password.
- `GET /api/v1/users/me` — read the authenticated profile.
- `PATCH /api/v1/users/me` — update name and/or email.
- `GET|POST /api/v1/users/me/emergency-contacts` — list or add contacts.
- `PATCH|DELETE /api/v1/users/me/emergency-contacts/{contact_id}` — update or delete an owned contact.
- `POST|GET /api/v1/journeys` — create and list the authenticated user's walking, bus, train, metro, or cab journeys.
- `GET /api/v1/journeys/{journey_id}` — read an owned journey with its route points, timestamps, events, and sharing grants.
- `POST /api/v1/journeys/{journey_id}/start|pause|resume|end` — manage journey lifecycle; ending a planned journey cancels it. Starting or resuming requires explicit location consent.
- `PATCH /api/v1/journeys/{journey_id}/tracking` — grant or revoke GPS recording consent during an active journey.
- `POST|GET|DELETE /api/v1/journeys/{journey_id}/shares` — grant selected SheRail accounts access to live journey location or revoke access.
- `GET /api/v1/journeys/shared-with-me` — list active journeys shared with the authenticated user.
- `GET /api/v1/journeys/shared-with-me/{journey_id}` — read the latest location of an active journey shared with the authenticated user.
- `WS /api/v1/ws/journeys/{journey_id}` — authenticated live location stream. Send `{ "type": "authenticate", "access_token": "...", "tracking_consent": true }` after connecting. Only the journey owner may send `{ "type": "location", "latitude": ..., "longitude": ..., "accuracy_m": ..., "captured_at": "..." }`; recipients are read-only and must have an active share grant.
- `PATCH /api/v1/journeys/{journey_id}/safety` — configure check-in interval/grace and GPS safety thresholds with explicit monitoring consent.
- `PUT /api/v1/journeys/{journey_id}/expected-route` — save the owner's private expected-route waypoints.
- `POST /api/v1/journeys/{journey_id}/check-in` — confirm the user is safe and reset the next check-in deadline.
- `GET /api/v1/safety/events` — list pending confirmation prompts, scoped to the signed-in user.
- `POST /api/v1/safety/events/{event_id}/confirm|dismiss` — escalate a confirmed route-deviation/long-stop event to registered contacts, or dismiss it without contacting them.
- `POST /api/v1/safety/alerts/sos` — create an SOS and queue SMS to registered emergency contacts. Location fields are accepted only with explicit `share_location: true`.
- `GET /api/v1/safety/alerts[/{alert_id}]` — read owned alert and per-contact provider statuses.
- `POST /api/v1/safety/alerts/{alert_id}/cancel` — cancel a false alarm and queue correction SMS messages for contacts that may have received it.
- `POST /api/v1/safety/alerts/{alert_id}/retry` — manually retry failed/uncertain deliveries; an uncertain provider outcome may result in a duplicate message.
- `POST /api/v1/webhooks/twilio/sms-status` — provider callback; requests are authenticated with Twilio's signature.
- `GET /api/v1/safety-buddies` — list sent, received, and accepted trusted-user invitations.
- `POST /api/v1/safety-buddies/invitations` and `POST /api/v1/safety-buddies/invitations/{link_id}/respond` — invite an existing account and accept or decline.
- `DELETE /api/v1/safety-buddies/{link_id}` — unlink a buddy and revoke both users' journey grants to one another.
- `POST|DELETE /api/v1/safety-buddies/{buddy_user_id}/journeys/{journey_id}` — grant or revoke a consented per-journey buddy share.
- `GET /api/v1/safety-buddies/alerts` and `POST /api/v1/safety-buddies/alerts/{alert_id}/read` — read and acknowledge persisted alerts delivered for shared journeys.
- `POST /api/v1/map/nearby` — consented live nearby assistance search via OpenStreetMap/Overpass.
- `POST /api/v1/map/reports/search` — search nearby moderator-verified community reports.
- `POST /api/v1/map/reports` — submit a consented report without attachments; pending reports are not included in map searches.
- `GET /api/v1/map/moderation/access`, `GET /api/v1/map/moderation/reports`, and `PATCH /api/v1/map/moderation/reports/{report_id}` — admin-role access, review queue, and verification/rejection.
- `POST /api/v1/map/reports/submit` — multipart report submission with optional image files; `GET /api/v1/map/reports/mine` and `/api/v1/map/reports/{report_id}/images/{image_id}` — owner's report history and authorized image retrieval.
- `/api/v1/admin/overview`, `/users`, `/sos-alerts`, `/community-reports`, `/assistance-points`, and `/railway-assistance` — role-protected dashboard data and management.
- `GET /api/v1/railway-assistance` — authenticated optional railway directory.
- `GET /api/v1/notifications`, `/unread-count`, and read endpoints; `GET|POST /api/v1/notifications/devices`, `DELETE /api/v1/notifications/devices`, and `POST /api/v1/notifications/devices/revoke-all` — persistent inbox and opt-in Expo push-device registration.

Safety check-in reminders are scheduled locally on the phone after the user grants notification permission; the API worker independently enforces the deadline and grace period and creates an SMS escalation. Route deviation compares consented GPS fixes with the user-drawn expected route. Long-stop and route-deviation events first create a pending prompt; only an explicit confirmation escalates them. GPS anomaly checks ignore fixes with reported accuracy worse than 100 meters.

The API runs persisted PostgreSQL-backed monitoring and delivery workers every 10 seconds. Due checks, SMS delivery records, in-app notifications, push tickets, and push receipt polling survive API restarts; PostgreSQL row locks prevent concurrent workers from handling the same item. SMS delivery is asynchronous. SMS status is `pending`, `queued`, `delivered`, `failed`, `unconfigured`, or `unknown` as appropriate; `delivered` is shown only after a provider receipt. Configure the public callback URL to receive final SMS delivery receipts. A network interruption after a provider accepts an SMS but before SheRail records its ID is marked `unknown`, not silently treated as delivered; manual retry warns that it could duplicate the message.

The mobile app requests foreground location permission before recording and records points only while it is open. It does not request background location permission. Location recording, safety-monitoring consent, SOS location sharing, and live-sharing consent are separate; live-sharing remains restricted to SheRail accounts selected by the journey owner and can be revoked. The route expected by deviation monitoring is private to the owner. WebSocket connections are managed in process, so live map updates and immediate in-app anomaly prompts require the connected API process; durable event creation and SMS escalation use PostgreSQL and the monitoring worker.

Passwords are validated and hashed with Argon2; plaintext passwords are never persisted or returned. Contact queries are always scoped to the authenticated user. JWTs use the configured secret and expire after `ACCESS_TOKEN_EXPIRE_MINUTES`.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

Tests use a temporary SQLite database; application configuration and migrations target PostgreSQL.
