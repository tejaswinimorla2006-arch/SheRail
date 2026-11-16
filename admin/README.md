# SheRail Admin

Standalone Vite + React admin interface. From this directory, install dependencies with `npm install` and start the development server with `npm run dev`. Set `VITE_API_URL` to the API base URL (default: `/api/v1`); the value should include `/api/v1`.

The login token stays in `sessionStorage` for the current browser tab. Each session is checked against the protected admin overview endpoint before the dashboard is shown. API authorization must be enforced by the server; any role information shown by the client is informational only.

The resource forms follow the API schemas: assistance points use `name`, `category`, `description`, `address`, `phone`, `latitude`, `longitude`, and `is_active`; railway records use `category`, `title`, `description`, `station_name`, `phone`, `contact_url`, `availability`, and `is_active`. Reports expose image UUIDs in `image_ids`; each preview is fetched as authenticated bytes from `/admin/community-reports/{report_id}/images/{image_id}`.
