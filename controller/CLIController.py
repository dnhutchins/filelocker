import cherrypy
import re
import datetime
import Filelocker
from twisted.plugin import getPlugins, IPlugin
from lib.Constants import Actions
import sqlalchemy
from lib.SQLAlchemyTool import session
from Cheetah.Template import Template
from lib.Formatters import *
from lib.Models import *
from lib import AccountService, FileService
from directory import CLIDirectory
import directory
import plugins

__author__="dnhutchins"
__date__ ="$Apr 10, 2015 2:15:32 PM$"

class CLIController:

    validIPv4 = re.compile('^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')
    validIPv6 = re.compile('^\s*((([0-9A-Fa-f]{1,4}:){7}([0-9A-Fa-f]{1,4}|:))|(([0-9A-Fa-f]{1,4}:){6}(:[0-9A-Fa-f]{1,4}|((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){5}(((:[0-9A-Fa-f]{1,4}){1,2})|:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9A-Fa-f]{1,4}:){4}(((:[0-9A-Fa-f]{1,4}){1,3})|((:[0-9A-Fa-f]{1,4})?:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){3}(((:[0-9A-Fa-f]{1,4}){1,4})|((:[0-9A-Fa-f]{1,4}){0,2}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){2}(((:[0-9A-Fa-f]{1,4}){1,5})|((:[0-9A-Fa-f]{1,4}){0,3}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9A-Fa-f]{1,4}:){1}(((:[0-9A-Fa-f]{1,4}){1,6})|((:[0-9A-Fa-f]{1,4}){0,4}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(:(((:[0-9A-Fa-f]{1,4}){1,7})|((:[0-9A-Fa-f]{1,4}){0,5}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:)))(%.+)?\s*$')

    @cherrypy.expose
    def CLI_login(self, CLIkey, userId, format="cli", **kwargs):
        rootURL, local, sMessages, fMessages = cherrypy.request.app.config['filelocker']['root_url'], False, [], []
        if session.query(ConfigParameter).filter(ConfigParameter.name == "cli_feature").one().value == 'Yes':
            userId = strip_tags(userId)
            CLIkey = strip_tags(CLIkey)
            hostIP = Filelocker.get_client_address()
            if(self.validIPv4.match(hostIP)):
                hostIPv4 = hostIP
                hostIPv6 = ""
            elif(self.validIPv6.match(hostIP)):
                hostIPv4 = ""
                hostIPv6 = hostIP 
        
            self.directory = CLIDirectory.CLIDirectory()
            if self.directory.authenticate(userId, CLIkey, hostIPv4, hostIPv6):
                currentUser = AccountService.get_user(userId, True)
                cherrypy.session['request-origin'] = str(os.urandom(32).encode('hex'))[0:32]
                if currentUser is not None:
                    session.add(AuditLog(cherrypy.session.get("user").id, "Login", "User %s logged in successfully from IP %s" % (currentUser.id, Filelocker.get_client_address())))
                    session.commit()
                    sMessages.append(cherrypy.session['request-origin'])
                else:
                    fMessages.append("Failure: Not Authorized!")
            else:
                fMessages.append("Failure: Not Authorized!")
        else:
            fMessages.append("Failure: CLI not supported by server!")
        return fl_response(sMessages, fMessages, format)


if __name__ == "__main__":
    pass
