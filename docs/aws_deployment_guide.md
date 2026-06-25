# How I Deployed the PulseNet Backend + RDS on AWS EC2

This is a step-by-step writeup of exactly what I did to get the Flask backend running on an EC2 instance and talking to a MySQL database on Amazon RDS — from uploading the backend all the way to a verified backend ↔ database connection.

## Values to replace with your own

| What | My example | Replace with |
|---|---|---|
| Path to my `.pem` key | `C:\path\to\your-key.pem` | your key |
| EC2 public IP | `<EC2_IP>` | your IP |
| RDS endpoint | `database-xxxx.eu-central-1.rds.amazonaws.com` | your endpoint |
| RDS password | `<YOUR_RDS_PASSWORD>` | your password (**do NOT share it on Slack!**) |

> **Golden rule:** commands that use `scp` run **on my own computer** (PowerShell). Everything else runs **on the EC2** (after `ssh`).

---

## 1. I connect to my EC2 (on my computer)

```bash
ssh -i "C:\path\to\your-key.pem" ec2-user@<EC2_IP>
```

It's Amazon Linux 2023, so the SSH user is `ec2-user` and the package manager is `dnf`.

## 2. I upload the backend folder (on my computer — a separate terminal, NOT inside the SSH session)

```powershell
cd "C:\path\to\PulseNet"
scp -i "C:\path\to\your-key.pem" -r backend ec2-user@<EC2_IP>:~/
```

This copies the whole `backend/` folder to the server's home directory.

## 3. I install the backend dependencies (on the EC2)

```bash
cd ~/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

From here on, as long as I see `(venv)` at the start of the line, I'm in the right environment.

## 4. I create the RDS database (in the AWS Console)

1. RDS → **Create database** → **MySQL** → **Free tier**.
2. I set: DB identifier, Master username = `admin`, and a master password.
3. When it's done I copy the **Endpoint** — that becomes my `DB_HOST`.

## 5. I reset the RDS master password (in the AWS Console)

I didn't remember the password I set, so I reset it (you can't recover an RDS password, only reset it — and it does not delete any data):

RDS → **Databases** → select my DB → **Modify** → **New master password** → type a new one → **Continue** → **Apply immediately** → **Modify DB instance**. I wait until the status goes back to **Available**.

## 6. I install the mysql client (on the EC2)

On Amazon Linux 2023 the `mysql` command comes from the `mariadb105` package:

```bash
sudo dnf install -y mariadb105
```

## 7. I test that the EC2 can reach the RDS (on the EC2)

```bash
mysql -h database-xxxx.eu-central-1.rds.amazonaws.com -u admin -p
```

I type the master password when prompted.

- If I get into the `MySQL [(none)]>` prompt → the network is fine (I type `exit`).
- If it hangs / times out → the RDS **Security Group** is blocking it. Fix: on the RDS security group add an **Inbound rule** of type **MySQL/Aurora (port 3306)** with Source set to the EC2's security group.

## 8. I load the schema into RDS

First, on my computer, I upload `schema.sql`:

```powershell
cd "C:\path\to\PulseNet"
scp -i "C:\path\to\your-key.pem" database\schema.sql ec2-user@<EC2_IP>:~/
```

Then, on the EC2, I stream it into the database (the `<` feeds the file's contents into mysql):

```bash
mysql -h database-xxxx.eu-central-1.rds.amazonaws.com -u admin -p < ~/schema.sql
```

`schema.sql` itself runs `CREATE DATABASE IF NOT EXISTS pulsenet_db;`, so it creates the database and all the tables in one shot.

I verify that 6 tables were created:

```bash
mysql -h database-xxxx.eu-central-1.rds.amazonaws.com -u admin -p -e "USE pulsenet_db; SHOW TABLES;"
```

I expect to see: `users`, `sessions`, `posts`, `tags`, `posts_tags`, `follows`.

> Tip: the `-e "..."` flag runs a single command and exits, so I don't get stuck inside the interactive mysql monitor.

## 9. I create the `.env` file (on the EC2, inside `~/backend`)

The backend reads its DB connection from `DB_HOST / DB_USER / DB_PASSWORD / DB_NAME`, so the `.env` is what actually connects the backend to the database:

```bash
cd ~/backend
cat > .env << 'EOF'
DB_HOST=database-xxxx.eu-central-1.rds.amazonaws.com
DB_USER=admin
DB_PASSWORD=<YOUR_RDS_PASSWORD>
DB_NAME=pulsenet_db
EOF
```

I check it was written correctly with `cat .env`.

## 10. I verify the backend actually talks to the database (on the EC2)

**Direct connection test** — this runs the exact same connection the app uses, reading from `.env`:

```bash
source venv/bin/activate
python3 -c "import mysql.connector,os; from dotenv import load_dotenv; load_dotenv(); c=mysql.connector.connect(host=os.getenv('DB_HOST'),user=os.getenv('DB_USER'),password=os.getenv('DB_PASSWORD'),database=os.getenv('DB_NAME')); print('CONNECTED OK'); c.close()"
```

`CONNECTED OK` means success.

**API test** — I start the server and hit an endpoint:

```bash
pkill gunicorn 2>/dev/null
gunicorn --bind 127.0.0.1:5000 app:app &
curl http://127.0.0.1:5000/api/articles
```

- `[]` (empty list) → the backend is reading from the real (empty) database. ✅
- A full list of mock articles → it fell back to mock data (not connected) → I re-check `.env`.

To stop the server: `pkill gunicorn`.

---

## Done

At this point the backend and the RDS database are connected and working on AWS.

**Next step (not in this guide):** open the API to the outside world — run `gunicorn --bind 0.0.0.0:5000 app:app` and open port 5000 in the EC2 security group — and then point the frontend at the EC2 backend.
