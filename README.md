<div align="center">

# Integrated Share

**A self-hosted file sharing web application built for the RUET internal network**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.3-000000?style=flat&logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green?style=flat)

*Built by Team 0xTJRS23 · RUET student accounts only*

</div>

---

## What is Integrated Share?

Integrated Share is a self-hosted web application that lets anyone on the **RUET internal network** upload, manage, and share files from any device through just a browser. No cables, no USB drives, no cloud accounts. As long as you are connected to a RUET access point (RUET Students, CSE04, eduroam, or any other), you are in.

One machine on the network hosts the server. Everyone else opens a browser, types the server's local IP, and they are good to go.

---

## How it works

A single machine runs the Flask application. Since all RUET access points share the same internal network segment, any connected device can reach the server at its local IP (e.g., `http://10.12.47.52:5000`).

From there:

1. Create an account using your RUET student email (`@student.ruet.ac.bd`)
2. Log in and get your own private 1 GB file space
3. Upload anything — source code, documents, images, archives
4. Share files with a public download link or directly with another registered user
5. Log out and your session is gone — clean and simple

The dashboard looks and feels like Google Drive: a grid of file cards, a sidebar for navigation, and a storage bar that updates live as you upload or delete things.

---

## Features

- **User accounts** — each user gets their own isolated file space with a 1 GB storage limit
- **RUET-only registration** — only `@student.ruet.ac.bd` emails are accepted, enforced on the server side
- **Google Drive-style dashboard** — file grid, sidebar navigation (My Files / Shared with me), real-time storage bars
- **Multi-file upload** — drag and drop directly onto the page or click to browse; multiple files at once
- **Share links** — generate a 7-day public download link for any file
- **User-to-user sharing** — share a file directly with another registered user by their username
- **File management** — delete individual files or everything at once
- **Broad file support** — `.c`, `.cpp`, `.py`, `.java`, `.rs`, `.go`, `.sh`, `.txt`, `.md`, `.pdf`, images, archives, videos, and more
- **Upload security** — blocks server-side scripts, executables, and binary attack formats at the magic-byte level
- **SIEM-format activity log** — every login, upload, share, and delete is recorded with severity, category, outcome, and UTC timestamp following ECS conventions
- **Admin panel** — manage users and files, browse the full security log with severity/category/outcome badges
- **Session-based auth** — Flask signed session cookies, no JWT overhead
- **Responsive layout** — works on phones, tablets, and desktops

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+ · Flask |
| Database | SQLite via Flask-SQLAlchemy |
| Auth | Flask session cookies · Werkzeug PBKDF2-SHA256 password hashing |
| Frontend | HTML · CSS · Vanilla JavaScript |
| WSGI server | Gunicorn (production) |
| Cross-origin | Flask-CORS |

---

## Getting Started

### Prerequisites

- Python 3.10 or newer
- pip

### Installation

```bash
git clone https://github.com/InferiorAK/Integrated-Share.git
cd Integrated-Share
pip install -r requirements.txt
```

### Running the server

**Development:**

```bash
python app.py
```

**Production (Gunicorn):**

```bash
mkdir -p logs && gunicorn -w 4 -b 0.0.0.0:5000 --access-logfile logs/gunicorn-access.log --error-logfile logs/gunicorn-error.log app:app
```

The app starts on port `5000`. Anyone on the same local network can reach it through your machine's IP address.

> Find your local IP with `ip addr` on Linux or `ipconfig` on Windows.

---

## Usage

### Hosting (the machine running the server)

1. Connect to any RUET Wi-Fi
2. Run `python app.py` (or the Gunicorn command above for production)
3. Find your local IP — it will look something like `10.12.x.x`
4. Share that address — anyone on the RUET network can now open `http://<your-ip>:5000`

### Using the app (any device on the network)

