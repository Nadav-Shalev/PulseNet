# How I Deployed the PulseNet Frontend + nginx on AWS EC2

This continues from my backend + RDS guide (`aws_deployment_guide.md`). At that point the Flask
backend was running on the EC2 and talking to MySQL on RDS. Here I put the **frontend on the same
instance**, switch the server from manual `scp` uploads to a **git clone** (so updates are just
`git pull`), run the backend as a **systemd service**, and put **nginx** in front so the whole app
opens in a browser at one address.

End result: the app is reachable at `http://<EC2_IP>` (frontend + API on the same origin), and
future updates are `git pull` + rebuild.

## Values to replace with your own

| What | My example | Replace with |
|---|---|---|
| Path to my `.pem` key | `C:\path\to\your-key.pem` | your key |
| EC2 public IP | `<EC2_IP>` | your IP (⚠️ changes on stop/start if you have no Elastic IP) |
| GitHub repo URL | `https://github.com/Nadav-Shalev/PulseNet.git` | your repo |
| RDS password | already in the EC2's `.env` | never put it here / in git |

> **Golden rule:** `scp` / `git push` from my **own computer**; everything else runs **on the EC2**
> (after `ssh`). And: the RDS endpoint + password live ONLY in `~/PulseNet/backend/.env` on the
> server — they are gitignored and must never be committed to a public repo.

---

## 1. I point the frontend at a relative API path (on my computer, then push)

The React app reads its API base from `VITE_API_BASE_URL` (default `http://localhost:5000/api`). In
production I want it to call the backend **same-origin**, so I add a build config file:

`frontend/.env.production`:
```
VITE_API_BASE_URL=/api
```

This makes the production build call `/api` (relative), which means it works no matter what the
server's IP is, and there is no CORS (same origin). I commit and push it:
```bash
git add frontend/.env.production
git commit -m "point frontend at relative /api for same-origin deploy"
git push origin main
```
(No backend change is needed — with a same-origin setup the CORS config is irrelevant.)

## 2. I switch the EC2 from scp to a git clone (on the EC2)

First I install git (it wasn't on the instance), then clone the **whole** repo and preserve the
existing `.env`:
```bash
sudo dnf install -y git
cd ~
git clone https://github.com/Nadav-Shalev/PulseNet.git
cp ~/backend/.env ~/PulseNet/backend/.env     # keep my DB credentials (gitignored, not in the repo)
cat ~/PulseNet/backend/.env                    # verify the 4 DB_* lines are there
```
I rebuild the virtualenv in the new location and verify the DB connection:
```bash
cd ~/PulseNet/backend
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt gunicorn
gunicorn --bind 127.0.0.1:5000 app:app & sleep 3
curl http://127.0.0.1:5000/api/articles      # [] = connected to the (empty) DB
pkill gunicorn
```
Only after I see `[]` do I delete the old scp'd folders:
```bash
rm -rf ~/backend ~/database
```

## 3. I run the backend as a systemd service (on the EC2)

So the backend survives an SSH disconnect, restarts on crash, and starts on boot:
```bash
sudo tee /etc/systemd/system/pulsenet.service > /dev/null << 'EOF'
[Unit]
Description=PulseNet Flask backend (gunicorn)
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/PulseNet/backend
ExecStart=/home/ec2-user/PulseNet/backend/venv/bin/gunicorn --bind 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pulsenet
sudo systemctl status pulsenet        # expect: active (running)
```

## 4. I install Node and build the frontend (on the EC2)

Vite 8 needs Node 20+:
```bash
sudo dnf install -y nodejs20
node --version                         # v20.x
cd ~/PulseNet/frontend
CYPRESS_INSTALL_BINARY=0 npm install   # skip the big Cypress binary I don't need on the server
npm run build                          # builds dist/ using .env.production (-> /api)
ls dist                                # index.html + assets/
```
(The instance is small — 1 GB RAM. If `npm run build` is `Killed` (OOM), add a 2 GB swap file and
retry.)

## 5. I install and configure nginx (on the EC2)

nginx serves the built `dist/` and proxies `/api` and `/uploads` to the Flask service:
```bash
sudo dnf install -y nginx
```
Amazon Linux 2023's stock `nginx.conf` ships its own default server on port 80, which collides with
mine. I back it up and replace it with a clean version that has **no** default server block (so only
my config in `conf.d` defines a server):
```bash
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak
sudo tee /etc/nginx/nginx.conf > /dev/null << 'EOF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

include /usr/share/nginx/modules/*.conf;

events { worker_connections 1024; }

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    keepalive_timeout 65;

    include /etc/nginx/conf.d/*.conf;
}
EOF
```
My server config:
```bash
sudo tee /etc/nginx/conf.d/pulsenet.conf > /dev/null << 'EOF'
server {
    listen 80 default_server;
    server_name _;

    root /home/ec2-user/PulseNet/frontend/dist;
    index index.html;
    client_max_body_size 10M;            # backend allows ~6MB uploads; nginx default 1MB would 413

    location / { try_files $uri $uri/ /index.html; }   # SPA routing

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location /uploads/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
    }
}
EOF
```
nginx (user `nginx`) needs to traverse my home directory to reach `dist/`, then I test and start it:
```bash
sudo chmod o+x /home/ec2-user
sudo nginx -t                          # syntax is ok / test is successful
sudo systemctl enable --now nginx
# verify from inside the instance:
curl -s http://127.0.0.1/ | head -3            # React <!doctype html>
curl -s http://127.0.0.1/api/articles          # []
```

> **If port 80 is already taken** (for me it was — I also run phpMyAdmin on Apache/`httpd` on :80):
> keep Apache on 80 and serve PulseNet on **8080** instead. Change my config's first line to
> `listen 8080 default_server;`, then `sudo systemctl restart nginx` and
> `sudo systemctl enable --now httpd`. The app is then at `http://<EC2_IP>:8080` and phpMyAdmin at
> `http://<EC2_IP>/phpmyadmin/`. The relative `/api` still works because it stays same-origin
> (same host *and* port).

## 6. I open the port in the Security Group (AWS Console)

EC2 → Instances → my instance → **Security** tab → click the security group → **Edit inbound
rules** → **Add rule** → Type **HTTP** (port 80) — or **Custom TCP** port **8080** if I used 8080 —
Source **Anywhere-IPv4 (0.0.0.0/0)** → **Save rules**.

## 7. I verify end-to-end (browser)

I open `http://<EC2_IP>` (or `:8080`) and:
- the PulseNet UI loads,
- I sign up a new user (tests a DB write + the session cookie, same-origin),
- I create a post with an image (tests upload to `/uploads/` through nginx),
- the post and its image show up.

---

## Updating later (the whole point of using git)

```bash
cd ~/PulseNet && git pull
sudo systemctl restart pulsenet        # if the backend changed
cd frontend && npm run build           # if the frontend changed
```

> Note: with no Elastic IP, the EC2's public IP changes every time I stop/start the instance. After
> a restart I grab the new IP from the EC2 console and use it in the browser (and update my SSH
> config's HostName).
