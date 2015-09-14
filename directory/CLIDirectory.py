import cherrypy
from lib.SQLAlchemyTool import session
import lib.Encryption
from lib.Models import *
import sqlalchemy
__author__="dnhutchins"
__date__ ="$Apr 10, 2015 2:48:08 PM$"

class CLIDirectory(object):

    def lookup_user(self, userId):
        return session.query(User).filter(User.id == userId).scalar()

    def authenticate(self, userId, cliKey, hostIPv4, hostIPv6):
        isValid = False
        try:
            hostKey = session.query(CLIKey).filter(CLIKey.user_id == userId).filter(CLIKey.host_ipv4 == hostIPv4).filter(CLIKey.host_ipv6 == hostIPv6).one()
            if hostKey.value == cliKey:
                isValid = True
            else:
                isValid = False
        except sqlalchemy.orm.exc.NoResultFound:
            isValid = False
        except Exception, e:
            cherrypy.log.error("[system] [authenticate] [Problem authenticating CLIKey: %s" % str(e))
            isValid = False
        return isValid

