#!/usr/bin/env python
#
# (C) 2004 British Broadcasting Corporation and Kamaelia Contributors(1)
#     All Rights Reserved.
#
# You may only modify and redistribute this under the terms of any of the
# following licenses(2): Mozilla Public License, V1.1, GNU General
# Public License, V2.0, GNU Lesser General Public License, V2.1
#
# (1) Kamaelia Contributors are listed in the AUTHORS file and at
#     http://kamaelia.sourceforge.net/AUTHORS - please extend this file,
#     not this notice.
# (2) Reproduced in the COPYING file, and at:
#     http://kamaelia.sourceforge.net/COPYING
# Under section 3.5 of the MPL, we are using this text since we deem the MPL
# notice inappropriate for this file. As per MPL/GPL/LGPL removal of this
# notice is prohibited.
#
# Please contact us via: kamaelia-list-owner@lists.sourceforge.net
# to discuss alternative licensing.
# -------------------------------------------------------------------------

#possible dirty hack to sort things out...
#import sys
#reload(sys)
#sys.setdefaultencoding("utf-8")

import array
from Axon.Component import component
from Axon.ThreadedComponent import threadedcomponent
from Axon.Ipc import producerFinished, shutdownMicroprocess
from Kamaelia.Util.PipelineComponent import pipeline
from Kamaelia.Util.Introspector import Introspector
from Kamaelia.Internet.TCPClient import TCPClient
from Kamaelia.SimpleServerComponent import SimpleServer
from Axon.Ipc import producerFinished, errorInformation
import string, time, website
from Lagger import Lagger

def currentTimeHTTP():
    curtime = time.gmtime()
    return time.strftime("Date: %a, %d %b %Y %H:%M:%S GMT", curtime)

def removeTrailingCr(line):
    if len(line) == 0:
        return line
    elif line[-1] == "\r":
        return line[0:-1]
    else:
        return line

def splitUri(requestobject):
    splituri = string.split(requestobject["raw-uri"], "://")
    if len(splituri) > 1:
        requestobject["uri-protocol"] = splituri[0]
        requestobject["raw-uri"] = requestobject["raw-uri"][len(splituri[0] + "://"):]
    
    splituri = string.split(requestobject["raw-uri"], "/")
    if splituri[0] != "":
        requestobject["uri-server"] = splituri[0]
        requestobject["raw-uri"] = requestobject["raw-uri"][len(splituri[0] + "/"):]
    else:
        requestobject["uri-server"] = requestobject["raw-uri"]
        requestobject["raw-uri"] = ""
        
    splituri = string.split(requestobject["uri-server"], ":")
    if len(splituri) == 2:
        requestobject["uri-port"] = splituri[1]
        requestobject["uri-server"] = splituri[0]
        
    splituri = string.split(requestobject["uri-server"], "@")
    if len(splituri) == 2:
        requestobject["uri-username"] = splituri[0]
        requestobject["uri-server"] = requestobject["uri-server"][len(splituri[0] + "@"):]
        splituri = string.split(requestobject["uri-username"], ":")
        if len(splituri) == 2:
            requestobject["uri-username"] = splituri[0]
            requestobject["uri-password"] = splituri[1]


