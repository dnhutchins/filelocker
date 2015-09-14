# -*- coding: utf-8 -*-
import cherrypy
from Cheetah.Template import Template
from lib.SQLAlchemyTool import session
from lib import AccountService
from lib.Constants import Actions
from lib.Formatters import *
from lib.Models import *
from lib import Mail
from lib import ShareService
__author__="wbdavis"
__date__ ="$Sep 25, 2011 9:28:23 PM$"

class ShareController:

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def create_user_shares(self, fileIds, userId=None, notify="no", cc="false", format="json", requestOrigin="", **kwargs):
        config = cherrypy.request.app.config['filelocker']
        orgConfig = get_config_dict_from_objects(session.query(ConfigParameter).filter(ConfigParameter.name.like('org_%')).all())
        user, role, sMessages, fMessages  = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileIds = split_list_sanitized(fileIds)
            userId = strip_tags(userId) if userId is not None and userId != "" else None
            notify = True if notify.lower() == "true" else False
            cc = True if cc.lower() == "true" else False
            sharedFiles, recipients = [], []
            try:
                if userId is not None:
                    shareUser = AccountService.get_user(userId)
                    if (shareUser.email is not None and shareUser.email != ""):
                        recipients.append(shareUser)
                    for fileId in fileIds:
                        flFile = session.query(File).filter(File.id==fileId).one()
                        
                        if (role is not None and flFile.role_owner_id == role.id) or flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                            existingShare = session.query(UserShare).filter(and_(UserShare.file_id==fileId, UserShare.user_id==userId)).scalar()
                            if existingShare is None:
                                flFile.user_shares.append(UserShare(user_id=userId, file_id=fileId))
                                session.commit()
                                sharedFiles.append(flFile)
                                if role is not None: session.add(AuditLog(user.id, Actions.CREATE_USER_SHARE, "Role %s shared file %s(%s) with %s" % (role.id, flFile.name, flFile.id, shareUser.id), shareUser.id, role.id))
                                else: session.add(AuditLog(user.id, "Create User Share", "%s shared file %s(%s) with %s" % (user.id, flFile.name, flFile.id, shareUser.id), shareUser.id))
                                session.commit()
                        else:
                            fMessages.append("You do not have permission to share file with ID: %s" % str(flFile.id))
                    if notify:
                        cherrypy.session.release_lock()
                        if cc:
                            if (user is not None and user != ""):
                                recipients.append(user)
                            else:
                                fMessages.append("You elected to receive a carbon copy of the share notification, however your account does not have an email address set.")
                        for recipient in recipients:
                            try:
                                Mail.notify(get_template_file('share_notification.tmpl'),{'sender':user.email if role is None else role.email,'recipient':recipient.email, 'ownerId':user.id if role is None else role.id, 'ownerName':user.display_name if role is None else role.name, 'sharedFiles':sharedFiles, 'filelockerURL': config['root_url'], 'org_url': orgConfig['org_url'], 'org_name': orgConfig['org_name'], 'personalMessage': ""})
                                session.add(AuditLog(user.id, Actions.SEND_EMAIL, "%s(%s) has been notified via email that you have shared a file with him or her." % (recipient.display_name, recipient.id), None, role.id if role is not None else None))
                            except Exception, e:
                                session.rollback()
                                fMessages.append("Problem sending email notification to %s: %s" % (recipient.display_name, str(e)))
                        session.commit()
                    sMessages.append("Shared file(s) successfully")
                else:
                    fMessages.append("You did not specify a user to share the file with")
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_user_shares(self, fileIds, userId, format="json", requestOrigin=""):
        user, role, sMessages, fMessages = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileIds = split_list_sanitized(fileIds)
            for fileId in fileIds:
                try:
                    flFile = session.query(File).filter(File.id==fileId).one()
                    if (role is not None and flFile.role_owner_id == role.id) or flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                        ps = session.query(UserShare).filter(and_(UserShare.user_id == userId, UserShare.file_id == flFile.id)).scalar()
                        if ps is not None:
                            session.delete(ps)
                            session.add(AuditLog(user.id, Actions.DELETE_USER_SHARE, "You stopped sharing file %s with %s" % (flFile.name, userId), None, role.id if role is not None else None))
                            session.commit()
                            sMessages.append("Share has been successfully deleted")
                        else:
                            fMessages.append("This share does not exist")
                    else:
                        fMessages.append("You do not have permission to modify shares for file with ID: %s" % str(flFile.id))
                except Exception, e:
                    session.rollback()
                    fMessages.append("Problem deleting share for file: %s" % str(e))
        return fl_response(sMessages, fMessages, format)

