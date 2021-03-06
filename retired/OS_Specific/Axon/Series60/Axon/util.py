#!/usr/bin/python
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
"""
General utility functions & common includes
"""

#import sets
from AxonExceptions import invalidComponentInterface


#"""This sets the system into production moe which means that many exception could be suppressed to allow the system to keep running.  Test all code with this set to false so that you are alerted to errors"""
production=False

def logError(someException, *args):
    "Currently does nothing but can be rewritten to log ignored errors if the production value is true."
    pass

def axonRaise(someException,*args):
    if production:
        logError(someException, *args)
        return False
    else:
        raise someException(*args)

def removeAll(xs, y):
   """ Very simplistic method of removing all occurances of y in list xs.
   """
   try:
      while 1:
         del xs[xs.index(y)]
   except ValueError, reason:
      if not reason.__str__() == "list.index(x): x not in list":
         raise ValueError, reason

def listSubset(requiredList, suppliedList):
   """Returns True if requiredList is a subset of suppliedList, False otherwise.
   Efficient for short required lists but copying and sorting both lists first
   may be better if required list is long."""
   for item in requiredList:
      if not item in suppliedList:
         return False
   return True

def testInterface(theComponent, interface):
   "Look for a minimal match interface for the component"
   (requiredInboxes,requiredOutboxes) = interface
   if not listSubset(requiredInboxes, theComponent.Inboxes):
      return axonRaise(invalidComponentInterface, "inboxes", theComponent, interface)
   if not listSubset(requiredOutboxes, theComponent.Outboxes):
      return axonRaise(invalidComponentInterface,"outboxes", theComponent, interface)
   return True

def safeList(arg=None):
   try:
      return list(arg)
   except TypeError:
      return []

class Finality(Exception):
   """Used for implementing try...finally... inside a generator
   """
   pass
   
