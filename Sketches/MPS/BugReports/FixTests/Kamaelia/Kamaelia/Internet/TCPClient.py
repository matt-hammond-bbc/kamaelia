#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# FIXME: Uses the selector service, but has no way of indicating to the
#        selector service that its services are no longer required.
#        This needs resolving.
#
# Copyright 2010 British Broadcasting Corporation and Kamaelia Contributors(1)
#
# (1) Kamaelia Contributors are listed in the AUTHORS file and at
#     http://www.kamaelia.org/AUTHORS - please extend this file,
#     not this notice.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# -------------------------------------------------------------------------
"""\
=================
Simple TCP Client
=================

This component is for making a TCP connection to a server. Send to its "inbox"
inbox to send data to the server. Pick up data received from the server on its
"outbox" outbox.



Example Usage
-------------

Sending the contents of a file to a server at address 1.2.3.4 on port 1000::

    Pipeline( RateControlledFileReader("myfile", rate=100000),
              TCPClient("1.2.3.4", 1000),
            ).activate()


Example Usage - SSL
-------------------

It is also possible to cause the TCPClient to switch into SSL mode. To do this
you send it a message on its "makessl" inbox. It is necessary for a number of
protocols to be able to switch between non-ssl and ssl, hence this approach
rather than simply saying "ssl client" or "non-ssl client"::

    Graphline(
           MAKESSL = OneShot(" make ssl "),
           CONSOLE = ConsoleReader(),
           ECHO = ConsoleEchoer(),
           CONNECTION = TCPClient("kamaelia.svn.sourceforge.net", 443),
           linkages = {
               ("MAKESSL", "outbox"): ("CONNECTION", "makessl"),
               ("CONSOLE", "outbox"): ("CONNECTION", "inbox"),
               ("CONNECTION", "outbox"): ("ECHO", "inbox"),
           }
    )

How does it work?
-----------------

TCPClient opens a socket connection to the specified server on the specified
port. Data received over the connection appears at the component's "outbox"
outbox as strings. Data can be sent as strings by sending it to the "inbox"
inbox.

An optional delay (between component activation and attempting to connect) can
be specified. The default is no delay.

It creates a ConnectedSocketAdapter (CSA) to handle the socket connection and
registers it with a selectorComponent so it is notified of incoming data. The
selectorComponent is obtained by calling
selectorComponent.getSelectorService(...) to look it up with the local
Coordinating Assistant Tracker (CAT).

TCPClient wires itself to the "CreatorFeedback" outbox of the CSA. It also wires
its "inbox" inbox to pass data straight through to the CSA's "inbox" inbox,
and its "outbox" outbox to pass through data from the CSA's "outbox" outbox.

Socket errors (after the connection has been successfully established) may be
sent to the "signal" outbox.

This component will terminate if the CSA sends a socketShutdown message to its
"CreatorFeedback" outbox.

This component will terminate if a shutdownMicroprocess or producerFinished
message is sent to its "control" inbox. This message is forwarded onto the CSA.
TCPClient will then wait for the CSA to terminate. It then sends its own
shutdownMicroprocess message out of the "signal" outbox.
"""

import socket
import errno

import Axon
from Axon.util import Finality

from Axon.Ipc import producerFinished, shutdownMicroprocess
from Axon.Ipc import newComponent, status
from Kamaelia.IPC import socketShutdown, newCSA

from Kamaelia.IPC import newReader, newWriter
from Kamaelia.IPC import removeReader, removeWriter

from Kamaelia.Internet.ConnectedSocketAdapter import ConnectedSocketAdapter

from Kamaelia.Internet.Selector import Selector
# from Kamaelia.Apps.SocialBookmarks.Print import Print # For debug purposes

import time