class HTTPParser(component):
    Inboxes =  { "inbox"         : "Raw HTTP requests",
                 "control"       : "UNUSED" }
    Outboxes = { "outbox"        : "HTTP request object",
                 "signal"        : "UNUSED" }
    
    def __init__(self):
        super(HTTPParser, self).__init__()
        readbuffer = ""
        self.requeststate = 1 # awaiting request line
        self.lines = []
        self.readbuffer = ""

    def dataFetch(self):
        if self.dataReady("inbox"):
            self.readbuffer += self.recv("inbox")
            return 1
        else:
            return 0
            
    def shouldShutdown(self):
        while self.dataReady("control"):
            temp = self.recv("control")
            if isinstance(temp, shutdownMicroprocess) or isinstance(temp, producerFinished):
                return True
        
        return False
        
    def nextLine(self):
        lineendpos = string.find(self.readbuffer, "\n")
        if lineendpos == -1:
            return None
        else:
            line = removeTrailingCr(self.readbuffer[:lineendpos])
            self.readbuffer = self.readbuffer[lineendpos + 1:] #the remainder after the \n
            #print "Received line: " + line
            return line
        
    def main(self):

        while 1:
            requestobject = { "bad": False, "headers": {}, "raw-uri": "", "version": "0.9", "method":"", "protocol":"" }
            
            #state 1 - awaiting initial line
            currentline = None
            while currentline == None:
                if self.shouldShutdown(): return
                while self.dataFetch():
                    pass
                currentline = self.nextLine()
                if currentline == None:
                    self.pause()
                    yield 1
                
            #print "Initial line found"
            splitline = string.split(currentline, " ")
            
            if len(splitline) < 2:
                requestobject["bad"] = True
                # bad request
            else:
                if len(splitline) < 3:
                    # must be HTTP/0.9
                    requestobject["method"] = splitline[0]
                    requestobject["raw-uri"] = splitline[1]
                    requestobject["protocol"] = "HTTP"
                    requestobject["version"] = "0.9"
                else: #deal with normal HTTP including badly formed URIs
                    requestobject["method"] = splitline[0]

                    #next line supports all working clients but also 
                    #some broken clients that don't encode spaces properly!
                    requestobject["raw-uri"] = string.join(splitline[1:-1], "%20") 
                    protvers = string.split(splitline[-1], "/")
                    if len(protvers) != 2:
                        requestobject["bad"] = True
                        requestobject["version"] = "0.9"
                    else:
                        requestobject["protocol"] = protvers[0]
                        requestobject["version"] = protvers[1]
                    
                    splitUri(requestobject)
                    
                #foo://toor:letmein@server.bigcompany.com:80/bla?this&that=other could be handled better

                if requestobject["method"] == "PUT" or requestobject["method"] == "POST":
                    bodiedrequest = True
                else:
                    bodiedrequest = False

                if requestobject["version"] != "HTTP/0.9":
                    #state 2 - as this is a valid request, we now accept headers	
                    previousheader = ""
                    endofheaders = False
                    while not endofheaders:
                        if self.shouldShutdown(): return						
                        while self.dataFetch():
                            pass
                            
                        currentline = self.nextLine()
                        while currentline != None:
                            if currentline == "":
                                #print "End of headers found"
                                endofheaders = True
                                break
                            else:
                                if currentline[0] == " " or currentline[0] == "\t": #continued header
                                    requestobject["headers"][previousheader] += " " + string.lstrip(currentline)
                                else:
                                    splitheader = string.split(currentline, ":")
                                    #print "Found header: " + splitheader[0]
                                    requestobject["headers"][string.lower(splitheader[0])] = string.lstrip(currentline[len(splitheader[0]) + 1:])
                            currentline = self.nextLine()
                            #should parse headers header
                        if not endofheaders:
                            self.pause()
                            yield 1
                if requestobject["headers"].has_key("host"):
                    requestobject["uri-server"] = requestobject["headers"]["host"]
                
                if bodiedrequest:
                    #state 3 - the headers are complete - awaiting the message
                    if not requestobject["headers"].has_key("content-length"):
                        #this is not strictly required - it breaks compatible with chunked encoding
                        #but will do for now
                        requestobject["bad"] = 411 #length required
                    else:
                        if string.lower(requestobject["headers"].get("expect", "")) == "100-continue":
                            #we're supposed to say continue, but this is a pain
                            #and everything still works if we don't
                            pass
                            
                        bodylength = int(requestobject["headers"]["content-length"])
                         
                        while len(self.readbuffer) < bodylength:
                            if self.shouldShutdown(): return						
                            while self.dataFetch():
                                pass
                            if len(self.readbuffer) < bodylength:
                                self.pause()
                                yield 1
                        requestobject["body"] = self.readbuffer[:bodylength]
                        self.readbuffer = self.readbuffer[bodylength:]

                #state 4 - request complete, send it on
            #print "Request sent on."
            #print requestobject
            
            if requestobject["version"] == "1.1":
                requestobject["headers"]["connection"] = requestobject["headers"].get("connection", "keep-alive")
            else:
                requestobject["headers"]["connection"] = requestobject["headers"].get("connection", "close")
                    
            self.send(requestobject, "outbox")
            if string.lower(requestobject["headers"].get("connection", "")) == "close":
                self.send(producerFinished(), "signal") #this functionality is semi-complete
                return

