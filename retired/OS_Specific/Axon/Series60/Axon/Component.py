#!/usr/bin/env python2.3
# -*- coding: utf-8 -*-
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
"""Kamaelia Concurrency Component Framework.

COMPONENTS

A component is a microprocess with a microthread of control, input/output
queues (inboxes/ outboxes) connected by linkages to other components, with
postmen taking messages from output queues, passing them along linkages
to inboxes.

A microprocess is a class that supports parallel execution using microthreads.

A microthread takes more explanation is a thread of control resulting from
a function of the following form::

   def foo():
      yield 1
      while 1:
         print "this"
         yield 1
         print "that"

'bla = foo()' results in bla containing an intelligent function representing the
thread of control *inside* the function - in this case inside the while loop - that
remembers where the program counter was when control was yielded back
to the caller. Repeated calls to 'bla' continue where you left off.

First call to 'bla()' & you get "this" printed. Next time you get "that" then "this"
printed (when you go back round the loop). The time after that, you get "that"
then "this" printed, and so on.

If you have 10 calls to 'foo()' you end up with 10 function calls that remember
where they were in 'foo()', which run for a bit and then return control back to the
caller. If you repeatedly call all of these function calls, you essentially end up
with 'foo()' running 10 times in parallel. It's these special "position remembering"
functions that get termed microthreads.

Clearly in order to have a microthread, you have to have a piece of code
capable of being called in this manner - ie it yields control back to it's caller
periodically  - this is a what a microprocess in this context. An object that has
a "special method" that can be treated in this manner.

A component puts a layer of wrapper on top of the microprocess, which adds
in input & output queues (inboxes/outboxes). To make life easier, a component
has some wrappers around the "special function" to make user code less
obfuscated. The life cycle for a component runs as follows::

myComponent = FooComponent()   # Calls Foo.__init__() constructor,
                              # which must call super class constructor

'myComponent' gets activated.

When 'myComponent' is activated the following logic happens for the
runtime of 'myComponent' ::

   def runComponent(someComponent):
      result = someComponent.initialiseComponent()
      if result: yield result
      result = 1
      while result:
         result = someComponent.mainBody()
         if result: yield result
      someComponent.closeDownComponent
      yield result
      # Component ceases running

Dummy methods for the methods listed here are provided, so missing these
out won't result in broken code. The upshot is a user component looks like this::

   class myComponent(component):
      count = 0
      def __init__(self,somearg):
         self.__class__.count = self.__class__.count + 1
         self.somearg = somearg
         self.Component() # !!!! Must happen if this method exists

      def initialiseComponent(self):
         print "We can perform pre-loop initialisation here!"
         print "If we created a new component here, we'd have"
         print "     return newComponent[theComponent]"
         print " as the last line of this function"
         return 1

      def mainLoop(self):
         print "We're now in the main loop"
         print "If we wanted to exit the loop, we return a false value"
         print "at the end of this function"
         print "If we want to continue round, we return a true, non-None,"
         print "value. This component is set to run & run..."
         return 1

      def closeDownComponent(self):
         print "We can't get here since mainLoop above always returns true"
         print "If it returned false however, we would get sent here for"
         print "shutdown code."
         print "After executing this, the component stops execution"

This creates a component class which has the default input/output boxes
of "inbox" and "outbox".

"""
from __future__ import generators

import time

from util import removeAll
from idGen import strId, numId
#from debug import debug
from Microprocess import microprocess
from Postman import postman
from Scheduler import scheduler
from AxonExceptions import noSpaceInBox
from Linkage import linkage
from Ipc import *

# Component - a microprocess with a bunch of input/output queues.
#
# It's only communication with the outside world should be through these
# in/out queues, except for a minority of adaptor components that interact
# with the outside world. (Think stdin/stout/stderr)
#
# All components you create should subclass the component class. At present
# you should be doing subclassing directly in most cases. After performing
# local component initialisation in your   '__init__' function, you should then
# call your super class's (component's) '__init__' constructor to ensure that
# the component is correctly configured. ie do this::
#
#    self.component()
#
# In order for your component to become active, you can either::
#
#    foo = myComponent()
#    foo.activate()
#
# If the scheduler isn't already running. If the scheduler is running, then
# you are creating a component from inside a component. In which case
# at the end of your 'mainBody()' function you need to return the new component
# in a message to the scheduler via::
#
#    return (newComponent([foo]);
#
# Which will then handle activation of the component.
#
# Life cycle of a component:
#
# 1. First your '__init__' method is called - this should set up the component,
#     but not actually do any work, other than pure initialisation. (eg read in
#     a file name from the arguments and store it locally, don't open it at that
#     point)
#
# 2. Your object is then activated at some point. This provides you with a
#     thread of control which you have to hand back. When your object is
#     activated and has a thread of control, you can perform some initialisation,
#     since the method 'initialiseComponent' is then called.
#
# 3. Your object goes into the main loop - your 'mainBody' function forms
#     the body of this loop. If you return a 'newComponent' value, you can
#     activate new components you create. If you return a false value (eg None),
#     then your component will exit this mainloop and go into a closedown state.
#
# 4. Your 'closeDownComponent' method is called next if it exists.
#

