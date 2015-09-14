import cherrypy
import time
import FileService
import os

class ProgressFile(object):
    def __init__(self, buf, fileName, file_object=None, uploadIndex=None, *args, **kwargs):
        if file_object is None:
            self.file_object = FileService.get_temp_file()
        else:
            self.file_object = file_object
        self.fileName = fileName
        self.transferred = 0
        self.buf = buf
        lcHDRS = {}
        for key, val in cherrypy.request.headers.iteritems():
            lcHDRS[key.lower()] = val
        self.pre_sized = float(lcHDRS['content-length'])
        self.speed = 1
        self.remaining = 0
        self.eta = 0
        self.uploadIndex = uploadIndex
        self._start = time.time()
        self.status = "Uploading"
    def write(self, data):
        now = time.time()
        self.transferred += len(data)
        if (now - self._start) == 0:
            self.speed = 0
        else:
            self.speed = self.transferred / (now - self._start)
        self.remaining = self.pre_sized - self.transferred
        if self.speed == 0: self.eta = 9999999
        else: self.eta = self.remaining / self.speed
        return self.file_object.write(data)

    def seek(self, pos):
        self.post_sized = self.transferred
        self.transferred = True
        return self.file_object.seek(pos)

    def read(self, size):
        return self.file_object.read(size)

    def readline(self):
        return self.file_object.readline()

    def stat_dict(self):
        valDict = {'fileName': self.fileName, 'speed': '%9.2f' % (self.speed / 1024.0),
                   'sizeKB': '%9.2f' % (self.pre_sized / 1024.0),
                   'transferredKB': '%9.2f' % (self.transferred / 1024.0), 'eta': str(int(self.eta))}
        if self.uploadIndex is not None:
            if self.uploadIndex.isdigit():
                valDict['uploadIndex'] = self.uploadIndex
            else:
                valDict['uploadIndex'] = "\"%s\"" % self.uploadIndex
        valDict['status'] = self.status
        return valDict

