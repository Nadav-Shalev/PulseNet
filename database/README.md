# PulseNet Database

`schema.sql` is the MySQL schema for the PulseNet backend.

From the project root:

```bash
mysql -u root -p < database/schema.sql
```

The schema creates the `pulsenet_db` database and the tables used by the Flask API:
`users`, `sessions`, `posts`, `tags`, `posts_tags`, and `follows`.
