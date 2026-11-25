# GuardLink

GuardLink is a Django web application for requesting security guards and
managing guard assignments, shifts, attendance, payments, and rewards.

## Database

The development database is **SQLite** (`db.sqlite3`), included with Python and
requiring no separate database server. Django creates the tables from the
version-controlled migrations in `core/migrations/`. SQLite is a good fit for a
local student project; PostgreSQL is a suitable next step for a deployed,
multi-user system.

The main data records are:

- **Users**: email-based login, hashed password, contact details, and client or
  administrator role.
- **Ranks and guards**: rank rates, guard identity, and availability.
- **Sites and guard requests**: client-owned locations and requested rank,
  shift, quantity, dates, and status. A client submits a separate request for
  each shift needed; administrators assign guards only to the requested shift.
- **Shifts, assignments, and attendance**: deployment schedule and daily
  attendance records.
- **Guard payroll and rewards**: pay periods, present shifts, bonuses, and totals.
- **Client invoices**: one invoice per fully assigned request, based on the
  scheduled guard-days and the rank's client daily rate.

## Run locally

From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

`createsuperuser` asks for email, full name, and a password. Use that account to
sign in as an administrator. The admin setup page at `/admin/` is where you
create ranks and their guard/client daily rates, create shift types, and add
guard records before clients submit requests. Clients create their own accounts
using **Create account**. Admin roles cannot be selected on the public
registration form.

Clients choose one shift for each request. To request Day and Night coverage,
submit two requests. Administrators assign the requested number of guards to
that shift, then record attendance for payroll.

Open the address printed by Django (usually `http://127.0.0.1:8000/`) in your
browser. The development server is for local development, not production.

## Payroll, rewards, and client invoices

Guard payroll and client billing are separate:

- **Guard payroll** counts attendance marked Present in the selected period
  and multiplies by the guard daily rate. Rewards dated in that period are
  calculated as a percentage of base pay: Excellent Service (25%), Good Service
  (5%), Perfect Attendance (10%), and Client Perfect Rating (5%). Only the
  highest qualifying reward percentage applies. Perfect Attendance requires
  every scheduled shift-day in the period to be recorded Present. Absent and
  Late records do not count as paid shift-days.
- **Client invoices** bill scheduled coverage: each assigned guard-day is
  charged at the rank's client daily rate, whether or not attendance is later
  marked absent. An administrator can create a draft invoice after all guards
  for an approved/completed request are assigned, issue it to the client, then
  mark it paid. Clients see issued and paid invoices on their dashboard.

For example, one assigned guard scheduled for three calendar days creates
three billable guard-days. This demo does not include taxes, discounts,
overtime, cancellation fees, or partial-day pricing.

## Login and permissions

Django's authentication system verifies passwords and stores only password
hashes. Clients can see only their own request history. Administrator-only
screens require an administrator account, and the public signup flow always
creates a client account. Log out using the **Log out** button.

The committed secret key is only a development fallback. Before deployment,
set a private `DJANGO_SECRET_KEY`, configure `DJANGO_ALLOWED_HOSTS`, turn off
debug mode with `DJANGO_DEBUG=false`, and use a production-ready database and
web server. `STATIC_ROOT` is configured for collecting static files.

## Tests

Run the application tests with:

```bash
python manage.py test core
```