1. Open `http://<server-ip>:5000` in any browser
2. Register with your `@student.ruet.ac.bd` email
3. Upload files by dragging them onto the page or clicking **New**
4. Click the share icon on any file card to get a 7-day public link, or share directly with a user by their username
5. Switch between **My Files** and **Shared with me** using the sidebar
6. The storage bar in both the topbar and sidebar updates live as you manage your files

### Default admin account

When the app starts for the first time it creates an admin user automatically.

| Username | Password |
|---|---|
| `admin` | `admin123` |

Change the password after first login. The admin panel is accessible at `/admin`.

---

## Project Structure

```
Integrated-Share/
├── app.py                  # Entry point — config, blueprints, DB init + SIEM column migration
├── requirements.txt
├── .gitignore
│
├── core/                   # Application logic split into Flask Blueprints
│   ├── extensions.py       # Shared SQLAlchemy db instance
│   ├── models.py           # DB models: User, SharedFile, FileShare, ActivityLog
│   ├── utils.py            # Auth decorators, file validator, SIEM log_action()
│   ├── auth.py             # /login  /register  /logout  /api/auth/*
│   ├── files.py            # /  /api/files  /api/upload  /api/download  /api/delete
│   ├── share.py            # /api/share/link  /api/share/user  /share/<token>
│   └── admin.py            # /admin  /api/admin/*
│
├── static/
│   ├── style.css           # Full cyan-themed UI: auth pages, Drive layout, SIEM badges
│   └── main.js             # File grid, sidebar filtering, drag overlay, storage bars
│
├── templates/
│   ├── index.html          # Main dashboard (Google Drive-style layout)
│   ├── login.html          # Login page
│   ├── register.html       # Registration page (RUET email enforced)
│   ├── admin.html          # Admin panel — users, files, SIEM security log
│   └── error.html          # Error page (invalid or expired share links)
│
├── logs/                   # Gunicorn access + error logs (git-ignored)
├── uploads/                # Per-user file directories (auto-created, git-ignored)
└── instance/
    └── integrated_share.db # SQLite database (auto-created, git-ignored)
```

---

## Security

The upload validator uses a denylist approach — it blocks what is dangerous and allows everything else.

- **Extension block** — `.php`, `.asp`, `.jsp`, `.cgi`, `.exe`, `.dll`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.lnk`, and similar server-side scripts or Windows attack vectors
- **Magic byte check** — rejects ELF, PE/COFF, and Mach-O executable binaries even if they have been renamed to look harmless
- **RUET email enforcement** — registration only accepts `@student.ruet.ac.bd` addresses, checked server-side
- **Isolated storage** — each user's files live in their own subdirectory under `uploads/`; no cross-user path traversal is possible
- **Password hashing** — Werkzeug PBKDF2-SHA256
- **Session security** — secret key is generated once and persisted to disk; sessions are signed

### SIEM activity log

Every significant event is written to the `ActivityLog` table in a format inspired by the [Elastic Common Schema (ECS)](https://www.elastic.co/guide/en/ecs/current/index.html):

| Field | Example values |
|---|---|
| `timestamp` | `2026-03-09T14:32:05Z` (ISO 8601 UTC) |
| `severity` | `INFO` · `LOW` · `MEDIUM` · `HIGH` |
| `event_category` | `AUTH` · `FILE_OP` · `SHARING` · `ADMIN` · `GENERAL` |
| `action` | `login` · `upload` · `share_link` · `delete` · `login_failure` |
| `outcome` | `SUCCESS` · `FAILURE` |
| `ip_address` | source IP of the request |

Failed login attempts are logged with `severity=MEDIUM` and `outcome=FAILURE`. All log entries are visible in the admin panel with colour-coded severity and outcome badges.

---

## Team

**Team 0xTJRS23** — a group of CSE students at RUET who built this as a hands-on project in web development, local networking, and application security.

| | |
|---|---|
| Taseen | Jahin |
| Roddro | Sadit |

---

## License

This project is open source under the [MIT License](LICENSE).

---

<div align="center">
<sub>Made for the RUET network · © 2026 Team 0xTJRS23</sub>
</div>