class HTTPServer(component):
    """\
    HTTPServer() -> new HTTPServer
    """
    
    Inboxes =  { "inbox"         : "TCP data stream - receive",
                 "mime-outbox"   : "Data from MIME handler",
                 "mime-signal"   : "Error signals from MIME handler",
                 "http-outbox"   : "Data from HTTP resource retriever",
                 "http-signal"   : "Error signals from the HTTP resource retriever",
                 "control"       : "Receive shutdown etc. signals" }


    Outboxes = { "outbox"        : "TCP data stream - send",
                 "mime-inbox"    : "To MIME handler",
                 "mime-control"  : "To MIME handler",
                 "http-inbox"    : "To HTTP resource retriever",
                 "http-control"  : "To HTTP resource retriever's signalling inbox",
                 "signal"        : "UNUSED" }

    def __init__(self):
        super(HTTPServer, self).__init__()

    def initialiseComponent(self):
        self.mimehandler = HTTPParser()
        self.httphandler = HTTPRequestHandler()
        #self.httphandler.filereader = TriggeredFileReader()
        
        self.link( (self,"mime-inbox"), (self.mimehandler,"inbox") )
        self.link( (self,"mime-control"), (self.mimehandler,"control") )
        self.link( (self.mimehandler,"outbox"), (self, "mime-outbox") )
        self.link( (self.mimehandler,"signal"), (self, "mime-signal") )

        self.link( (self, "http-inbox"), (self.httphandler, "inbox") )
        self.link( (self, "http-control"), (self.httphandler, "control") )
        self.link( (self.httphandler, "outbox"), (self, "http-outbox") )
        self.link( (self.httphandler, "signal"), (self, "http-signal") )

        #elf.link( (self.httphandler, "filereader-inbox"), (self.httphandler.filereader, "inbox") )
        #self.link( (self.httphandler.filereader,"outbox"), (self.httphandler, "filereader-outbox") )
        
        self.addChildren(self.mimehandler, self.httphandler) #self.httphandler.filereader)
        self.httphandler.activate()
        self.mimehandler.activate()
        #self.httphandler.filereader.activate()

    def mainBody(self):
        while self.dataReady("inbox"):
            temp = self.recv("inbox")
            self.send(temp, "mime-inbox")

        while self.dataReady("control"):
            temp = self.recv("control")
            if isinstance(temp, shutdownMicroprocess) or isinstance(temp, producerFinished):
                self.send(temp, "mime-control")
                self.send(temp, "http-control")
                return 0
        
        while self.dataReady("http-outbox"):
            temp = self.recv("http-outbox")
            self.send(temp, "outbox")

        while self.dataReady("mime-outbox"):
            temp = self.recv("mime-outbox")
            self.send(temp, "http-inbox")

        while self.dataReady("mime-signal"):
            temp = self.recv("mime-signal")
            if isinstance(temp, producerFinished):
                pass
                #we don't need to care yet - wait 'til the request handler finishes
        
        while self.dataReady("http-signal"):
            temp = self.recv("http-signal")
            if isinstance(temp, producerFinished):
                sig = producerFinished(self)
                self.send(sig, "mime-control")                
                self.send(sig, "signal")
                return 0
                #close the connection
                
        self.pause()
        return 1

    def closeDownComponent(self):
        for child in self.childComponents():
            self.removeChild(child)
        self.mimehandler = None
        self.httphandler = None

