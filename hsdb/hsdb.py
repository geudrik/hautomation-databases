#! /usr/bin/env python2.7
# -*- coding: latin-1 -*-

import ConfigParser
import os

from uuid import uuid4

from datetime import datetime

from sqlalchemy import create_engine

from sqlalchemy import event
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import VARCHAR
from sqlalchemy.orm import relationship
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import synonym
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.ext.declarative import declarative_base

"""
This whole section is a bit of a hack, but it works. Try to load DB connection vars
from our config file, overriding/setting where not defined. At a bare minimum, we
need to have a username and password. Other vars will be set as defaults

file: ~/.config/homestack

[homestack_databases]
user = root
pass = root
host = localhost
port = 3306
name = MyDBName
keep_alive = True
"""
try:
    conf_path = os.environ.get("HOMESTACK_CONFIG", "~/.config/homestack")
    parser = ConfigParser.ConfigParser()
    parser.read(os.path.expanduser(conf_path))

    db_user = parser.get("homestack_databases", "user")
    db_pass = parser.get("homestack_databases", "pass")

except Exception as e:
    raise Exception("\nA username and password for the database must be set in ~/.config/homestack\n{}".format(e))

try:
    db_host = parser.get("homestack_databases", "host")
except ConfigParser.NoOptionError:
    db_host = "localhost"

try:
    db_port = parser.get("homestack_databases", "port")
except ConfigParser.NoOptionError:
    db_port = 3306

try:
    db_name = parser.get("homestack_databases", "name")
except ConfigParser.NoOptionError:
    db_name = "homestack"

try:
    db_keep_alive = parser.getboolean("homestack_databases", "keep_alive")
except:
    pass

# Set up our Engine
hs_engine = create_engine(
    "mysql://{}:{}@{}:{}/{}?charset=utf8".format(
        db_user,
        db_pass,
        db_host,
        db_port,
        db_name),
    encoding = "utf8",
    pool_recycle=1800, 
    pool_size=5)

# Initialize our ORM
hs_base = declarative_base()
hs_base.metadata.bind = hs_engine
hs_session_maker = sessionmaker(bind=hs_engine)


"""
The following is keep-alive related code. We ran into issues in the past.
When using flask-sqlalchemy, this is all handled for you (amongst other stuff)
    but since we wanted to diorce our models from our web app (so we can easily
    use them elsewhere), we now have to handle this ourselves
"""
if db_keep_alive:

    """
    Listen for engine connections, and ensure they're alive
    """
    @event.listens_for(hs_engine, "engine_connect")
    def ping_connection(connection, branch):
        """
        Branch refers to a child connection of a given connection.
        We don't want to be pinging on these, only the parent
        """
        if branch:
            return

        """
        Disable "close with result".  This flag is only used with "connectionless"
        execution, otherwise will be False by default
        """
        save_should_close_with_result = connection.should_close_with_result
        connection.should_close_with_result = False

        try:
            """
            Attept to run a `SELECT 1`, using a core SELECT(), which ensures our
            selection of a scalar without a table defined is formatted correctly
            for the recieving backend
            """
            connection.scalar(select([1]))

        except exc.DBAPIError as err:
            """
            Shit bricks when our SELECT 1 fails
            DBAPIError is a wrapper for DPAPI's generic exception. It includes a
            `.connection_invalidated` attribute though, which specifies whether or
            not this connection is a 'disconnect' condition. We can determine this
            by inspecging the original exception.
            """

            if err.connection_invalidated:
                """
                Attempt to re-run the same select as above. The idea being that
                the connection will re-validate itself.

                The disconnect detection here also causes the entire connection
                pool be become invalidated, resulting in all stale connections
                being discarded.
                """
                connection.scalar(select([1]))

            else:
                raise

        finally:
            # Restore our 'close_with_result'
            connection.should_close_with_result = save_should_close_with_result

    """
    Possible improvements for pool when involved in subprocesses
    Reference: http://docs.sqlalchemy.org/en/latest/core/pooling.html
    """
    @event.listens_for(hs_engine, "connect")
    def connect(dbapi_connection, connection_record):
        connection_record.info['pid'] = os.getpid()

    """
    Prohibit interprocess hijacking of connetions
    """
    @event.listens_for(hs_engine, "checkout")
    def checkout(dbapi_connection, connection_record, connection_proxy):
        pid = os.getpid()
        if connection_record.info['pid'] != pid:
            connection_record.connection = connection_proxy.connection = None
            raise exc.DisconnectionError(
                "Connection record belongs to pid {}, attempting to check out in pid {}".format(
                    connection_record.info['pid'],
                    pid))