class component(microprocess):
   Inboxes=["inbox","control"]
   Outboxes=["outbox","signal"]
   Usescomponents=[]

   def __init__(self ):
      """You want to overide this method locally. You MUST call this superconstructor for
      things to work however. The way you do this is super(YourClassName, self).__init__()
      """
      super(component, self).__init__()
      self.inboxes = dict()
      self.outboxes = dict()
      # Create the FIFOs associated with the inboxes/outboxes. (dict(string->list))
      [ self.inboxes.__setitem__(boxname, list()) for boxname in self.Inboxes ]
      [ self.outboxes.__setitem__(boxname, list()) for boxname in self.Outboxes ]

      self.children = []

      self.postoffice = postman("component :" + self.name)
      self.postoffice.activate()
      self.synchronised = {}

   def _synchronisedBox(self, boxtype="sink",boxdirection="outbox",boxname="outbox", maxdepth=1):
      """C.synchronisedBox(boxtype="source/sink" boxdirection="inbox/outbox" boxname="name" maxdepth=queuesize

      Declares a box as synchronised. Generally inboxes will be declared synchronised
      which means data cannot be delivered into them immediately. An important point
      is that this makes an box at the other end of a linkage also synchronised. This
      means if you're sending to a synchronised outbox, or an outbox that has been made
      synchronous as a result then you must use synchronisedSend to send data. (Things
      go bang otherwise)
      """
      try:
         self.synchronised[boxdirection][boxname]=(boxtype,maxdepth)
      except KeyError:
         self.synchronised[boxdirection] = {}
         self.synchronised[boxdirection][boxname]=(boxtype,maxdepth)

   def synchronisedSend(self, thingsToSend,outbox="outbox"):
      """C.synchronisedSend(list, of, things,to, send) -> generator for sending the
      objects when space is available. Expected to be used as:
         for i in self.synchronisedSend(thingsToSend):
            yield 1
      Largely has to be done that way due to not being able to wrap yield.
      See test/SynchronousLinks_SystemTest.py for an example
      """
      while 1:
         try:
            j = thingsToSend[0]
            self.send(j,outbox)
         except noSpaceInBox:
            yield -1
         else:
            del thingsToSend[0]
            if not thingsToSend: break
            yield j

   def __str__(self):
      """Provides a useful string representation of the component.
      You probably want to override this, and append this description using
      something like: 'component.__str__(self)'
      """
      result = "Component " + self.name + " [ inboxes : " + self.inboxes.__str__() + " outboxes : " + self.outboxes.__str__()
      return result

   def _activityCreator(self):
      return True

   def __addChild(self, child):
      """'C.__addChild(component)' -
      Register component as a child.

      This takes a child component, and adds it to the children list of this
      component. This has a number of effects internally, and includes
      registering the component as capable of recieving and sending messages.
      It doesn't give the child a thread of control however!

      You will want to call this function if you create child components of your
      component.
      """
      self.postoffice.register(child.name,child)
      self.children.append(child)

   def addChildren(self,*children):
      """'C.addChildren(list,of,components)' -
      Register the components as children/subcomponents
      This takes a list of children components and adds them to the children list of this
      component. This is done by looping of the list and adding each one individually
      by calling addChild. addChild has a number of effects internally described above."""
      for child in children:
         self.__addChild(child)

   def removeChild(self, child):
      """'C.removeChild(component)' -
      Deregister component as a child.

      Removes the child component, and deregisters it as capable of recieving
      messages. You probably want to do this when you enter a closedown state
      of some kind for either your component, or the child component.

      You will want to call this function when shutting down child components of
      your component.
      """
      removeAll(self.children, child)
      self.postoffice.deregister(component=child)

   def childComponents(self):
      """'C.childComponents()' -
      Simple accessor method, returns list of child components"""
      return self.children

   def dataReady(self,boxname="inbox"):
      """'C.dataReady("boxname")' -
      test, returns true if data is available in the requested inbox.

      Used by a component to check an inbox for ready data.
      You will want to call this method to periodically check whether you've been
      sent any messages to deal with!

      You are unlikely to want to override this method.
      """
      return len(self.inboxes[boxname])


   def link(self, source,sink,passthrough=0,pipewidth=0,synchronous=None):
      """'C.link(source,sink)' -
      create linkage between a source and sink.

      source is a tuple: (source_component, source_box)
      sink is a tuple: (sink_component, sink_box)

      passthrough and pipewidth are defined as in the linkage class
      """
      source_comp,sourcebox = source
      sink_comp,sinkbox = sink
      linkage(source_comp, sink_comp, sourcebox, sinkbox,self.postoffice,passthrough=passthrough,pipewidth=pipewidth,synchronous=synchronous)

   def recv(self,boxname="inbox"):
      """'C.recv("boxname")' -
      returns the first piece of data in the requested inbox.

      Used by a component to recieve a message from the outside world.
      All comms goes via a named box/input queue

      You will want to call this method to actually recieve messages you've been
      sent. You will want to check for new messages using dataReady first
      though.

      You are unlikely to want to override this method.
      """
      result = self.inboxes[boxname][0]
      del self.inboxes[boxname][0]
      return result

   def send(self,message, boxname="outbox",force=False):
      """'C.send(message, "boxname")' -
      appends message to the requested outbox.

      Used by a component to send a message to the outside world.
      All comms goes via a named box/output queue

      You will want to call this method to send messages. They are NOT sent
      immediately. They are placed in your outbox called 'boxname', and are
      periodically collected & delivered by the postman.
      
      If the outbox is synchronised then noSpaceInBox will be raised if the box
      is full unless force is True which should only be used with great care.

      You are unlikely to want to override this method.
      """
      try:
         (boxtype,maxdepth) =self.synchronised["outbox"][boxname]
         if len(self.outboxes[boxname]) >= maxdepth and not force:
            raise noSpaceInBox
      except KeyError:
         pass
      self.outboxes[boxname].append(message)

   def _collect(self, boxname="outbox"):
      """**INTERNAL** 'C._collect("boxname")' -
      returns the first piece of data in the requested outbox.

      Used by a postman to collect messages to the outside world from
      a particular outbox of this component.

      **You are unlikely to want to call this method directly.** You are unlikely to
      want to override this.
      """
      result = self.outboxes[boxname][0]
      del self.outboxes[boxname][0]
      return result


   def _safeCollect(self, boxname="outbox"):
      """C.safeCollect("boxname")' - returns the first piece of data in the requested outbox.

      Used by ../NewInternetConnection.py currently - in _test_ code. Not normally called by clients
      """
      try:
         return self._collect(boxname)
      except IndexError:
         pass

   def _collectInbox(self, boxname="inbox"):
      """**INTERNAL** 'C._collect("boxname")' -
      returns the first piece of data in the requested inbox.

      XXXX Used for passthrough deliveries

      Used by a postman to collect messages to be passed through
      a particular inbox of this component.

      **You are unlikely to want to call this method directly.** You are unlikely to
      want to override this.
      """
      result = self.inboxes[boxname][0]
      del self.inboxes[boxname][0]
      return result

   def _deliver(self,message,boxname="inbox",force=False):
      """**INTERNAL** 'C._deliver(message, "boxname")' -
      appends message to the requested inbox.

      Used by a postman to deliver messages from the outside world to
      a particular inbox of this component.  Raises noSpaceInbox if the box is
      synchronised and full unless force is true when it carrys on and overfills.

      **You are unlikely to want to call this method directly.** You are unlikely to
      want to override this method.
      """
      try:
         (boxtype,maxdepth) =self.synchronised["inbox"][boxname]
         if len(self.inboxes[boxname]) >= maxdepth and not force:
            raise noSpaceInBox
      except KeyError:
         pass
      self.inboxes[boxname].append(message)
      self._unpause()

   def _passThroughDeliverOut(self,message,boxname="outbox",force=False):
      """**INTERNAL** 'C.passThroughDeliver(message, "boxname")' -
      appends message to the requested outbox.

      Used by a postman to deliver messages from a subcomponent outbox to
      a component's outbox - ie a pass through linkage.  Raises noSpaceInbox if
      the box is synchronised and full unless force is true when it carrys on and
      overfills.

      **You are unlikely to want to call this method directly.** You are unlikely to
      want to override this method.
      """
      # Delegate to send method. (Reason for having this function rather than just
      # name is to have the documentation!
      self.send(message, boxname, force)

   def _passThroughDeliverIn(self,message,boxname="inbox",force=False):
      """**INTERNAL** 'C.passThroughDeliver(message, "boxname")' -
      appends message to the requested outbox.

      Used by a postman to deliver messages from a supercomponent inbox to
      a subcomponent's inbox - ie a pass through linkage.  Raises noSpaceInbox if
      the box is synchronised and full unless force is true when it carrys on and
      overfills.

      **You are unlikely to want to call this method directly.** You are unlikely to
      want to override this method.
      """
      # Delegate to _deliver method. (Reason for having this function rather than just
      # name is to have the documentation!
      self._deliver(message, boxname,force)

   def main(self):
      """'C.main()' **You normally will not want to override or call this method**
      This is the function that gets called by microprocess. If you override
      this do so with care. If you don't do it properly, your initialiseComponent,
      mainBody & closeDownComponent parts will not be called. Ideally you
      should not NEED to override this method. You also should not call this
      method directly since activate does this for you in order to create a
      microthread of control.

      """
      result = self.initialiseComponent()
      if not result:
         result = 1
      yield result
      while(result):
         result = self.mainBody()
         if result:
            yield result
      yield self.closeDownComponent()

   def initialiseComponent(self):
      """Stub method. **This method is designed to be overridden.** """
      return 1
   def mainBody(self):
      """Stub method. **This method is designed to be overridden.** """
      return None
   def closeDownComponent(self):
      """Stub method. **This method is designed to be overridden.** """
      return 1
   def _closeDownMicroprocess(self):
      return shutdownMicroprocess(self.postoffice)

