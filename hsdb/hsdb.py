#! /usr/bin/env python2.7
# -*- coding: latin-1 -*-

import ConfigParser
import os

from uuid import uuid4

from datetime import datetime

from sqlalchemy import create_engine

from sqlalchemy import exc
from sqlalchemy import event
from sqlalchemy import Table
from sqlalchemy import Column
from sqlalchemy import select
from sqlalchemy import VARCHAR
from sqlalchemy import ForeignKey
from sqlalchemy.orm import synonym
from sqlalchemy.orm import relationship
from sqlalchemy.orm import sessionmaker
from sqlalchemy.inspection import inspect
from sqlalchemy.dialects.mysql import BINARY
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm.relationships import RelationshipProperty

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

    @classmethod
    def insert(cls, **kwargs):
        """
        Helper method to simplify inserts. Create an instance, insert it, commit it, and return it
        """

        instance = cls(**kwargs)

        cls._session.add(instance)
        cls._session.commit()

        return instance

    def delete(self):
        """
        Helper function that allows us to tack on .delete() on a select if we want
        """
        self.__class__._session.delete(self)
        self.__class__._session.commit()

    def _get_hybrid_properties(self):
        return dict( (key, prop) for key, prop in inspect(self).mapper.all_orm_descriptors.items() if isinstance(prop, hybrid_property) )

    def serialize(self, depth=1, hybrid=True):
        """
        Aren't recursive functions super fun?

        Iterate over our object, following relationships to a max `depth`
        ultimately returning a json serializable format (see: a dict)

        BEWARE THE BACKREF
            User -> UserGroups -> User -> .....

        The use of `__serializable_relations__` is the hack-n-slash method to indicate
        which relationships for that class we should recurse through

        See the UserGroup class for an example. The `roles` relationship will be serialized

        Args:
            depth (int) The max number of levels to recurse through
            hybrid (bool) Whether or not to include the serialization of hybrid properties

        """

        # Bail if we've exhausted our recursion depth
        if depth == 0:
            return None

        # Our return object
        ret = {}

        # Quick check to see if we're serializiable
        def is_serializable():
            if hasattr(self, '__serializable_relations__') and key in self.__serializable_relations__ and depth > 1:
                return True
            return False

        # Ensure our session is more fresh than Stunna's coke
        # This ensures we don't hit weird edge-case scenerios where attributes don't exist
        attributes = self.__dict__.items()
        if not [ attr for attr in attributes if attr[0] is str and not attr[0].startswith('_') ]:
            self._session.refresh(self)

        # For each relationship we've explicitely set as serialziable via __serializable_relations__
        #   load them!
        # getattr returns a value, thus implicitely loading our property into this instance
        properties = self.__mapper__.iterate_properties
        for prop in properties:
            if isinstance(prop, RelationshipProperty):
                key = getattr(prop, 'key')
                if is_serializable():
                    getattr(self, key)

        # Begin to actually walk through our object and begin to serialize the data
        for key, value in self.__dict__.items():

            # If our key looks private, ignore it and continue
            if key.startswith("_"):
                continue

            # If our value is an instance of HomestackDatabase
            if isinstance(value, HomestackDatabase):
                if is_serializable():
                    ret[key] = value.serialize(depth=depth-1)

            # If our value is a list of objects
            elif isinstance(value, list):

                _ret = []
                for item in value:

                    # Looping through all items, do the same work we do against a single
                    if isinstance(item, HomestackDatabase):
                        if is_serializable():
                            _ret.append(item.serialize(depth=depth-1))

                ret[key] = _ret

            # Other weird edge cases for serialization
            else:

                # How to serialize datetime objects
                if isinstance(value, datetime):
                    ret[key] = value.isoformat()

                # Blind fallback #yolo
                else:
                    ret[key] = value

        # Attempt to serialize our hybrid properties
        if hybrid:

            hybrid_properties = self._get_hybrid_properties()

            for key, value in hybrid_properties.items():
                value = value.get(self)

                # How to serialize datetime objects
                if isinstance(value, datetime):
                    ret[key] = value.isoformat()

                # Blind fallback #yolo
                else:
                    ret[key] = value

        # Finally, return our dict
        return ret