class TCPClient(Axon.Component.component):
   """\
   TCPClient(host,port[,delay]) -> component with a TCP connection to a server.

   Establishes a TCP connection to the specified server.
   
   Keyword arguments:
   
   - host     -- address of the server to connect to (string)
   - port     -- port number to connect on
   - delay    -- delay (seconds) after activation before connecting (default=0)
   """
   Inboxes  = { "inbox"           : "data to send to the socket",
                "_socketFeedback" : "notifications from the ConnectedSocketAdapter",
                "control"         : "Shutdown signalling",
                "makessl"         : "Notifications to the ConnectedSocketAdapter that we want to negotiate SSL",
              }
   Outboxes = { "outbox"         :  "data received from the socket",
                "signal"         :  "socket errors",
                "_selectorSignal"       : "For registering and deregistering ConnectedSocketAdapter components with a selector service",
                "sslready"       : "SSL negotiated successfully",

              }
   Usescomponents=[ConnectedSocketAdapter] # List of classes used.

   def __init__(self,host,port,delay=0, connect_timeout=60, wait_for_serverclose = False):
      """x.__init__(...) initializes x; see x.__class__.__doc__ for signature"""
      super(TCPClient, self).__init__()
      self.host = host
      self.port = port
      self.delay=delay
      self.CSA = None
      self.sock = None
      self.howDied = None
      self.connect_timeout = connect_timeout
      self.wait_for_serverclose = wait_for_serverclose

   def main(self):
      """Main loop."""

      # wait before connecting
      waitUntil = time.time() + self.delay
      while time.time() < waitUntil:
         yield 1

      for v in self.runClient():
         yield v
      
      if (self.sock is not None) and (self.CSA is not None):
         self.send(removeReader(self.CSA, self.sock), "_selectorSignal")
         self.send(removeWriter(self.CSA, self.sock), "_selectorSignal")
      

   def setupCSA(self, sock):
      """\
      setupCSA(sock) -> new ConnectedSocketAdapter component

      Creates a ConnectedSocketAdapter component for the socket, and wires up to
      it. Also sends the CSA to the "selector" service.
      """
      selectorService, selectorShutdownService, newSelector = Selector.getSelectorServices(self.tracker)
      if newSelector:
         self.addChildren(newSelector)

      CSA = ConnectedSocketAdapter(sock, selectorService) #  self.createConnectedSocket(sock)
      self.addChildren(CSA)
      self.link((self, "_selectorSignal"),selectorService)
 
      self.link((CSA, "CreatorFeedback"),(self,"_socketFeedback"))
      self.link((CSA, "outbox"), (self, "outbox"), passthrough=2)
      self.link((CSA, "sslready"), (self, "sslready"), passthrough=2)
      self.link((self, "inbox"), (CSA, "inbox"), passthrough=1)
      self.link((self, "makessl"), (CSA, "makessl"), passthrough=1)

      self.link((self, "control"), (CSA, "control"), passthrough=1)  # propagate shutdown msgs

      self.send(newReader(CSA, ((CSA, "ReadReady"), sock)), "_selectorSignal")            
      self.send(newWriter(CSA, ((CSA, "SendReady"), sock)), "_selectorSignal")            
      self.CSA = CSA # We need this for shutdown later

      return self.childComponents()

   def waitCSAClose(self):
      """Returns True if a socketShutdown message is received on "_socketFeedback" inbox."""
      if self.dataReady("_socketFeedback"):
         message = self.recv("_socketFeedback")
         if isinstance(message, socketShutdown):
            try:
               socket, howdied = message
               self.howDied = howdied
            except TypeError:
               self.howDied = None 
            return False
      return True

   def safeConnect(self, sock, *sockArgsList):
      """\
      Connect to socket and handle possible errors that may occur.

      Returns True if successful, or False on failure. Unhandled errors are raised
      as exceptions.
      """
      try:
         sock.connect(*sockArgsList); # Expect socket.error: (115, 'Operation now in progress')
            # EALREADY
            #   The  socket  is  non-blocking  and  a  previous connection
            #   attempt has not yet been completed.
         self.connecting=0
         return True
      except socket.error, socket.msg:
         (errorno, errmsg) = socket.msg.args
         if errorno==errno.EALREADY:
            # The socket is non-blocking and a previous connection attempt has not yet been completed
            # We handle this by allowing  the code to come back and repeatedly retry
            # connecting. This is a valid, if brute force approach.
            assert(self.connecting==1)
            return False
         elif errorno==errno.EINPROGRESS or errorno==errno.EWOULDBLOCK:
            #The socket is non-blocking and the connection cannot be completed immediately.
            # We handle this by allowing  the code to come back and repeatedly retry
            # connecting. Rather brute force.
            if not getattr(self, 'connecting', 0):
                self.connecting=1
                return False # Not connected should retry until no error
            else:
                # MSW doesn't raise a nice connection refused exception.  Instead
                # we detect going from a WSAEINVAL (like EALREADY for windows) back to a
                # EWOULDBLOCK which means the connection was refused and we are trying to
                # connect for a second time.
                raise errno.ECONNREFUSED
         elif errorno == errno.EISCONN:
             # This is a windows error indicating the connection has already been made.
             self.connecting = 0 # as with the no exception case.
             return True
         elif hasattr(errno, "WSAEINVAL"):
            if errorno == errno.WSAEINVAL:
                # If we are on windows, this will be the error instead of EALREADY
                # above.
                assert(self.connecting==1)
                return False
            else:
                raise socket.msg # We're on windows platform and unk exception occurred
         # Anything else is an error we don't handle
         else:
            raise socket.msg

   def runClient(self,sock=None):
      # The various numbers yielded here indicate progress through the function, and
      # nothing else specific.
      try:
         sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); yield 0.3
         # Print( "GOT SOCK" )
         self.sock = sock # We need this for shutdown later
         try:
            sock.setblocking(0); yield 0.6
            # Print( "GOT A NON BLOCK" )
            try:
               tryUntil = time.time() + self.connect_timeout
               # Print( "GOT A ODD SOCK" )
               while not self.safeConnect(sock,(self.host, self.port)):
                  if self.shutdown():
                      return
                  if time.time() >= tryUntil:
                      self.howDied = "timeout"
                      raise Finality
                  yield 1
               # Print( "CONNECTED" )
               yield newComponent(*self.setupCSA(sock))
               while self.waitCSAClose():
                  self.pause()
                  yield 2
               raise Finality
            except Exception, x:
               # Print(  "SHUTTING SOCK",x )
               result = sock.shutdown(2) ; yield 3
               raise x  # XXXX If X is not finality, an error message needs to get sent _somewhere_ else
               # The logical place to send the error is to the signal outbox
         except Exception, x:
            # Print(  "CLOSING SOCK",x )
            sock.close() ;  yield 4,x # XXXX If X is not finality, an error message needs to get sent _somewhere_ else
            raise x
      except Finality:
         # Print( "LOOKING GOOD SOCK" )
         yield 5
      except socket.error, e:
         # We now do the flipside of setupCSA, whether we had an error or not
         # A safe error relates to a disconnected server, and unsafe error is generally
         # bad. However either way, it's gone, let's let the person using this
         # component know, shutdown everything, and get outta here.
         #
         # FIXME: Set self.howDied here as well
         #
         # Print(  "SMELLY SOCK", e )
         pass
      self.send(producerFinished(self,self.howDied), "signal")