"""
Begin actually defining our databaes!
"""

class HomestackDatabase(object):
    """
    Base class that all of our other DB classes inherit from
    The purpose here is to provide additional functionality and provode some ease
    of use helpers in all of our other classes
    """

    _base           = hs_base
    _engine         = hs_engine
    _session_maker  = hs_session_maker
    _session        = hs_session_maker()

    @classmethod
    def get_session(cls):
        """
        Sometimes, we just need a damn session. This lets us simple do
        things like `session = Users.get_session()`. Is nice, I take.
        """
        return cls._session

    @classmethod
    def filter_by(cls, *args, **kwargs):
        """
        `filter_by()` is for simple 'where' clauses. This makes that feel more natural

        Examples:
            Users.filter_by(name='Mike')    Literally, get all rows from `Users` where `name=Mike`
        """
        return cls.query().filter_by(*args, **kwargs)

    @classmethod
    def filter(cls, *args, **kwargs):
        """
        `filter()` is the manly form of filter_by (the prior is only for convienience).
        This again, lets us write a little less code, but otherwise functions exactly
            the same as the built-in filter() function

        Examples:
            Users.filter(or_(Users.name='Mike', Users.username='mDog'))
                instead of...
            Users.query().filter(...)
        """
        return cls.query().filter(*args, **kwargs)

    @classmethod
    def search(cls, *args, **kwargs):
        """
        Functions exactly the same way as our filter() method, returning the same data
        This just reads more nicely in code than filter() does
        """
        return cls.query().filter(*args, **kwargs)

    @classmethod
    def list(cls):
        """
        Another helper/idiot method to literally just return a list of objects

        Examples:
            user_list = Users.list()
        """
        return cls.query().all()

    @classmethod
    def query(cls, *args):
        """
        Helper class to let us easily query. query() normally takes a Class as a param,
            as it's a _session function, but here we expose it and make it more natural

        Examples:
            Users.query(name).first()       Get the `name` from `Users` of the first() row
            Users.query().first()           Get the first row returned from `Users`

        Ref: http://docs.sqlalchemy.org/en/latest/orm/tutorial.html#querying
        """

        # If we have arguments, assume we're querying against what ever class is calling
        if len(args):
            return cls._session.query(cls, cls, *args)

        # No args, so assume we're running a generic query() against `this` class
        return cls._session.query(cls)

class User(hs_base, HomestackDatabase):
    """
    Class that represents our User table
    """

    __tablename__   = "Users"
    __bind_key__    = "homestack"

    # int: The id of the user
    user_id         = Column(INTEGER(unsigned=True), primary_key=True)
    id              = synonym("user_id")

    # datetime: The time the user record was originally created
    time            = Column(DATETIME, default=datetime.utcnow, nullable=False, index=True)

    # datetime: The time the user last logged in
    timestamp       = Column(DATETIME, default=datetime.utcnow, nullable=False, index=True)

    # str: The username for this user
    username        = Column(VARCHAR(128), unique=True, nullable=False)

class ApiKey(hs_base, HomestackDatabase):
    """
    Class that represents our API Keys table
    """

    __tablename__   = 'APIKeys'
    __bind_key__    = 'homestack'

    # int: API key id
    api_key_id      = Column(INTEGER(unsigned=True), primary_key=True)
    key_id          = synonym("api_key_id")
    id              = synonym("api_key_id")

    # int: User id for this key
    user_id         = Column(INTEGER(unsigned=True), ForeignKey("Users.user_id"), nullable=False)

    # str: The api key
    api_key         = Column(VARCHAR(36), unique=True, nullable=False, default=uuid4)

    # str: brief description for usage of this key
    description     = Column(VARCHAR(255))

    # datetime: The time the record was originally created
    created         = Column(DATETIME, default=datetime.utcnow, nullable=False, index=True)

    # object: Convienience relationship to our User class
    user            = relationship("User")

# Explicitely do nothing on direct run
if __name__ == "__main__":
    pass