#    @cherrypy.expose
#    @cherrypy.tools.requires_login()
#    def share_file_with_everyone(self, fileId):
#        everyUser = session.query(User).all()
#        flFile = session.query(File).filter(File.id==fileId).one()
#        for user in everyUser:
#            file.user_shares.append(UserShare(user_id=user.id, file_id=fileId))

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def create_group_shares(self, fileIds, groupId, notify="false", cc="false", format="json", requestOrigin=""):
        user, role, sMessages, fMessages, config  = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [], cherrypy.request.app.config['filelocker'])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            orgConfig = get_config_dict_from_objects(session.query(ConfigParameter).filter(ConfigParameter.name.like('org_%')).all())
            fileIds = split_list_sanitized(fileIds)
            groupId = strip_tags(groupId) if groupId is not None and groupId != "" else None
            notify = True if notify.lower() == "true" else False
            cc = True if cc.lower() == "true" else False
            try:
                if groupId is not None:
                    sharedFiles = []
                    group = session.query(Group).filter(Group.id==groupId).one()
                    if (role is not None and group.role_owner_id == role.id) or group.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                        for fileId in fileIds:
                            flFile = session.query(File).filter(File.id == fileId).one()
                            existingShare = session.query(GroupShare).filter(and_(GroupShare.group_id==group.id, GroupShare.file_id==fileId)).scalar()
                            if existingShare is not None:
                                fMessages.append("File %s is already shared with group %s" % (flFile.name, group.name))
                            elif (role is not None and flFile.role_owner_id == role.id) or flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                                flFile.group_shares.append(GroupShare(group_id=groupId, file_id=fileId))
                                sharedFiles.append(flFile)
                            else:
                                fMessages.append("You do not have permission to share file with ID: %s" % fileId)
                        sMessages.append("Shared file(s) successfully")
                        if role is not None:
                            session.add(AuditLog(user.id, Actions.CREATE_GROUP_SHARE, "Role %s shared %s files with group %s(%s)" % (role.id, len(fileIds), group.name, group.id), None, role.id))
                        else:
                            session.add(AuditLog(user.id, Actions.CREATE_GROUP_SHARE, "%s shared %s files with group %s(%s)" % (user.id, len(fileIds), group.name, group.id), None))
                    else:
                        fMessages.append("You do not have permission to share with this group")
                    session.commit()
                    if notify:
                        cherrypy.session.release_lock()
                        for groupMember in group.members:
                            try:
                                Mail.notify(get_template_file('share_notification.tmpl'),{'sender':user.email if role is None else role.email,'recipient':groupMember.email, 'ownerId':user.id if role is None else role.id, 'ownerName':user.display_name if role is None else role.name, 'sharedFiles':sharedFiles, 'filelockerURL': config['root_url'], 'org_url': orgConfig['org_url'], 'org_name': orgConfig['org_name']})
                                session.add(AuditLog(user.id, Actions.SEND_EMAIL, "%s has been notified via email that you have shared a file with him or her." % (groupMember.email), None, role.id if role is not None else None))
                                session.commit()
                            except Exception, e:
                                session.rollback()
                                fMessages.append("Problem sending email notification to %s: %s" % (groupMember.display_name, str(e)))
                        if cc:
                            if (user.email is not None and user.email != ""):
                                try:
                                    Mail.notify(get_template_file('share_notification.tmpl'),{'sender':user.email if role is None else role.email,'recipient':user.email if role is None else role.email, 'ownerId':user.id if role is None else role.id, 'ownerName':user.display_name if role is None else role.name, 'sharedFiles':sharedFiles, 'filelockerURL': config['root_url'], 'org_url': orgConfig['org_url'], 'org_name': orgConfig['org_name']})
                                    session.add(AuditLog(user.id, Actions.SEND_EMAIL, "You have been carbon copied via email on the notification that was sent out as a result of your file share."))
                                    session.commit()
                                except Exception, e:
                                    session.rollback()
                                    fMessages.append("Problem carbon copying email notification: %s" % (str(e)))
                            else:
                                fMessages.append("You elected to receive a carbon copy of the share notification, however your account does not have an email address set.")
            except Exception, e:
                session.rollback()
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_group_shares(self, fileIds, groupId, format="json", requestOrigin=""):
        user, role, sMessages, fMessages = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileIds = split_list_sanitized(fileIds)
            for fileId in fileIds:
                try:
                    group = session.query(Group).filter(Group.id==groupId).one()
                    if (role is not None and group.role_owner_id == role.id) or group.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                        flFile = session.query(File).filter(File.id==fileId).one()
                        if (role is not None and flFile.role_owner_id == role.id) or flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                            share = session.query(GroupShare).filter(GroupShare.group_id == groupId and GroupShare.file_id == flFile.id).scalar()
                            if share is not None:
                                session.delete(share)
                                session.add(AuditLog(user.id, Actions.DELETE_GROUP_SHARE, "You stopped sharing file %s with group %s" % (flFile.name, group.name), None, role.id if role is not None else None))
                                session.commit()
                        else:
                            fMessages.append("You do not have permission to modify shares for file with ID: %s" % str(flFile.id))
                    else:
                        fMessages.append("You do not have permission delete shares with this group")
                except Exception, e:
                    session.rollback()
                    fMessages.append("Problem deleting share for file: %s" % str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def get_files_shared_with_user(self, format="json", **kwargs):
        #Determine which files are shared with the user
        user, sMessages, fMessages, sharedFiles = (cherrypy.session.get("user"), [], [], [])
        try:
            hiddenFileIds = []
            hiddenShares = session.query(HiddenShare).filter(HiddenShare.owner_id == user.id).all()
            for hiddenShare in hiddenShares:
                hiddenFileIds.append(hiddenShare.file_id)
            for flFile in ShareService.get_files_shared_with_user(user):
                if flFile.id not in hiddenFileIds:
                    sharedFiles.append(flFile.get_dict())
        except Exception, e:
            cherrypy.log.error("[%s] [get_files_shared_with_user] [Couldn't get files shared with user: %s]" % (user.id, str(e)))
            fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format, data=sharedFiles)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def unhide_shares(self, format="json", requestOrigin="",**kwargs):
        user, sMessages, fMessages  = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                session.query(HiddenShare).filter(HiddenShare.owner_id==user.id).delete(synchronize_session=False)
                session.commit()
                sMessages.append("All shares have been unhidden")
            except Exception, e:
                fMessages.append("Could not unhide shares: %s" % str(e))
                cherrypy.log.error("[%s] [unhide_shares] [Could not unhide shares: %s]" % (user.id, str(e)))
        return fl_response(sMessages, fMessages, format)
        
    
    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def hide_shares(self, fileIds, format="json", requestOrigin="", **kwargs):
        user, sMessages, fMessages  = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                fileIds = split_list_sanitized(fileIds)
                for fileId in fileIds:
                    session.add(HiddenShare(file_id=fileId, owner_id=user.id))
                session.commit()
                sMessages.append("Share has been hidden")
            except Exception, e:
                fMessages.append("Could not hide share: %s" % str(e))
                cherrypy.log.error("[%s] [unhide_shares] [Could not unhide shares: %s]" % (user.id, str(e)))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def create_attribute_shares(self, fileIds, attributeId, format="json", requestOrigin="", **kwargs):
        user, sMessages, fMessages  = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                userShareableAttributes, permission = AccountService.get_shareable_attributes_by_user(user), False
                for attribute in userShareableAttributes:
                    if attributeId == attribute.id:
                        permission = True
                        break
                if permission:
                    fileIds = split_list_sanitized(fileIds)
                    for fileId in fileIds:
                        session.add(AttributeShare(file_id=fileId, attribute_id=attributeId))
                    sMessages.append("Successfully shared file(s) with users having the %s attribute" % attributeId )
                else:
                    fMessages.append("You do not have permission to share with this attribute")
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_attribute_shares(self, fileIds, attributeId, format="json", requestOrigin="", **kwargs):
        user, sMessages, fMessages  = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                userShareableAttributes, permission = AccountService.get_shareable_attributes_by_user(user), False
                for attribute in userShareableAttributes:
                    if attributeId == attribute.id:
                        permission = True
                        break
                if permission:
                    fileIdList = split_list_sanitized(fileIds)
                    for fileId in fileIdList:
                        share = session.query(AttributeShare).filter(AttributeShare.attribute_id==attributeId and AttributeShare.fileId==fileId).one()
                        session.delete(share)
                    sMessages.append("Successfully unshared file(s) with users having the %s attribute" % attributeId)
                else:
                    fMessages.append("You do not have permission to delete attribute shares for this attribute")
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def create_public_share(self, fileIds, expiration, shareType, message, notifyEmails, cc="false", format="json", requestOrigin="", **kwargs):
        user, role, sMessages, fMessages, shareId, ps = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [], None, None)
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            config = cherrypy.request.app.config['filelocker']
            orgConfig = get_config_dict_from_objects(session.query(ConfigParameter).filter(ConfigParameter.name.like('org_%')).all())
            fileIds = split_list_sanitized(fileIds)
            cc = True if cc == "true" else False
            try:
                try:
                    expiration = datetime.datetime(*(time.strptime(strip_tags(expiration), "%m/%d/%Y")[0:6]))
                except Exception, e:
                    raise Exception("Invalid expiration date format. Date must be in mm/dd/yyyy format.")
                if expiration is None or expiration == "":
                    raise Exception("Public shares must have a valid expiration date")
                message = strip_tags(message)
                shareType = "single" if shareType != "multi" else "multi"
                ps = PublicShare(date_expires=expiration, reuse=shareType, message=message)
                if role is not None:
                    ps.role_owner_id = role.id
                else:
                    ps.owner_id = user.id
                    
                if (kwargs.has_key("password") and kwargs['password']!=""):
                    ps.set_password(kwargs['password'])
                elif shareType=="multi":
                    raise Exception("You must specify a password for public shares that don't expire after 1 use")
    
                ps.generate_share_id()
                session.add(ps)
                sharedFiles = []
                for fileId in fileIds:
                    flFile = session.query(File).filter(File.id==fileId).one()
                    if flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                        ps.files.append(flFile)
                        session.commit()
                        sharedFiles.append(flFile)
                        session.commit()
                    else:
                        fMessages.append("You do not have permission to share file with ID: %s" % str(flFile.id))
                session.add(AuditLog(user.id, Actions.CREATE_PUBLIC_SHARE, "%s file(s) publicly shared." % len(ps.files), None, role.id if role is not None else None))
                notifyEmailList = split_list_sanitized(notifyEmails)
                if cc:
                    if (user.email is not None and user.email != ""):
                        notifyEmailList.append(user.email)
                    else:
                        fMessages.append("You elected to receive a carbon copy of the share notification, however your account does not have an email address set.")
                cherrypy.session.release_lock()
                for recipient in notifyEmailList:
                    if recipient is not None and recipient != "":
                        Mail.notify(get_template_file('public_share_notification.tmpl'), {'sender':user.email if role is None else role.email, 'recipient':recipient, 'sharedFiles':sharedFiles, 'ownerId':user.id if role is None else role.id, 'ownerName': user.display_name if role is None else role.name, 'shareId':ps.id, 'filelockerURL':config['root_url'], 'org_url': orgConfig['org_url'], 'org_name': orgConfig['org_name'], 'personalMessage': message})
                if len(notifyEmailList) > 0:
                    session.add(AuditLog(user.id, Actions.SEND_EMAIL, "Email notifications about a public share were sent to the following addresses: %s" % ",".join(notifyEmailList), None, role.id if role is not None else None))
                session.commit()
                shareId = ps.id
                sMessages.append("Files shared successfully")
            except Exception, e:
                session.rollback()
                fMessages.append(str(e))
                cherrypy.log.error("[%s] [create_public_share] [Unable to create public share: %s]" % (user.id, str(e)))
        return fl_response(sMessages, fMessages, format, data=shareId)
    
    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_public_shares_by_file_ids(self, fileIds, format="json", requestOrigin="", **kwargs):
        user, role, sMessages, fMessages = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileIds = split_list_sanitized(fileIds)
            try:
                for fileId in fileIds:
                    try:
                        flFile = session.query(File).filter(File.id==fileId).one()
                        if role is not None:
                            if flFile.role_owner_id == role.id:
                                for publicShare in flFile.public_shares:
                                    publicShare.files.remove(flFile)
                            else:
                                fMessages.append("This role does not have permissions to modify public shares on file with ID: %s" % fileId)
                        else:
                            if flFile.owner_id == user.id:
                                for publicShare in flFile.public_shares:
                                    publicShare.files.remove(flFile)
                            else:
                                fMessages.append("You do not have permission to modify public shares on file with ID: %s" % fileId)
                    except sqlalchemy.orm.exc.NoResultFound:
                        fMessages.append("File with ID:%s not found" % fileId)
            except Exception,e:
                fMessages.append("Could delete public shares by file ids: %s" % str(e))
                cherrypy.log.error("[%s] [delete_public_shares_by_file_ids] [Could delete public shares by file ids: %s]" % (user.id, str(e)))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_public_share(self, shareId, format="json", requestOrigin="", **kwargs):
        user, role, sMessages, fMessages = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            shareId = strip_tags(shareId)
            try:
                ps = session.query(PublicShare).filter(PublicShare.id == shareId).one()
                if role is not None and ps.role_owner_id == role.id:
                    session.delete(ps)
                    session.add(AuditLog(user.id, Actions.DELETE_PUBLIC_SHARE, "Role %s stopped sharing files publicly via URL using share ID: %s" % (role.name, str(ps.id)), None, role.id))
                    session.commit()
                    sMessages.append("Successfully unshared files")
                elif ps.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                    session.delete(ps)
                    session.add(AuditLog(user.id, Actions.DELETE_PUBLIC_SHARE, "You stopped sharing files publicly via URL using share ID: %s" % str(ps.id)))
                    session.commit()
                    sMessages.append("Successfully unshared files")
                else:
                    fMessages.append("You do not have permission to modify share ID: %s" % str(ps.id))
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def get_public_shares_by_file_ids(self, fileIds, format="json", **kwargs):
        user, role, sMessages, fMessages, publicShares = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [], [])
        fileIds = split_list_sanitized(fileIds)
        try:
            publicShareIds = []
            for fileId in fileIds:
                try:
                    flFile = session.query(File).filter(File.id==fileId).one()
                    if role is not None:
                        if flFile.role_owner_id == role.id:
                            for publicShare in flFile.public_shares:
                                if publicShare.id not in publicShareIds:
                                    publicShareIds.append(publicShare.id)
                                    publicShares.append(publicShare)
                        else:
                            fMessages.append("This role does not have permission to access public shares on file with ID: %s" % fileId)
                    elif flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                        for publicShare in flFile.public_shares:
                            if publicShare.id not in publicShareIds:
                                publicShareIds.append(publicShare.id)
                                publicShares.append(publicShare)
                    else:
                        fMessages.append("You do not have permission to access public shares on file with ID:%s" % fileId)
                except sqlalchemy.orm.exc.NoResultFound:
                    fMessages.append("File with ID:%s not found" % fileId)
        except Exception, e:
            fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format, data=publicShares)


    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def unhide_all_shares(self, format="json", requestOrigin=""):
        user, sMessages, fMessages = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                session.query(HiddenShare).filter(HiddenShare.owner_id==user.id).delete()
                session.commit()
                sMessages.append("Successfully unhid shares")
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def hide_share(self, fileIds, format="json", requestOrigin=""):
        user, sMessages, fMessages = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileIds = split_list_sanitized(fileIds)
            for fileId in fileIds:
                try:
                    session.add(HiddenShare(file_id=fileId, owner_id=user.id))
                except Exception, e:
                    fMessages.append(str(e))
            sMessages.append("Successfully hid shares. Unhide shares in Account Settings.")
            session.commit()
        return fl_response(sMessages, fMessages, format)
