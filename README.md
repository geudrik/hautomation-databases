# [Homestack](https://github.com/geudrik/homestack)
[Homestack](https://github.com/geudrik/homestack) is my attempt at a unified and centralized home automation / home lab management front end and API.
This is the repository for the database library. I opted to divorce the models from Flask as it allowed me additional flexibility moving forward.

### Dependencies
```
sudo apt-get install git python-pip -y
pip install alembic sqlalchemy argon2
```

### Config File
This library is configured to read in a config file. Without it, the library will not work. The following should exist in `~/.config/homestack` for this library to initialize correctly. Alternatively, the environment variable `HOMESTACK_CONFIG` can also contain a path to any file you wish that contains the following configuration details

```sql
[homestack_databases]
user = db_user
pass = db_pass

# Optional params. Defaults are specified
host = localhost
port = 3306
name = homestack
```

### Installation
`pip install git+git://github.com/geudrik/homestack-db-library.git`

**Free Software, Hell Yea!**