if __name__ == '__main__':
   def producersConsumersSystemTest():
      class Producer(component):
         Inboxes=[]
         Outboxes=["result"]
         def __init__(self):
            super(Producer,self).__init__()
         def main(self):
            i = 100
            while(i):
               i = i -1
               self.send("hello", "result")
               yield  1

      class Consumer(component):
         Inboxes=["source"]
         Outboxes=["result"]
         def __init__(self):
            super(Consumer,self).__init__()
            self.count = 0
            self.i = 30
         def doSomething(self):
            print self.name, "Woo",self.i
            if self.dataReady("source"):
               self.recv("source")
               self.count = self.count +1
               self.send(self.count, "result")

         def main(self):
            yield 1
            while(self.i):
               self.i = self.i -1
               self.doSomething()
               yield 1

      class testComponent(component):
         Inboxes=["_output"]
         Outboxes=["output"]
         def __init__(self):
            super(testComponent, self).__init__()

            self.lackofinterestingthingscount = 0
            self.total = 0

            self.producer, self.consumer =Producer(), Consumer()
            self.producer2, self.consumer2 = Producer(), Consumer()

            self.addChildren(self.producer, self.producer2, self.consumer, self.consumer2)

            self.link((self.producer, "result"), (self.consumer, "source"))
            linkage(self.producer2, self.consumer2, "result", "source", self.postoffice)
            linkage(self.consumer,self,"result","_output", self.postoffice)
            linkage(self.consumer2,self,"result","_output", self.postoffice)
         def childComponents(self):
            return [self.producer, self.consumer,self.producer2, self.consumer2]
         def mainBody(self):
            if len(self.inboxes["_output"]) > 0:
               result = self.recv("_output")
               self.total = self.total + result
               print "Result recieved from consumer : ", result, "!"
               print "New Total : ", self.total, "!"
            else:
               self.lackofinterestingthingscount = self.lackofinterestingthingscount +1
               if self.lackofinterestingthingscount > 2:
                  print "Exiting. Nothing interesting for ", self.lackofinterestingthingscount, " iterations"
                  return 0
            return 1

      r = scheduler()
      p = testComponent()
      children = p.childComponents()
      p.activate()
      for p in children:
         p.activate()
      scheduler.run.runThreads(slowmo=0)# context = r.runThreads()

   producersConsumersSystemTest()
