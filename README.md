[README.md](https://github.com/user-attachments/files/33920961/README.md)# Room / Facility / Vehicle Scheduler

A simple internal web app for requesting and approving rooms, facilities and vehicles.

|||
|-|-|
|**Stack**|Python, Flask, SQLite|
|**Network**|LAN-only (not intended for the public internet)|
|**Default port**|`5070`|
|**Data location**|`/data` inside the container (SQLite database)|

> \*\*Security:\*\* The default login is \*\*`admin` / `admin123`\*\*. Change it immediately under \*\*Admin > Add/update user\*\*. Always set a long random `SECRET\_KEY` in production.

\---

## Table of Contents

1. [Roles \& Permissions](#roles--permissions)
2. [Configuration](#configuration)
3. [Run Locally on Your Computer](#run-locally-on-your-computer)
4. [Deploy on Synology DSM 7.0](#deploy-on-synology-dsm-70)
5. [Backup \& Updates](#backup--updates)
6. [Troubleshooting](#troubleshooting)

\---

## Roles \& Permissions

Each role includes everything the role above it in the table can do.

|Capability|Requestor|Approver|Admin|
|-|:-:|:-:|:-:|
|Submit requests|✅|✅|✅|
|View own requests|✅|✅|✅|
|Cancel own requests|✅|✅|✅|
|Approve / reject any request|❌|✅|✅|
|Manage resources (rooms, facilities, vehicles)|❌|❌|✅|
|Manage users|❌|❌|✅|
|Dashboard \& reports|❌|❌|✅|

\---

## Configuration

|Setting|Where|Description|Example|
|-|-|-|-|
|`SECRET\_KEY`|Environment variable|Signs session cookies. Use a long random string.|`change-me-to-a-long-random-string`|
|Port|Docker `-p` flag|Host port mapped to container port `5070`|`-p 5070:5070`|
|Data volume|Docker `-v` flag|Persists the SQLite database outside the container|`-v ./data:/data`|

Generate a random secret key:

```bash
python -c "import secrets; print(secrets.token\_hex(32))"
```

\---

## Run Locally on Your Computer

Two options: **Docker** (no Python setup) or **plain Python**. Both work on Windows, macOS and Linux.

### Option A: Docker (recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
# 1. From the project folder (where the Dockerfile is)
docker build -t request-system .

# 2. Run it (data is saved in a local ./data folder)
docker run -d --name request-system -p 5070:5070 \\
  -e SECRET\_KEY="dev-secret-change-me" \\
  -v "$(pwd)/data:/data" \\
  request-system
```

On **Windows PowerShell**, use `${PWD}` instead of `$(pwd)`:

```powershell
docker run -d --name request-system -p 5070:5070 `
  -e SECRET\_KEY="dev-secret-change-me" `
  -v "${PWD}/data:/data" `
  request-system
```

Open [http://localhost:5070](http://localhost:5070).

### Option B: Python (no Docker)

Requires Python 3.9+.

**macOS / Linux**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export SECRET\_KEY="dev-secret-change-me"
python app.py
```

**Windows (PowerShell)**

```powershell
python -m venv venv
venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
$env:SECRET\_KEY = "dev-secret-change-me"
python app.py
```

Open [http://localhost:5070](http://localhost:5070).

> If the entry file is not `app.py`, run whichever file starts the Flask app (check the last line of the `Dockerfile`, usually `CMD`). If the database path is configurable, point it to a local folder instead of `/data`.

### Share it with other PCs on your network (optional)

1. Find your computer's LAN IP (`ipconfig` on Windows, `ifconfig` / `ip a` on macOS/Linux).
2. Allow port `5070` through the firewall.
3. Others open `http://<your-ip>:5070`.

### Stop / remove (Docker)

```bash
docker stop request-system
docker rm request-system
```

\---

## Deploy on Synology DSM 7.0

Uses the **Container Manager / Docker** package.

|Step|Action|
|-|-|
|1|Copy this folder to the NAS, e.g. `/volume1/docker/request-system/app`, and create `/volume1/docker/request-system/data`.|
|2|SSH into the NAS.|
|3|Build the image (see below).|
|4|Run the container (see below).|
|5|Open `http://NAS-IP:5070` from any PC on the LAN.|

**Build**

```bash
cd /volume1/docker/request-system/app
sudo docker build -t request-system .
```

**Run**

```bash
sudo docker run -d --name request-system --restart unless-stopped \\
  -p 5070:5070 \\
  -e SECRET\_KEY="<long random string>" \\
  -v /volume1/docker/request-system/data:/data \\
  request-system
```

\---

## Backup \& Updates

|Task|How|
|-|-|
|**Backup**|Back up `/volume1/docker/request-system/data` (e.g. with Hyper Backup). Locally, back up the `./data` folder.|
|**Update**|Rebuild the image, remove the old container, run it again. Data persists because it lives in the mounted volume.|

```bash
sudo docker build -t request-system .
sudo docker rm -f request-system
# then re-run the "docker run" command above
```

\---

## Troubleshooting

|Problem|Likely cause / fix|
|-|-|
|Can't open `http://NAS-IP:5070`|Check the container is running (`docker ps`), the port isn't used by something else, and the NAS firewall allows `5070`.|
|Logged out constantly / sessions reset|`SECRET\_KEY` changes between restarts. Set a fixed value.|
|Data disappears after update|The `-v` data volume was missing. Always mount `/data`.|
|`Port is already allocated`|Use another host port, e.g. `-p 8080:5070`.|
|Forgot admin password|Restore a backup of `data/`, or reset the user in the SQLite database.|



