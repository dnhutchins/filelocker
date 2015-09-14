# -*- coding: utf-8 -*-
import os
import stat
import shutil
import Filelocker
from stat import ST_SIZE
import random
import cherrypy
from cherrypy.lib import cptools, http, file_generator_limited
import mimetypes
mimetypes.init()
mimetypes.types_map['.dwg']='image/x-dwg'
mimetypes.types_map['.ico']='image/x-icon'
import datetime
import subprocess
from Cheetah.Template import Template
from lib.SQLAlchemyTool import session
import sqlalchemy
from sqlalchemy import *
from sqlalchemy.sql import select, delete, insert
from lib.Models import *
from lib.Constants import Actions
from lib.Formatters import *
from lib import Mail
from lib import Encryption
from lib import AccountService
from lib import FileService
# Cherrypy 3.2+ _cpreqbody replaces usage of standard lib cgi, safemime, and cpcgifs
#from lib.FileFieldStorage import FileFieldStorage, ProgressFile
from lib.FileFieldStorage import ProgressFile
__author__="wbdavis"
__date__ ="$Sep 25, 2011 9:28:54 PM$"

class FileController(object):

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def get_quota_usage(self, format="json", **kwargs):
        user, sMessages, fMessages, quotaMB, quotaUsedMB = (cherrypy.session.get("user"),[], [], 0, 0)
        try:
            quotaMB, quotaUsage = 0,0
            if cherrypy.session.get("current_role") is not None:
                quotaMB = cherrypy.session.get("current_role").quota
                quotaUsage = FileService.get_role_quota_usage_bytes(cherrypy.session.get("current_role").id)
            else:
                quotaMB = user.quota
                quotaUsage = FileService.get_user_quota_usage_bytes(user.id)
            quotaUsedMB = int(quotaUsage) / 1024 / 1024
        except Exception, e:
            fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format, data={'quotaMB': quotaMB , 'quotaUsedMB': quotaUsedMB})

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def get_download_statistics(self, fileId, startDate=None, endDate=None, format="json", **kwargs):
        user, role, sMessages, fMessages, stats = (cherrypy.session.get("user"), cherrypy.session.get("current_role"),  [], [], None)
        try:
            flFile = session.query(File).filter(File.id == fileId).one()
            startDateFormatted, endDateFormatted = None, None
            thirtyDays = datetime.timedelta(days=30)
            today = datetime.datetime.now()
            thirtyDaysAgo = today - thirtyDays
            if startDate is not None:
                startDateFormatted = datetime.datetime(*time.strptime(strip_tags(startDate), "%m/%d/%Y")[0:5])
            else:
                startDateFormatted =  thirtyDaysAgo
            if endDate is not None:
                endDateFormatted = datetime.datetime(*time.strptime(strip_tags(endDate), "%m/%d/%Y")[0:5])
            else:
                endDateFormatted = today


            if (role is not None and flFile.role_owner_id == role.id) or flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                if endDateFormatted is not None:
                    endDateFormatted = endDateFormatted + datetime.timedelta(days=1)

                uniqueDownloads = session.query(func.date(AuditLog.date), func.count(distinct(AuditLog.initiator_user_id))).\
                filter(AuditLog.action==Actions.DOWNLOAD).\
                filter(AuditLog.file_id == flFile.id).\
                filter(AuditLog.date < endDateFormatted).\
                filter(AuditLog.date > startDateFormatted).\
                group_by(func.date(AuditLog.date)).all()
                uniqueDownloadStats = []
                for row in uniqueDownloads:
                    uniqueDownloadStats.append((row[0].strftime("%m/%d/%Y"), row[1]))

                totalDownloads = session.query(func.date(AuditLog.date), func.count(AuditLog.initiator_user_id)).\
                filter(AuditLog.action==Actions.DOWNLOAD).\
                filter(AuditLog.file_id == flFile.id).\
                filter(AuditLog.date < endDateFormatted).\
                filter(AuditLog.date > startDateFormatted).\
                group_by(func.date(AuditLog.date)).all()
                totalDownloadStats = []
                for row in totalDownloads:
                    totalDownloadStats.append((row[0].strftime("%m/%d/%Y"), row[1]))
                stats = {"total":totalDownloadStats, "unique":uniqueDownloadStats}
        except sqlalchemy.orm.exc.NoResultFound, nrf:
            fMessages.append("Could not find file with ID: %s" % str(fileId))
        except Exception, e:
            fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format, data=stats)
        
    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def get_user_file_list(self, fileIdList=None, format="json", **kwargs):
        """Get File List"""
        config = cherrypy.request.app.config['filelocker']
        orgConfig = get_config_dict_from_objects(session.query(ConfigParameter).filter(ConfigParameter.name.like('org_%')).all())
        user, role, sMessages, fMessages = (cherrypy.session.get("user"), cherrypy.session.get("current_role"), [], [])
        myFilesList = []
        hiddenShares = session.query(HiddenShare).filter(HiddenShare.owner_id==user.id).all()
        hiddenShareIds = []
        for hiddenShare in hiddenShares:
            hiddenShareIds.append(hiddenShare.file_id)
        if fileIdList is None:
            allFilesList = session.query(File).filter(File.owner_id == user.id).all() if role is None else session.query(File).filter(File.role_owner_id==role.id).all()
            for flFile in allFilesList:
                if flFile.id not in hiddenShareIds:
                    myFilesList.append(flFile)
        else:
            fileIdList = split_list_sanitized(fileIdList)
            for fileId in fileIdList:
                flFile = session.query(File).filter(File.id==fileId).one()
                if (role is not None and flFile.role_owner_id == role.id) or (flFile.owner_id == user.id or flFile.shared_with(user)) and flFile.id not in hiddenShareIds:
                    myFilesList.append(flFile)
        for flFile in myFilesList: #attachments to the file objects for this function, purely cosmetic
            if (len(flFile.public_shares) > 0) and (len(flFile.user_shares) > 0 or len(flFile.group_shares) > 0 ):
                flFile.documentType = "document_both"
            elif len(flFile.public_shares) > 0:
                flFile.documentType = "document_globe"
            elif len(flFile.public_shares) == 0 and (len(flFile.user_shares) > 0 or len(flFile.group_shares) > 0):
                flFile.documentType = "document_person"
            else:
                flFile.documentType = "document"
            #TODO: Account for attribute shares here 'document_attribute'
        if format=="json" or format=="searchbox_html" or format=="cli":
            myFilesJSON = []
            userShareableAttributes = AccountService.get_shareable_attributes_by_user(user) if role is None else AccountService.get_shareable_attributes_by_role(role)
            for flFile in myFilesList:
                flFile.fileUserShares, flFile.fileGroupShares, flFile.availableGroups, sharedGroupsList, flFile.fileAttributeShares = ([],[],[],[],[])
                for share in flFile.user_shares:
                    flFile.fileUserShares.append({'id': share.user.id, 'name': share.user.display_name})
                sharedGroupIds = []
                for share in flFile.group_shares:
                    sharedGroupIds.append(share.group.id)
                    flFile.fileGroupShares.append({'id': share.group.id, 'name': share.group.name})
                for share in flFile.attribute_shares:
                    flFile.fileAttributeShares.append({'id': share.attribute.id, 'name': share.attribute.name})
                for group in session.query(Group).filter(Group.owner_id==user.id):
                    if group.id not in sharedGroupIds:
                        flFile.availableGroups.append({'id': group.id, 'name': group.name})
                myFilesJSON.append({'fileName': flFile.name, 'fileId': flFile.id, 'fileOwnerId': flFile.owner_id, 'fileSizeBytes': flFile.size, 'fileUploadedDatetime': flFile.date_uploaded.strftime("%m/%d/%Y"), 'fileExpirationDatetime': flFile.date_expires.strftime("%m/%d/%Y") if flFile.date_expires is not None else "Never", 'filePassedAvScan':flFile.passed_avscan, 'documentType': flFile.documentType, 'fileUserShares': flFile.fileUserShares, 'fileGroupShares': flFile.fileGroupShares, 'availableGroups': flFile.availableGroups, 'fileAttributeShares': flFile.fileAttributeShares})
            if format=="json":
                return fl_response(sMessages, fMessages, format, data=myFilesJSON)
            elif format=="searchbox_html":
                selectedFileIds = ",".join(fileIdList)
                context = "private_sharing"
                groups = session.query(Group).filter(Group.owner_id == user.id).all()
                directoryType = session.query(ConfigParameter).filter(ConfigParameter.name=="directory_type").one().value
                searchWidget = str(Template(file=get_template_file('search_widget.tmpl'), searchList=[locals(),globals()]))
                tpl = Template(file=get_template_file('share_files.tmpl'), searchList=[locals(),globals()])
                return str(tpl)
            elif format=="cli":
                myFilesJSON = sorted(myFilesJSON, key=lambda k: k['fileId'])
                myFilesXML = ""
                for myFile in myFilesJSON:
                    myFilesXML += "<file id='%s' name='%s' size='%s' passedAvScan='%s'></file>" % (myFile['fileId'], myFile['fileName'], myFile['fileSizeBytes'], myFile['filePassedAvScan'])
                return fl_response(sMessages, fMessages, format, data=myFilesXML)
        elif format=="list":
            return myFilesList
        else:
            return str(myFilesList)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def take_file(self, fileId, format="json", requestOrigin="", **kwargs):
        user, sMessages, fMessages = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            config = cherrypy.request.app.config['filelocker']
            try:
                flFile = session.query(File).filter(File.id==fileId).one()
                if flFile.owner_id == user.id:
                    fMessages.append("You cannot take your own file")
                elif flFile.shared_with(user) or AccountService.user_has_permission(user, "admin"):
                    if (FileService.get_user_quota_usage_bytes(user) + flFile.size) >= (user.quota*1024*1024):
                        cherrypy.log.error("[%s] [take_file] [User has insufficient quota space remaining to check in file: %s]" % (user.id, flFile.name))
                        raise Exception("You may not copy this file because doing so would exceed your quota")
                    takenFile = flFile.get_copy()
                    takenFile.owner_id = user.id
                    takenFile.date_uploaded = datetime.datetime.now()
                    takenFile.notify_on_download = False
                    session.add(takenFile)
                    session.commit()
                    shutil.copy(os.path.join(config['vault'],str(flFile.id)), os.path.join(config['vault'],str(takenFile.id)))
                    sMessages.append("Successfully took ownership of file %s. This file can now be shared with other users just as if you had uploaded it. " % flFile.name)
                else:
                    fMessages.append("You do not have permission to take this file")
            except sqlalchemy.orm.exc.NoResultFound, nrf:
                fMessages.append("Could not find file with ID: %s" % str(fileId))
            except Exception, e:
                session.rollback()
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_files(self, fileIds, format="json", requestOrigin="", **kwargs):
        user, role, sMessages, fMessages = (cherrypy.session.get("user"),cherrypy.session.get("current_role"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileIds = split_list_sanitized(fileIds)
            for fileId in fileIds:
                try:
                    fileId = int(fileId)
                    flFile = session.query(File).filter(File.id == fileId).one()
                    if flFile.role_owner_id is not None and role is not None and flFile.role_owner_id == role.id:
                        FileService.queue_for_deletion(flFile.id)
                        session.delete(flFile)
                        session.add(AuditLog(user.id, Actions.DELETE_FILE, "File %s (%s) owned by role %s has been deleted by user %s. " % (flFile.name, flFile.id, role.name, user.id)))
                        session.commit()
                        sMessages.append("File %s deleted successfully" % flFile.name)
                    elif flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                        FileService.queue_for_deletion(flFile.id)
                        session.delete(flFile)
                        session.add(AuditLog(user.id, Actions.DELETE_FILE, "File %s (%s) has been deleted" % (flFile.name, flFile.id)))
                        session.commit()
                        sMessages.append("File %s deleted successfully" % flFile.name)
                    else:
                        fMessages.append("You do not have permission to delete file %s" % flFile.name)
                except sqlalchemy.orm.exc.NoResultFound, nrf:
                    fMessages.append("Could not find file with ID: %s" % str(fileId))
                except Exception, e:
                    session.rollback()
                    cherrypy.log.error("[%s] [delete_files] [Could not delete file: %s]" % (user.id, str(e)))
                    fMessages.append("File not deleted: %s" % str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def update_file(self, fileId, format="json", requestOrigin="", **kwargs):
        user,  sMessages, fMessages = (cherrypy.session.get("user"), [], [])
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            fileId = strip_tags(fileId)
            try:
                flFile = session.query(File).filter(File.id==fileId).one()
                if flFile.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                    if kwargs.has_key("fileName"):
                        flFile.name = strip_tags(kwargs['fileName'])
                    if kwargs.has_key('notifyOnDownload'):
                        flFile.notify_on_download = True if kwargs['notifyOnDownload'].lower()=="true" else False
                    if kwargs.has_key('fileNotes'):
                        flFile.notes = strip_tags(kwargs['fileNotes'])
                    session.commit()
                    sMessages.append("Successfully updated file %s" % flFile.name)
                else:
                    fMessages.append("You do not have permission to update file with ID: %s" % str(flFile.id))
            except sqlalchemy.orm.exc.NoResultFound, nrf:
                fMessages.append("Could not find file with ID: %s" % str(fileId))
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    @cherrypy.tools.before_upload()
    def upload(self, format="json", **kwargs):
        cherrypy.response.timeout = 86400
        user, role, uploadRequest, uploadKey, config, sMessages, fMessages, uploadIndex = None, None, None, None, cherrypy.request.app.config['filelocker'], [], [], None

        notify_user = False

        #Check Permission to upload since we can't wrap in requires login for public uploads
        if cherrypy.session.has_key("uploadRequest") and cherrypy.session.get("uploadRequest") is not None and cherrypy.session.get("uploadRequest").expired == False:
            uploadRequest = cherrypy.session.get("uploadRequest")
            user = AccountService.get_user(uploadRequest.owner_id)
            uploadKey = "%s:%s" % (user.id, uploadRequest.id)
            if uploadRequest.notify_user:
                notify_user = True
        else:
            #cherrypy.tools.requires_login()
            user, sMessages, fMessages = cherrypy.session.get("user"), cherrypy.session.get("sMessages"), cherrypy.session.get("fMessages")
            uploadKey = user.id
            if cherrypy.session.get("current_role") is not None:
                role = cherrypy.session.get("current_role")

        #Check upload size
        lcHDRS = {}
        for key, val in cherrypy.request.headers.iteritems():
            lcHDRS[key.lower()] = val
        try:
            fileSizeBytes = int(lcHDRS['content-length'])
        except KeyError, ke:
            fMessages.append("Request must have a valid content length")
            raise cherrypy.HTTPError(411, "Request must have a valid content length")
        fileSizeMB = ((fileSizeBytes/1024)/1024)
        vaultSpaceFreeMB, vaultCapacityMB = FileService.get_vault_usage()
        
        if (fileSizeMB*2) >= vaultSpaceFreeMB:
            cherrypy.log.error("[system] [upload] [File vault is running out of space and cannot fit this file. Remaining Space is %s MB, fileSizeBytes is %s]" % (vaultSpaceFreeMB, fileSizeBytes))
            fMessages.append("The server doesn't have enough space left on its drive to fit this file. The administrator has been notified.")
            raise cherrypy.HTTPError(413, "The server doesn't have enough space left on its drive to fit this file. The administrator has been notified.")
        quotaSpaceRemainingBytes = 0
        if role is not None:
            quotaSpaceRemainingBytes = (role.quota*1024*1024) - FileService.get_role_quota_usage_bytes(role.id)
        else:
            quotaSpaceRemainingBytes = (user.quota*1024*1024) - FileService.get_user_quota_usage_bytes(user.id)
        if fileSizeBytes > quotaSpaceRemainingBytes:
            fMessages.append("File size is larger than your quota will accommodate")
            raise cherrypy.HTTPError(413, "File size is larger than your quota will accommodate")

        #The server won't respond to additional user requests (polling) until we release the lock
        cherrypy.session.release_lock()

        newFile = File()
        newFile.size = fileSizeBytes
        #Get the file name
        fileName, tempFileName = None,None
        if fileName is None and lcHDRS.has_key('x-file-name'):
            fileName = lcHDRS['x-file-name']
        if kwargs.has_key("fileName"):
            fileName = kwargs['fileName']
        if fileName is not None and fileName.split("\\")[-1] is not None:
            fileName = fileName.split("\\")[-1]

        #Set upload index if it's found in the arguments
        if kwargs.has_key('uploadIndex'):
            uploadIndex = kwargs['uploadIndex']

        #Read file from client
        if lcHDRS['content-type'] == "application/octet-stream":
            file_object = FileService.get_temp_file()
            tempFileName = file_object.name.split(os.path.sep)[-1]
            #Create the progress file object and drop it into the transfer dictionary
            upFile = ProgressFile(8192, fileName, file_object, uploadIndex)
            if cherrypy.file_uploads.has_key(uploadKey): #Drop the transfer into the global transfer list
                cherrypy.file_uploads[uploadKey].append(upFile)
            else:
                cherrypy.file_uploads[uploadKey] = [upFile,]
            bytesRemaining = fileSizeBytes
            while True:
                if bytesRemaining >= 8192:
                    block = cherrypy.request.rfile.read(8192)
                else:
                    block = cherrypy.request.rfile.read(bytesRemaining)
                upFile.write(block)
                bytesRemaining -= 8192
                if bytesRemaining <= 0: break
            upFile.seek(0)
            #If the file didn't get all the way there
            if long(os.path.getsize(upFile.file_object.name)) != long(fileSizeBytes): #The file transfer stopped prematurely, take out of transfers and queue partial file for deletion
                cherrypy.log.error("[system] [upload] [File upload was prematurely stopped, rejected]")
                FileService.queue_for_deletion(tempFileName)
                fMessages.append("The file %s did not upload completely before the transfer ended" % fileName)
                if cherrypy.file_uploads.has_key(uploadKey):
                    for fileTransfer in cherrypy.file_uploads[uploadKey]:
                        if fileTransfer.file_object.name == upFile.file_object.name:
                            cherrypy.file_uploads[uploadKey].remove(fileTransfer)
                    if len(cherrypy.file_uploads[uploadKey]) == 0:
                        del cherrypy.file_uploads[uploadKey]
                raise cherrypy.HTTPError("412 Precondition Failed", "The file transfer completed, but the file appears to be missing data. If you did not intentionally cancel the file, please try re-uploading.")
        else:
            cherrypy.request.headers['uploadindex'] = uploadIndex
            # Cherrypy 3.2+ _cpreqbody replaces usage of standard lib cgi, safemime, and cpcgifs
            # I have no clue when we would be reaching this code, so, for the moment I am going to break it and see if I can't find a way to hit it :)
            #forms = cherrypy._cpcgifs.FieldStorage(fp=cherrypy.request.rfile, headers=lcHDRS,
                # FieldStorage only recognizes POST.  environ={'REQUEST_METHOD': "POST"}, keep_blank_values=1)
            cherrypy.log.error("!!!!!!!!!!!!!!!!!!! LOOK !!!!!!!!!!!!!!!!!")
            cherrypy.log.error("!!!!!!!!!!!!!!!!!!! HERE !!!!!!!!!!!!!!!!!")
            upFile = forms.list[0]
            if fileName is None:
                fileName = upFile.filename
            if str(type(upFile.file)) == '<type \'cStringIO.StringO\'>' or isinstance(upFile.file, StringIO.StringIO):
                newTempFile = FileService.get_temp_file()
                newTempFile.write(str(upFile.file.getvalue()))
                newTempFile.seek(0)
                upFile = ProgressFile(8192, fileName, newTempFile)
                if cherrypy.file_uploads.has_key(uploadKey): #Drop the transfer into the global transfer list
                    cherrypy.file_uploads[uploadKey].append(upFile)
                else:
                    cherrypy.file_uploads[uploadKey] = [upFile,]
            else:
                upFile = upFile.file
            tempFileName = upFile.file_object.name.split(os.path.sep)[-1]

        #The file has been successfully uploaded by this point, process the rest of the variables regarding the file
        newFile.name = fileName
        fileNotes = strip_tags(kwargs['fileNotes']) if kwargs.has_key("fileNotes") else ""
        if fileNotes is not None and len(fileNotes) > 256:
            fileNotes = fileNotes[0:256]
        newFile.notes = fileNotes

        #Owner ID is a separate variable since uploads can be owned by the system
        if role is not None:
            newFile.role_owner_id = role.id
        else:
            newFile.owner_id = user.id

        #Process date provided
        maxDays = int(session.query(ConfigParameter).filter(ConfigParameter.name=='max_file_life_days').one().value)
        maxExpiration = datetime.datetime.today() + datetime.timedelta(days=maxDays)
        expiration = kwargs['expiration'] if kwargs.has_key("expiration") else None
        if expiration is None or expiration == "" or expiration.lower() =="never":
            if role is not None and (AccountService.role_has_permission(role, "expiration_exempt") or AccountService.role_has_permission(role, "admin")):
                expiration = None
            elif AccountService.user_has_permission(user,  "expiration_exempt") or AccountService.user_has_permission(user, "admin"): #Check permission before allowing a non-expiring upload
                expiration = None
            else:
                expiration = maxExpiration
        else:
            expiration = datetime.datetime(*time.strptime(strip_tags(expiration), "%m/%d/%Y")[0:5])
            if expiration > maxExpiration and AccountService.user_has_permission(user,  "expiration_exempt")==False:
                fMessages.append("Expiration date was invalid. Expiration set to %s" % maxExpiration.strftime("%m/%d/%Y"))
                expiration = maxExpiration
        newFile.date_expires = expiration
        avCommand =  session.query(ConfigParameter).filter(ConfigParameter.name=="antivirus_command").one().value
        scanFile = True if (avCommand) else False
        newFile.notify_on_download = False
        newFile.date_uploaded = datetime.datetime.now()
        newFile.status = "Processing"
        newFile.upload_request_id = None if (uploadRequest is None) else uploadRequest.id

        #Set status to scanning
        if cherrypy.file_uploads.has_key(uploadKey):
            for fileTransfer in cherrypy.file_uploads[uploadKey]:
                if fileTransfer.file_object.name == upFile.file_object.name:
                    fileTransfer.status = "Scanning and Encrypting" if scanFile else "Encrypting"
        #Check in the file
        try:
            FileService.check_in_file(tempFileName, newFile)
            ### Moved to check_in_file so the record can be trashed if virus scan fails
            #session.add(newFile)
            #session.commit()
            #If this is an upload request, check to see if it's a single use request and nullify the ticket if so, now that the file has been successfully uploaded
            if uploadRequest is not None:
                if uploadRequest.type == "single":
                    session.add(AuditLog(Filelocker.get_client_address(), Actions.UPLOAD_REQUEST_FULFILLED, "File %s has been uploaded by an external user to your Filelocker account. This was a single user request and the request has now expired." % (newFile.name), uploadRequest.owner_id))
                    attachedUploadRequest = session.query(UploadRequest).filter(UploadRequest.id == uploadRequest.id).one()
                    session.delete(attachedUploadRequest)
                    cherrypy.session['uploadRequest'].expired = True
                else:
                    session.add(AuditLog(Filelocker.get_client_address(), Actions.UPLOAD_REQUEST_FULFILLED, "File %s has been uploaded by an external user to your Filelocker account." % (newFile.name), uploadRequest.owner_id))
            checkInLog = AuditLog(user.id, Actions.UPLOAD, "File %s (%s) checked in to Filelocker: MD5 %s " % (newFile.name, newFile.id, newFile.md5))
            if role is not None:
                checkInLog.affected_role_id = role.id
            session.add(checkInLog)
            sMessages.append("File %s uploaded successfully." % str(fileName))
            session.commit()
        except sqlalchemy.orm.exc.NoResultFound, nrf:
            fMessages.append("Could not find upload request with ID: %s" % str(uploadRequest.id))
        except Exception, e:
            cherrypy.log.error("[%s] [upload] [Couldn't check in file: %s]" % (user.id, str(e)))
            fMessages.append("File couldn't be checked in to the file repository: %s" % str(e))
        upFile.file_object.close()

        #At this point the file upload is done, one way or the other. Remove the ProgressFile from the transfer dictionary
        try:
            if cherrypy.file_uploads.has_key(uploadKey):
                for fileTransfer in cherrypy.file_uploads[uploadKey]:
                    if fileTransfer.file_object.name == upFile.file_object.name:
                        cherrypy.file_uploads[uploadKey].remove(fileTransfer)
                if len(cherrypy.file_uploads[uploadKey]) == 0:
                    del cherrypy.file_uploads[uploadKey]
        except KeyError, ke:
            cherrypy.log.error("[%s] [upload] [Key error deleting entry in file_transfer]" % user.id)

        #Send out upload notification to the file owner
        if notify_user:
            try:
                if user.email is not None and user.email != "":
                    orgConfig = get_config_dict_from_objects(session.query(ConfigParameter).filter(ConfigParameter.name.like('org_%')).all())
                    Mail.notify(get_template_file('upload_notification.tmpl'),{'sender': None, 'recipient': user.email, 'fileName': newFile.name, 'filelockerURL': config['root_url'], 'org_url': orgConfig['org_url'], 'org_name': orgConfig['org_name']})
            except Exception, e:
                cherrypy.log.error("[%s] [upload] [Unable to notify user %s of upload completion: %s]" % (user.id, user.id, str(e)))
                

        #Queue the temp file for secure erasure
        FileService.queue_for_deletion(tempFileName)

        #Return the response
        if format=="cli":
            newFileXML = "<file id='%s' name='%s'></file>" % (newFile.id, newFile.name)
            return fl_response(sMessages, fMessages, format, data=newFileXML)
        else:
            return fl_response(sMessages, fMessages, format)

    @cherrypy.expose
    def download(self, fileId, **kwargs):
        serveFile, publicShareId, requestedFile = False, None, None
        if cherrypy.session.has_key("public_share_id"):
            publicShareId = cherrypy.session.get("public_share_id")
            try:
                publicShare = session.query(PublicShare).filter(PublicShare.id == publicShareId).one()
                requestedFile = session.query(File).filter(File.id == fileId).one()
                if requestedFile in publicShare.files:
                    serveFile = True
                else:
                    raise cherrypy.HTTPError(401)
            except sqlalchemy.orm.exc.NoResultFound, nrf:
                raise cherrypy.HTTPError(404, "Could not find share or file")
        else:
            if not cherrypy.session.has_key("user"):
                raise cherrypy.HTTPRedirect(cherrypy.request.app.config['filelocker']['root_url'])
            else:
                user, role = cherrypy.session.get("user"), cherrypy.session.get("current_role")
                try:
                    requestedFile = session.query(File).filter(File.id==fileId).one()
                    if (role is not None and requestedFile.role_owner_id == role.id) or requestedFile.owner_id == user.id or requestedFile.shared_with(user) or AccountService.user_has_permission(user, "admin"):
                        serveFile = True
                except sqlalchemy.orm.exc.NoResultFound, nrf:
                    raise cherrypy.HTTPError(404, "Could not find file")

        cherrypy.response.timeout = 36000
        cherrypy.session.release_lock()

        if serveFile:
            return self.serve_file(requestedFile, publicShareId=publicShareId)
        else:
            raise cherrypy.HTTPError(403, "You do not have access to this file")

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def create_upload_request(self, password, expiration, requestType, maxFileSize=None, cc="false", notifyUser="false", emailAddresses=None, personalMessage=None, format="json", requestOrigin="", **kwargs):
        user, config, uploadURL, sMessages, fMessages = cherrypy.session.get("user"),cherrypy.request.app.config['filelocker'],"", [], []
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                expiration = parse_date(expiration, datetime.datetime.now())
            except Exception, e:
                fMessages.append(str(e))
            try:
                cc = True if cc.lower() == "true" else False
                notifyUser = True if notifyUser.lower() == "true" else False
                print "DEBUG: notifyUser = " + str(notifyUser)
                maxFileSize = int(strip_tags(maxFileSize)) if (maxFileSize == "" or maxFileSize=="0" or maxFileSize == 0) else None
                if maxFileSize is not None and maxFileSize < 0:
                    fMessages.append("Max file size must be a positive number")
                password = None if password == "" else password
                emailAddresses = split_list_sanitized(emailAddresses.replace(";", ",")) if (emailAddresses is not None and emailAddresses != "") else []
                personalMessage = strip_tags(personalMessage)
                requestType = "multi" if requestType.lower() == "multi" else "single"
                uploadRequest = UploadRequest(date_expires=expiration, max_file_size=maxFileSize, notify_user=notifyUser, type=requestType, owner_id=user.id)
                if password is not None:
                    uploadRequest.set_password(password)
                if requestType == "multi" and password is None:
                    fMessages.append("You must specify a password for upload requests that allow more than 1 file to be uploaded")
                else:
                    uploadRequest.generate_id()
                    session.add(uploadRequest)
                    if cc:
                        emailAddresses.append(user.email)
                    orgConfig = get_config_dict_from_objects(session.query(ConfigParameter).filter(ConfigParameter.name.like('org_%')).all())
                    for recipient in emailAddresses:
                        Mail.notify(get_template_file('upload_request_notification.tmpl'),\
                        {'sender': user.email, 'recipient': recipient, 'ownerId': user.id, \
                        'ownerName': user.display_name, 'requestId': uploadRequest.id, 'requestType': uploadRequest.type,\
                        'personalMessage': personalMessage, 'filelockerURL': config['root_url'], 'org_url': orgConfig['org_url'], 'org_name': orgConfig['org_name']})
                    session.add(AuditLog(user.id, Actions.CREATE_UPLOAD_REQUEST, "You created an upload request. As a result, the following email addresses were sent a file upload link: %s" % ",".join(emailAddresses), None))
                    session.commit()
                    uploadURL = config['root_url']+"/public_upload?ticketId=%s" % str(uploadRequest.id)
                    sMessages.append("Successfully created upload request")
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format, data=uploadURL)

    @cherrypy.expose
    @cherrypy.tools.requires_login()
    def delete_upload_request(self, ticketId, format="json", requestOrigin=""):
        user,  sMessages, fMessages = cherrypy.session.get("user"), [], []
        if requestOrigin != cherrypy.session['request-origin']:
            fMessages.append("Missing request key!!")
        else:
            try:
                ticketId = strip_tags(ticketId)
                uploadRequest = session.query(UploadRequest).filter(UploadRequest.id == ticketId).one()
                if uploadRequest.owner_id == user.id or AccountService.user_has_permission(user, "admin"):
                    session.delete(uploadRequest)
                    session.add(AuditLog(user.id, Actions.DELETE_UPLOAD_REQUEST, "You deleted an upload request with ID: %s" % uploadRequest.id))
                    session.commit()
                    sMessages.append("Upload request deleted")
                else:
                    fMessages.append("You do not have permission to delete this upload request")
            except Exception, e:
                fMessages.append(str(e))
        return fl_response(sMessages, fMessages, format)

    def serve_file(self, flFile, user=None, content_type=None, publicShareId=None):
        """Set status, headers, and body in order to serve the given file.

        The Content-Type header will be set to the content_type arg, if provided.
        If not provided, the Content-Type will be guessed by the file extension
        of the 'path' argument.

        If disposition is not None, the Content-Disposition header will be set
        to "<disposition>; filename=<name>". If name is None, it will be set
        to the basename of path. If disposition is None, no Content-Disposition
        header will be written.
        """
        config = cherrypy.request.app.config['filelocker']
        cherrypy.response.headers['Pragma']="cache"
        cherrypy.response.headers['Cache-Control']="private"
        cherrypy.response.headers['Content-Length'] = flFile.size
        cherrypy.response.stream = True

        success, message = (True, "")
        if user is None:
            user = cherrypy.session.get("user")
        disposition = "attachment"
        path = os.path.join(config['vault'], str(flFile.id))
        response = cherrypy.response
        try:
            st = os.stat(path)
        except OSError, ose:
            cherrypy.log.error("OSError while trying to serve file: %s" % str(ose))
            raise cherrypy.NotFound()
        # Check if path is a directory.
        if stat.S_ISDIR(st.st_mode):
            # Let the caller deal with it as they like.
            raise cherrypy.NotFound()

        # Set the Last-Modified response header, so that
        # modified-since validation code can work.
        response.headers['Last-Modified'] = http.HTTPDate(st.st_mtime)
        #cptools.validate_since()
        if content_type is None:
            # Set content-type based on filename extension
            ext = ""
            i = flFile.name.rfind('.')
            if i != -1:
                ext = flFile.name[i:].lower()
            content_type = mimetypes.types_map.get(ext, "text/plain")
        response.headers['Content-Type'] = content_type
        if disposition is not None:
            cd = '%s; filename="%s"' % (disposition, flFile.name)
            response.headers["Content-Disposition"] = cd

        # Set Content-Length and use an iterable (file object)
        #   this way CP won't load the whole file in memory
        c_len = st.st_size
        bodyfile = open(path, 'rb')
        salt = bodyfile.read(16)
        decrypter = Encryption.new_decrypter(flFile.encryption_key, salt)
        try:
            response.body = self.enc_file_generator(user, decrypter, bodyfile, flFile.id, publicShareId)
            return response.body
        except cherrypy.HTTPError, he:
            raise he

    def enc_file_generator(self, user, decrypter, dFile, fileId=None, publicShareId=None):
        endOfFile = False
        readData = dFile.read(1024*8)
        data = decrypter.decrypt(readData)
        #If the data is less than one block long, just process it and send it out
        #try:
        if len(data) < (1024*8):
            padding = int(str(data[-1:]),16)
            #A 0 represents that the file had a multiple of 16 bytes, and 16 bytes of padding were added
            if padding==0:
                padding=16
            endOfFile = True
            FileService.file_download_complete(user, fileId, publicShareId)
            yield data[:len(data)-padding]
        else:
            #For multiblock files
            while True:
                if endOfFile:
                    FileService.file_download_complete(user, fileId, publicShareId)
                    break
                next_data = decrypter.decrypt(dFile.read(1024*8))
                if (next_data is not None and next_data != "") and not len(next_data)<(1024*8):
                    yData = data
                    data = next_data
                    yield yData
                #This prevents padding going across block boundaries by aggregating the last two blocks and processing
                #as a whole if the next block is less than a full block (signifying end of file)
                else:
                    data = data + next_data
                    padding = int(str(data[-1:]),16)
                    #A 0 represents that the file had a multiple of 16 bytes, and 16 bytes of padding were added
                    if padding==0:
                        padding=16
                    endOfFile = True
                    yield data[:len(data)-padding]
        #except Exception, e:
            #logging.info("[%s] [decryptFile] [Decryption failed due to bad encryption key: %s]" % (user.userId, str(e)))
            #if cherrypy.session.has_key("fMessages"):
                #cherrypy.session['fMessages'].append("Decryption failed due to bad encryption key")
            #raise HTTPError(403, "Decryption failed due to bad encryption key.")

    @cherrypy.expose
    def upload_stats(self, format="json", **kwargs):
        sMessages, fMessages, uploadStats, uploadKey = [], [], [], None
        try:
            if cherrypy.session.has_key("user") and cherrypy.session.get("user") is not None:
                userId = cherrypy.session.get("user").id
                for key in cherrypy.file_uploads.keys():
                    if key.split(":")[0] == userId: # This will actually get uploads by the user and uploads using a ticket they generated
                        for fileStat in cherrypy.file_uploads[key]:
                            uploadStats.append(fileStat.stat_dict())
            elif cherrypy.session.has_key("uploadRequest"):
                uploadRequest = cherrypy.session.get("uploadRequest")
                uploadKey = uploadRequest.owner_id + ":" + uploadRequest.id
                if cherrypy.file_uploads.has_key(uploadKey):
                    for fileStat in cherrypy.file_uploads[uploadKey]:
                        uploadStats.append(fileStat.stat_dict())
            if format=='cli':
                uploadStatsXML = ""
                for fileUpload in uploadStats:
                    uploadStatsXML += "<upFile "
                    for k,v in fileUpload.iteritems():
                        uploadStatsXML += k+"='"+v+"' "
                    uploadStatsXML += "></upFile>"
                uploadStats = uploadStatsXML
        except KeyError:
            sMessages = ["No active uploads"]
        yield fl_response(sMessages, fMessages, format, data=uploadStats)
        
    