"""
The following two tables are essentially pivot tables. They're what allows us
to easily map roles to gruops, and visa-versa
"""
UserGroupToRole     = Table(
                        "UserGroupsToRoles",
                        hs_base.metadata,
                        Column("user_group_id", INTEGER(unsigned=True), ForeignKey("UserGroups.group_id")),
                        Column("role_id", INTEGER(unsigned=True), ForeignKey("Roles.role_id"))
                    )

UserToUserGroup     = Table(
                        "UsersToUserGroups",
                        hs_base.metadata,
                        Column("user_id", INTEGER(unsigned=True), ForeignKey("Users.user_id")),
                        Column("user_group_id", INTEGER(unsigned=True), ForeignKey("UserGroups.group_id"))
                    )

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

    # bin: The binary representation of a sha256 hash, generated by pbkdf2 hasking
    password_salt   = Column(BINARY(32), nullable=False, index=True, default=lambda: os.urandom(32))

    # list: Map the users groups
    user_groups     = relationship("UserGroup", secondary=UserToUserGroup)

    # Flask-Login related attributes and methods
    is_authenticated = True
    is_anonymous    = False
    is_active       = True

    # Determine whether or not this user has a given role
    def has_role(self, name):
        for group in self.user_groups:
            for role in group.roles:
                if name == role.name:
                    return True
        return False

    # Determine whether or not this user is in the specified group
    def in_group(self, name):
        return name in [ v.name for v in self.user_groups ]

    # Per Miguel Grinberg's suggestion, return Flask-Login friendly unique ID in Unicode
    def get_id(self):
        try:
            return unicode(self.user_id)
        except NameError:
            return str(self.user_id)


class Password(hs_base, HomestackDatabase):
    """
    Class that represents our Passwords table
    """

    __tablename__   = "Passwords"
    __bind_key__    = "homestack"

    # int: The ID of the password row
    password_id     = Column(INTEGER(unsigned=True), primary_key=True)
    id              = synonym('password_id')

    # bin: the binary representation of a sha256 encrypted password
    hashed_password = Column(BINARY(128), nullable=False, index=True)


class UserGroup(hs_base, HomestackDatabase):
    """
    Class that holds groups. This is only lightly used currently. The alembic
    transform contains an insert creating our 'administrators' group

    We leverage this predominantly for API key usage
    """

    __tablename__   = 'UserGroups'
    __bind_key__    = 'homestack'
    __serializable_relations__ = ['roles']

    # int: the ID of this group
    group_id        = Column(INTEGER(unsigned=True), primary_key=True)
    id              = synonym("group_id")

    # str: the name of this group
    name            = Column(VARCHAR(30), unique=True, nullable=False)

    # Helper relationships
    users           = relationship("User", secondary=UserToUserGroup)
    roles           = relationship("Role", secondary=UserGroupToRole)


class Role(hs_base, HomestackDatabase):
    """
    This class contains specific priviledges required to access certain
    routes/endpoints. The 'admin' role is created in the alembic migration
    """

    __tablename__   = 'Roles'
    __bind_key__    = 'homestack'

    # int: the ID of this role
    role_id         = Column(INTEGER(unsigned=True), primary_key=True)
    id              = synonym("role_id")

    # str: the name of this role
    name            = Column(VARCHAR(30), unique=True, nullable=False)

    # Helper relationship
    user_groups     = relationship("UserGroup", secondary=UserGroupToRole)


class ApiKey(hs_base, HomestackDatabase):
    """
    Class that represents our API Keys table
    """

    __tablename__   = 'ApiKeys'
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