#          self.send(e, "signal")
        # "TCPC: Exitting run client"

   def stop(self):
       """Stop method provided to allow the scheduler to kill TCPClient connections cleanly if necessary.
       (Only rarely, if ever, needed - you are not expected to call this yourself)"""
       try:
           self.sock.shutdown(2)
       except:
           pass # Well, we tried.
       try:
           self.sock.close()
       except:
           pass # Well, we tried.
       self.send(producerFinished(self,self.howDied), "signal")
       if (self.sock is not None) and (self.CSA is not None):
           self.send(removeReader(self.CSA, self.sock), "_selectorSignal")
           self.send(removeWriter(self.CSA, self.sock), "_selectorSignal")
           self.send(producerFinished(),"signal")
       super(TCPClient, self).stop()

   def shutdown(self):
       while self.dataReady("control"):
           msg = self.recv("control")
           if not self.wait_for_serverclose:
               self.send(msg,"signal")
               return isinstance(msg, (producerFinished,shutdownMicroprocess))
           else:
               if isinstance(msg, shutdownMicroprocess):
                   self.send(msg,"signal")
                   return True
       return False

__kamaelia_components__  = ( TCPClient, )


if __name__ =="__main__":
   from Axon.Scheduler import scheduler
   from Kamaelia.Chassis.ConnectedServer import SimpleServer
   from Kamaelia.Protocol.FortuneCookieProtocol import FortuneCookieProtocol
   from Kamaelia.Util.Console import ConsoleEchoer
   from Axon.Component import component


   class testHarness(component): # Spike component to test interoperability with TCPServer
      def __init__(self):
         super(testHarness, self).__init__() # I wonder if this can get forced to be called automagically?
         import random
         self.serverport = random.randint(4000,8000)
         self.server = SimpleServer(protocol=FortuneCookieProtocol, port=self.serverport)
         self.client = None
         self.display = ConsoleEchoer()

      def initialiseComponent(self):
         self.client = TCPClient("127.0.0.1",self.serverport, delay=1)
         self.addChildren(self.server,self.client,self.display)
#         self.addChildren(self.server, self.display)
         self.link((self.client,"outbox"), (self.display,"inbox") )
         return Axon.Ipc.newComponent(*(self.children))

      def mainBody(self):
            return 1

   t = testHarness()
   t.activate()
   scheduler.run.runThreads(slowmo=0)