class HTTPRequestHandler(component):
    Inboxes =  { "inbox"               : "Raw HTTP requests",
                 #"filereader-outbox"   : "File reader's outbox",
                 "control"             : "Signal component termination" }
    Outboxes = { "outbox"              : "HTTP request object",
                 #"filereader-inbox"    : "File reader's inbox",
                 "signal"              : "Signal connection to close" }

    def convertUnicodeToByteStream(self, data):
        return data.encode("utf-8")
        
    def __init__(self):
        super(HTTPRequestHandler, self).__init__()
        

    def fetchResource(self, request):
        for (prefix, handler) in website.URLHandlers:
            if request["raw-uri"][:len(prefix)] == prefix:
                resource = handler(request)
                return resource
        
    def formHeaderResponse(self, resource, protocolversion):
        if resource["statuscode"] == "200": statustext = "200 OK"
        if resource["statuscode"] == "400": statustext = "400 Bad Request"
        if resource["statuscode"] == "404": statustext = "404 Not Found"
        if resource["statuscode"] == "500": statustext = "500 Internal Server Error"
        if resource["statuscode"] == "501": statustext = "501 Not Implemented"
        if resource["statuscode"] == "411": statustext = "411 Length Required"

        if (protocolversion == "0.9"):
            header = ""        
        else:
            header = "HTTP/1.1 " + statustext + "\nServer: Kamaelia HTTP Server (RJL) 0.2\nDate: " + currentTimeHTTP() + "\n"
            if resource.has_key("charset"):
                header += "Content-type: " + resource["type"] + "; " + resource["charset"] + "\n"
            else:
                header += "Content-type: " + resource["type"] + "\n"
            header += "Content-length: " + str(len(resource["data"])) + "\n\n"
        return header

    def mainBody(self):
        while self.dataReady("inbox"):
            request = self.recv("inbox")
            print "Request for " + request["raw-uri"]
            if request["bad"] == "411":
                pagedata = website.getErrorPage(411, "Um - content-length plz!")
                self.send(self.formHeaderResponse(pagedata, request["version"]) + pagedata["data"], "outbox")
            elif request["bad"]:
                pagedata = website.getErrorPage(400, "Your request sucked!")
                self.send(self.formHeaderResponse(pagedata, "1.0") + pagedata["data"], "outbox")

            elif request["protocol"] != "HTTP":
                pagedata = website.getErrorPage(400, "Non-HTTP")
                self.send(self.formHeaderResponse(pagedata, request["version"]) + pagedata["data"], "outbox")
            else:
                if request["version"] > "1.0" and not request["headers"].has_key("host"):
                    pagedata = website.getErrorPage(400, "could not find host header")
                    self.send(self.formHeaderResponse(pagedata, request["version"]) + pagedata["data"], "outbox")
                elif request["method"] == "GET" or request["method"] == "POST":
                    pagedata = self.fetchResource(request)
                    if isinstance(pagedata["data"], unicode):
                         pagedata["data"] = self.convertUnicodeToByteStream(pagedata["data"])
                         pagedata["charset"] = "utf-8"
                         
                    self.send(self.formHeaderResponse(pagedata, request["version"]) + pagedata["data"], "outbox")
                else:
                    pagedata = website.getErrorPage(501,"The request method is not implemented")
                    self.send(self.formHeaderResponse(pagedata, request["version"]) + pagedata["data"], "outbox")
                    print "Sent 501 not implemented response"                    
                
                if request["version"] == "1.1":
                    connection = request["headers"].get("connection", "keep-alive")
                else:
                    connection = request["headers"].get("connection", "close")
                if connection.lower() == "close":
                    self.send(producerFinished(), "signal") #this functionality is semi-complete
                    return 0

        while self.dataReady("control"):
            temp = self.recv("control")
            if isinstance(temp, shutdownMicroprocess) or isinstance(temp, producerFinished):
                return 0

        self.pause()
        #time.sleep(0.01)
            
        return 1


if __name__ == '__main__':
    from Axon.Component import scheduler
    import socket
    SimpleServer(protocol=HTTPServer, port=8082, socketOptions=(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  ).activate()
    #pipeline(
    #    Introspector(),
    #    TCPClient("127.0.0.1", 1500),
    #).activate()
    #Lagger().activate()
    scheduler.run.runThreads(slowmo=0)
