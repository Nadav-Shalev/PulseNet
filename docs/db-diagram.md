# PulseNet Database Schema

Source of truth: [`database/schema.sql`](../database/schema.sql).

A rendered ERD image is committed at [`db-diagram.png`](./db-diagram.png):

![PulseNet ERD](./db-diagram.png)

The same diagram is also kept as Mermaid in [`db-diagram.mmd`](./db-diagram.mmd).

```mermaid
erDiagram
    users      ||--o{ posts      : "authors"
    users      ||--o{ sessions   : "has"
    posts      ||--o{ posts_tags : "tagged by"
    tags       ||--o{ posts_tags : "applied to"
    users      ||--o{ follows    : "is follower"
    users      ||--o{ follows    : "is followed"

    users {
        int      id PK
        varchar  name
        varchar  username UK
        varchar  email UK
        text     bio
        varchar  avatar
        varchar  profile_image
        varchar  password_hash
    }

    sessions {
        varchar   session_id PK
        int       user_id FK
        timestamp expires_at
    }

    posts {
        int       id PK
        int       author_id FK
        varchar   title
        text      body
        longtext  body_html
        text      description
        varchar   cover_image
        int       devto_id UK
        varchar   devto_url
        varchar   readable_publish_date
        timestamp created_at
    }

    tags {
        int     id PK
        varchar name UK
    }

    posts_tags {
        int post_id FK
        int tag_id FK
    }

    follows {
        int       follower_id FK
        int       following_id FK
        timestamp created_at
    }
```

## Exporting A PNG

Use one of these options:

1. Paste `docs/db-diagram.mmd` into mermaid.live and export PNG.
2. Preview the Mermaid diagram in VS Code with a Mermaid extension and save it.
3. Run `npx @mermaid-js/mermaid-cli -i docs/db-diagram.mmd -o docs/db-diagram.png`.
